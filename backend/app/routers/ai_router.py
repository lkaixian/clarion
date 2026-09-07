import logging
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import models, auth, schemas
from ..database import get_db
from ..audit import log_access
from ..ai.summarize import generate_handover_brief
from ..ai.interactions import (
    MedicationProvider,
    check_interactions,
    check_duplicate_prescriptions,
    get_medication_support,
)
from ..ai.ocr import extract_text_from_image, extract_structured_fields
from ..storage import BUCKET_DOCUMENTS, ObjectStoreError, apply_object_meta, get_object_store, sanitize_filename
from ..derived import prime_thumbnail
from ..imaging import ImageProcessingError, is_supported_image, validate_image_safe_to_decode
from ._uploads import enforce_upload_size, sniff_document_mime
from .patients import _serialize_patient

router = APIRouter(prefix="/ai", tags=["ai"])

logger = logging.getLogger("clarion.ai")

# Original uploaded files are persisted after OCR to the `clarion-documents`
# ObjectStore bucket (see app/storage.py) at key
# `{patient_id}/{document_id}_{sanitized_basename}`, retrievable via
# GET /patients/{patient_id}/documents/{document_id}/file. WORM-locked for
# 7 years on the MinIO target; no retention job on the local demo store.

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

    # Threaded db + current_user so cross-facility record filtering
    # (HospitalSetting.records_shared_publicly) and per-record editability
    # apply here too -- the handover brief should reflect what this clinician
    # is actually allowed to see. Note: this is a same-facility clinical
    # tool, not the emergency-scan path, so the sharing filter DOES apply.
    record = _serialize_patient(patient, db, current_user)
    brief = generate_handover_brief(record)
    log_access(db, patient_id, current_user.id, current_user.role, "generate_handover_brief",
               actor_facility=current_user.facility)
    return {"handover_brief": brief}


@router.get("/interaction-check/{patient_id}")
async def get_interaction_check(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Go through _serialize_patient (not patient.medications directly) so the
    # records_shared_publicly filter applies: a facility that has opted out of
    # public sharing must NOT have its drug names leak here -- neither into the
    # interaction/support results nor, especially, into
    # `cross_facility_duplicates` strings that would otherwise name the
    # opted-out facility alongside the drug.
    record = _serialize_patient(patient, db, current_user)
    active_meds = [m for m in record["medications"] if m.get("active")]
    drug_names = [m["drug_name"] for m in active_meds]
    med_dicts = [{"drug_name": m["drug_name"], "active": m["active"], "prescribed_by_facility": m.get("prescribed_by_facility")} for m in active_meds]

    # One provider instance shared across all three calls so the in-process
    # RxNorm/DailyMed cache dedupes normalization -- previously each call
    # re-resolved every drug from scratch (3x the external traffic for the
    # same drug set). Kept sequential rather than gathered: with the shared
    # cache the 2nd and 3rd calls are near-free cache hits, which is less
    # total work (and less load on NIH) than three concurrent cold lookups
    # racing each other. Code-review follow-up 2026-09-07.
    provider = MedicationProvider()
    interactions = await check_interactions(drug_names, provider=provider)
    duplicates = await check_duplicate_prescriptions(med_dicts, provider=provider)
    medication_support = await get_medication_support(drug_names, provider=provider)

    log_access(db, patient_id, current_user.id, current_user.role, "run_interaction_check",
               actor_facility=current_user.facility)
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

    Also persists the original uploaded file to the ObjectStore (see the
    module comment) so it can be retrieved later via
    GET /patients/{patient_id}/documents/{document_id}/file -- previously
    the temp file was OCR'd then immediately os.unlink'd, so only the
    extracted text was ever recoverable, never the original image/scan
    itself. Persistence is best-effort: a storage failure here never blocks
    or rolls back the OCR ingestion that already succeeded."""
    if doc_type not in schemas.VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type must be one of: {', '.join(sorted(schemas.VALID_DOC_TYPES))}",
        )

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    suffix = os.path.splitext(file.filename or "")[1] or ".png"
    enforce_upload_size(file, MAX_UPLOAD_BYTES, "File")
    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large — max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    # Sanitized basename -- also the trailing segment of the object key
    # built below, so the DB/API/Content-Disposition value seen elsewhere
    # (e.g. GET .../documents/{document_id}/file) never echoes the raw,
    # attacker-controlled multipart filename verbatim.
    safe_name = sanitize_filename(file.filename, fallback="upload")

    # Security Audit M5: this endpoint used to hand ANY uploaded bytes
    # straight to PIL/pytesseract with no format allowlist, pixel-bomb
    # ceiling, or animation-frame guard of its own -- app/imaging.py (P1.7)
    # already built exactly that hardening for the medicine-photo and
    # document-preview paths, but this one bypassed it entirely, so e.g. a
    # crafted TIFF (the CVE-prone format P1.7 deliberately excludes) could
    # still reach a raw Image.open() here. A non-image upload (a genuine
    # PDF scan, most commonly) is NOT rejected -- OCR is simply skipped for
    # it, same tolerant behavior as before; only the "is this superficially
    # image-shaped" path is now safety-gated before any decode is attempted.
    if is_supported_image(file_bytes):
        try:
            await run_in_threadpool(validate_image_safe_to_decode, file_bytes)
        except ImageProcessingError as exc:
            raw_text = f"[OCR skipped: image failed safety validation ({exc})]"
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            # Tesseract OCR is a blocking subprocess (the heaviest op in this
            # handler). This is an `async def` route, so run it off-thread or
            # it blocks the event loop for every other request. Security
            # Code-review follow-up 2026-09-07 -- the validate/thumbnail calls were already
            # threadpooled here; this one and the ObjectStore put below were
            # missed.
            try:
                raw_text = await run_in_threadpool(extract_text_from_image, tmp_path)
            finally:
                os.unlink(tmp_path)
    else:
        raw_text = "[OCR skipped: not an image format OCR supports — archived as-is]"
    structured = extract_structured_fields(raw_text)

    doc = models.ClinicalDocument(
        patient_id=patient_id, doc_type=doc_type, original_filename=safe_name,
        raw_text=raw_text, uploaded_by_facility=current_user.facility,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        # mime is derived from the file's own magic bytes, never the
        # client's Content-Type header -- the serve path additionally
        # re-guesses from the key against a strict allowlist.
        meta = await run_in_threadpool(
            get_object_store().put,
            BUCKET_DOCUMENTS,
            f"{patient_id}/{doc.id}_{safe_name}",
            file_bytes,
            mime=sniff_document_mime(file_bytes),
        )
        apply_object_meta(doc, meta, "file")
        db.add(doc)
        db.commit()
        # P1.7: pre-build the preview thumbnail (no-op for a PDF / non-image).
        # The WORM original is untouched -- prime_thumbnail only reads it. Runs
        # in the threadpool: this is an `async def` handler and a Pillow decode
        # would otherwise block the event loop for every other request.
        await run_in_threadpool(prime_thumbnail, BUCKET_DOCUMENTS, meta.key, meta.sha256)
    except (OSError, ValueError, ObjectStoreError):
        # Best-effort persistence: the OCR ingestion already succeeded and is
        # not rolled back. But this used to swallow the storage failure
        # entirely -- the document's original scan silently never reached the
        # object store and nobody knew. Log it (the response's
        # `file_persisted: false` also signals it to the caller).
        db.rollback()
        logger.warning(
            "clinical document original NOT persisted to object store "
            "(OCR row kept) patient=%s doc=%s type=%s",
            patient_id, doc.id, doc_type, exc_info=True,
        )

    log_access(db, patient_id, current_user.id, current_user.role, "upload_document", detail=doc_type,
               actor_facility=current_user.facility)

    return {
        "document_id": doc.id,
        "raw_text": raw_text,
        "structured_guess": structured,
        "file_persisted": bool(doc.file_object_key),
        "note": "Extraction is unreviewed — a records officer should confirm "
                "before these fields are added as formal Condition/Medication entries.",
    }
