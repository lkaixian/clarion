from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..audit import log_access
from ..ai.summarize import generate_handover_brief
from ..ai.interactions import check_interactions, check_duplicate_prescriptions
from ..ai.ocr import extract_text_from_image, extract_structured_fields
from .patients import _serialize_patient

router = APIRouter(prefix="/ai", tags=["ai"])


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
def get_interaction_check(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    active_meds = [m for m in patient.medications if m.active]
    drug_names = [m.drug_name for m in active_meds]
    med_dicts = [{"drug_name": m.drug_name, "active": m.active, "prescribed_by_facility": m.prescribed_by_facility} for m in active_meds]

    interactions = check_interactions(drug_names)
    duplicates = check_duplicate_prescriptions(med_dicts)

    log_access(db, patient_id, current_user.id, current_user.role, "run_interaction_check")
    return {"interactions": interactions, "cross_facility_duplicates": duplicates}


@router.post("/digitise/{patient_id}")
async def digitise_document(
    patient_id: str, doc_type: str, db: Session = Depends(get_db),
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    """Upload a scanned document (prescription, discharge summary, lab
    report). Runs OCR, stores the raw text + a lightweight extraction, and
    creates a ClinicalDocument row a human can review before finalising."""
    import tempfile, os

    suffix = os.path.splitext(file.filename or "")[1] or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    raw_text = extract_text_from_image(tmp_path)
    structured = extract_structured_fields(raw_text)
    os.unlink(tmp_path)

    doc = models.ClinicalDocument(
        patient_id=patient_id, doc_type=doc_type, original_filename=file.filename,
        raw_text=raw_text, uploaded_by_facility=current_user.facility,
    )
    db.add(doc)
    db.commit()

    log_access(db, patient_id, current_user.id, current_user.role, "upload_document", detail=doc_type)

    return {
        "document_id": doc.id,
        "raw_text": raw_text,
        "structured_guess": structured,
        "note": "Extraction is unreviewed — a records officer should confirm "
                "before these fields are added as formal Condition/Medication entries.",
    }
