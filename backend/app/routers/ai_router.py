import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import models, auth, schemas
from ..database import get_db
from ..audit import log_access
from ..ai.summarize import generate_handover_brief
from ..ai.interactions import check_interactions, check_duplicate_prescriptions, get_medication_support
from ..ai.ocr import extract_text_from_image, extract_structured_fields
from .patients import _serialize_patient

router = APIRouter(prefix="/ai", tags=["ai"])

# Where original uploaded files are persisted after OCR (see digitise_document
# below) -- backend/uploads/{patient_id}/{document_id}_{original_filename}.
# Git-ignored (see backend/.gitignore); grows unbounded with no
# retention/cleanup policy, same "demo-scale, not production storage" caveat
# as the SQLite backups directory.
UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads"

# Upload size cap for POST /ai/digitise/{patient_id} -- this endpoint OCRs
# scanned prescriptions/lab reports/discharge summaries/X-ray images, not
# video or bulk data, so 15MB comfortably covers even a high-res multi-page
# scan while blocking accidental/abusive multi-hundred-MB uploads (no size
# limit was previously enforced at all).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@router.get("/summary/{patient_id}")
def get_handover_brief(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    record = _serialize_patient(patient)
    brief = generate_handover_brief(record)
    log_access(db, patient_id, current_user.id, current_user.role, "generate_handover_brief")
    return {"handover_brief": brief}


@router.get("/interaction-check/{patient_id}")
async def get_interaction_check(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    active_meds = [m for m in patient.medications if m.active]
    drug_names = [m.drug_name for m in active_meds]
    med_dicts = [{"drug_name": m.drug_name, "active": m.active, "prescribed_by_facility": m.prescribed_by_facility} for m in active_meds]

    interactions = await check_interactions(drug_names)
    duplicates = await check_duplicate_prescriptions(med_dicts)
    medication_support = await get_medication_support(drug_names)

    log_access(db, patient_id, current_user.id, current_user.role, "run_interaction_check")
    return {
        "interactions": interactions,
        "cross_facility_duplicates": duplicates,
        "medication_support": medication_support,
    }


@router.post("/digitise/{patient_id}")
async def digitise_document(
    patient_id: str, doc_type: str, db: Session = Depends(get_db),
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    """Upload a scanned document (prescription, discharge summary, lab
    report). Runs OCR, stores the raw text + a lightweight extraction, and
    creates a ClinicalDocument row a human can review before finalising.

    Also persists the original uploaded file to disk (UPLOAD_ROOT, see
    above) so it can be retrieved later via
    GET /patients/{patient_id}/documents/{document_id}/file -- previously
    the temp file was OCR'd then immediately os.unlink'd, so only the
    extracted text was ever recoverable, never the original image/scan
    itself. File persistence is best-effort: a disk-write failure here
    never blocks or rolls back the OCR ingestion that already succeeded."""
    if doc_type not in schemas.VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type must be one of: {', '.join(sorted(schemas.VALID_DOC_TYPES))}",
        )

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    suffix = os.path.splitext(file.filename or "")[1] or ".png"
    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large — max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    # Sanitized basename -- matches what's actually used for the on-disk
    # path below, so the DB/API/Content-Disposition value seen elsewhere
    # (e.g. GET .../documents/{document_id}/file) never echoes the raw,
    # attacker-controlled multipart filename verbatim.
    safe_name = os.path.basename(file.filename or "upload")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    raw_text = extract_text_from_image(tmp_path)
    structured = extract_structured_fields(raw_text)
    os.unlink(tmp_path)

    doc = models.ClinicalDocument(
        patient_id=patient_id, doc_type=doc_type, original_filename=safe_name,
        raw_text=raw_text, uploaded_by_facility=current_user.facility,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        patient_dir = UPLOAD_ROOT / patient_id
        patient_dir.mkdir(parents=True, exist_ok=True)
        dest_path = patient_dir / f"{doc.id}_{safe_name}"
        with open(dest_path, "wb") as f:
            f.write(file_bytes)
        doc.file_path = str(dest_path)
        db.add(doc)
        db.commit()
    except OSError:
        db.rollback()

    log_access(db, patient_id, current_user.id, current_user.role, "upload_document", detail=doc_type)

    return {
        "document_id": doc.id,
        "raw_text": raw_text,
        "structured_guess": structured,
        "file_persisted": bool(doc.file_path),
        "note": "Extraction is unreviewed — a records officer should confirm "
                "before these fields are added as formal Condition/Medication entries.",
    }
