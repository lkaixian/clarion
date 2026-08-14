import mimetypes
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..nric import normalize_nric

router = APIRouter(prefix="/patients", tags=["patients"])

# Content-Types this app actually needs to serve inline/safely from
# GET /patients/{id}/documents/{document_id}/file -- scanned prescriptions,
# lab reports, discharge summaries, X-ray/imaging. Anything guessed outside
# this allowlist (in particular text/html, which a browser will happily
# execute in this app's own origin) is forced to application/octet-stream
# instead, which browsers only ever download, never render/execute. See
# get_document_file below -- deliberately guessed from the sanitized
# on-disk filename (ClinicalDocument.file_path), never from the
# attacker-controlled ClinicalDocument.original_filename.
SAFE_DOCUMENT_MEDIA_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf",
}


def _serialize_patient(p: models.Patient) -> dict:
    return {
        "id": p.id, "full_name": p.full_name, "date_of_birth": p.date_of_birth,
        "gender": p.gender, "national_id": p.national_id, "blood_type": p.blood_type,
        "phone": p.phone, "senior_citizen_mode": p.senior_citizen_mode,
        "email": p.email, "emergency_contact_name": p.emergency_contact_name,
        "emergency_contact_phone": p.emergency_contact_phone,
        "emergency_contact_relationship": p.emergency_contact_relationship,
        "conditions": [
            {
                "id": c.id, "name": c.name, "status": c.status,
                "diagnosed_at": c.diagnosed_at, "is_chronic": c.is_chronic,
                "critical_for_emergency": c.critical_for_emergency,
            }
            for c in p.conditions
        ],
        "medications": [
            {
                "id": m.id, "drug_name": m.drug_name, "dosage": m.dosage,
                "frequency": m.frequency, "prescribed_by_facility": m.prescribed_by_facility,
                "start_date": m.start_date, "active": m.active,
                "critical_for_emergency": m.critical_for_emergency,
            }
            for m in p.medications
        ],
        "allergies": [
            {
                "id": a.id, "substance": a.substance, "reaction": a.reaction,
                "severity": a.severity, "critical_for_emergency": a.critical_for_emergency,
            }
            for a in p.allergies
        ],
        "encounters": [
            {
                "id": e.id, "facility_name": e.facility_name, "encounter_type": e.encounter_type,
                "reason": e.reason, "notes": e.notes, "started_at": str(e.started_at),
            }
            for e in p.encounters
        ],
        # Summary shape only -- raw_text/ai_summary can be large OCR dumps,
        # fetched on demand via GET /patients/{id}/documents/{document_id}
        # instead so a full patient-record GET stays cheap.
        "documents": [
            {
                "id": d.id, "doc_type": d.doc_type, "original_filename": d.original_filename,
                "uploaded_by_facility": d.uploaded_by_facility, "uploaded_at": str(d.uploaded_at),
            }
            for d in p.documents
        ],
    }


@router.post("", response_model=schemas.PatientOut)
def create_patient(
    payload: schemas.PatientCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    data = payload.model_dump()

    # An empty-string national_id isn't a real NRIC -- treat it the same as
    # "no NRIC provided" (NULL) rather than a real value. Patient.national_id
    # is a nullable unique column: multiple NULLs are fine (SQLite/most DBs
    # never treat NULL as equal to NULL for a unique constraint), but two
    # patients both stored with national_id="" WOULD collide as a genuine
    # duplicate -- that's a modeling bug, not a real duplicate NRIC.
    if data.get("national_id") == "":
        data["national_id"] = None

    # Pre-insert uniqueness check, dash/case-tolerant (matches the NRIC
    # normalization used everywhere else NRICs are compared -- see
    # nric.normalize_nric / auth_router._resolve_patient_by_nric), so a
    # request that differs only by dashes or case still gets caught here
    # with a clean message instead of slipping through to a raw DB
    # IntegrityError.
    if data.get("national_id"):
        normalized_input = normalize_nric(data["national_id"])
        existing = (
            db.query(models.Patient)
            .filter(models.Patient.national_id.isnot(None))
            .all()
        )
        if any(normalize_nric(p.national_id) == normalized_input for p in existing):
            raise HTTPException(
                status_code=400,
                detail="This NRIC is already registered to another patient.",
            )

    patient = models.Patient(**data)
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        # Safety net for the pre-check above (e.g. a concurrent request
        # that snuck in between the check and this commit) -- never let a
        # raw sqlalchemy.exc.IntegrityError escape as a plain-text 500.
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="This NRIC is already registered to another patient.",
        )
    db.refresh(patient)
    log_access(db, patient.id, current_user.id, current_user.role, "create_patient",
               actor_facility=current_user.facility)
    return patient


@router.get("", response_model=List[schemas.PatientOut])
def list_patients(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    return db.query(models.Patient).all()


@router.get("/{patient_id}")
def get_patient_full_record(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # patients may only view their own record
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's record")

    log_access(db, patient_id, current_user.id, current_user.role, "view_full_record",
               fields=["all"], actor_facility=current_user.facility)
    return _serialize_patient(patient)


def _serialize_condition(c: models.Condition) -> dict:
    return {
        "id": c.id, "name": c.name, "status": c.status,
        "diagnosed_at": c.diagnosed_at, "is_chronic": c.is_chronic,
        "critical_for_emergency": c.critical_for_emergency,
    }


def _serialize_medication(m: models.MedicationStatement) -> dict:
    return {
        "id": m.id, "drug_name": m.drug_name, "dosage": m.dosage,
        "frequency": m.frequency, "prescribed_by_facility": m.prescribed_by_facility,
        "start_date": m.start_date, "active": m.active,
        "critical_for_emergency": m.critical_for_emergency,
    }


def _serialize_allergy(a: models.AllergyIntolerance) -> dict:
    return {
        "id": a.id, "substance": a.substance, "reaction": a.reaction,
        "severity": a.severity, "critical_for_emergency": a.critical_for_emergency,
    }


def _serialize_encounter(e: models.Encounter) -> dict:
    return {
        "id": e.id, "facility_name": e.facility_name, "encounter_type": e.encounter_type,
        "reason": e.reason, "notes": e.notes, "started_at": str(e.started_at),
    }


@router.post("/{patient_id}/conditions")
def add_condition(
    patient_id: str, payload: schemas.ConditionCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    condition = models.Condition(patient_id=patient_id, **payload.model_dump())
    db.add(condition)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_condition", detail=payload.name,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/conditions/{condition_id}")
def update_condition(
    patient_id: str, condition_id: str, payload: schemas.ConditionUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    condition = (
        db.query(models.Condition)
        .filter(models.Condition.id == condition_id, models.Condition.patient_id == patient_id)
        .first()
    )
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(condition, field, value)

    if submitted_fields:
        db.add(condition)
        db.commit()
        db.refresh(condition)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_condition",
        fields=sorted(submitted_fields.keys()), detail=condition_id,
        actor_facility=current_user.facility,
    )
    return _serialize_condition(condition)


@router.post("/{patient_id}/medications")
def add_medication(
    patient_id: str, payload: schemas.MedicationCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    med = models.MedicationStatement(patient_id=patient_id, **payload.model_dump())
    db.add(med)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_medication", detail=payload.drug_name,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/medications/{medication_id}")
def update_medication(
    patient_id: str, medication_id: str, payload: schemas.MedicationUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    med = (
        db.query(models.MedicationStatement)
        .filter(models.MedicationStatement.id == medication_id, models.MedicationStatement.patient_id == patient_id)
        .first()
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(med, field, value)

    if submitted_fields:
        db.add(med)
        db.commit()
        db.refresh(med)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_medication",
        fields=sorted(submitted_fields.keys()), detail=medication_id,
        actor_facility=current_user.facility,
    )
    return _serialize_medication(med)


@router.post("/{patient_id}/allergies")
def add_allergy(
    patient_id: str, payload: schemas.AllergyCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    allergy = models.AllergyIntolerance(patient_id=patient_id, **payload.model_dump())
    db.add(allergy)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_allergy", detail=payload.substance,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/allergies/{allergy_id}")
def update_allergy(
    patient_id: str, allergy_id: str, payload: schemas.AllergyUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    allergy = (
        db.query(models.AllergyIntolerance)
        .filter(models.AllergyIntolerance.id == allergy_id, models.AllergyIntolerance.patient_id == patient_id)
        .first()
    )
    if not allergy:
        raise HTTPException(status_code=404, detail="Allergy not found")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(allergy, field, value)

    if submitted_fields:
        db.add(allergy)
        db.commit()
        db.refresh(allergy)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_allergy",
        fields=sorted(submitted_fields.keys()), detail=allergy_id,
        actor_facility=current_user.facility,
    )
    return _serialize_allergy(allergy)


@router.post("/{patient_id}/encounters")
def add_encounter(
    patient_id: str, payload: schemas.EncounterCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Recording a transfer/visit here is what powers the 'what changed since
    last visit' transfer view on the web console."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    encounter = models.Encounter(patient_id=patient_id, **payload.model_dump())
    db.add(encounter)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_encounter", detail=payload.facility_name,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/encounters/{encounter_id}")
def update_encounter(
    patient_id: str, encounter_id: str, payload: schemas.EncounterUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Staff-only edit/correction for an existing encounter (e.g. fixing a
    typo'd reason/notes after the fact) -- the POST above stays create-only,
    this is what backs an eventual 'edit visit' UI action."""
    encounter = (
        db.query(models.Encounter)
        .filter(models.Encounter.id == encounter_id, models.Encounter.patient_id == patient_id)
        .first()
    )
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(encounter, field, value)

    if submitted_fields:
        db.add(encounter)
        db.commit()
        db.refresh(encounter)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_encounter",
        fields=sorted(submitted_fields.keys()), detail=encounter_id,
        actor_facility=current_user.facility,
    )
    return _serialize_encounter(encounter)


@router.patch("/{patient_id}/profile", response_model=schemas.PatientOut)
def update_own_profile(
    patient_id: str,
    payload: schemas.PatientProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Self-service only, for now: a patient editing their OWN contact
    profile (email/phone/emergency contact). No staff-editing variant here
    by design -- out of scope for this pass.

    full_name / date_of_birth / national_id are immutable via self-service
    identity fields: a request that tries to set any of them is explicitly
    rejected with a clear 400, not silently ignored, so a caller isn't
    misled into thinking an identity-field change actually took effect.
    """
    if current_user.role != "patient" or current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot edit another patient's profile")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    submitted_fields = payload.model_dump(exclude_unset=True)

    attempted_immutable = sorted(set(submitted_fields) & schemas.PATIENT_IMMUTABLE_FIELDS)
    if attempted_immutable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change {', '.join(attempted_immutable)} via profile self-service. "
                "These identity fields are immutable outside of staff-mediated changes."
            ),
        )

    changed_fields = []
    for field in schemas.PATIENT_SELF_EDITABLE_FIELDS:
        if field in submitted_fields:
            setattr(patient, field, submitted_fields[field])
            changed_fields.append(field)

    if changed_fields:
        db.add(patient)
        db.commit()
        db.refresh(patient)

    # Log which fields changed, not their new values -- the values
    # themselves are contact PII that shouldn't end up duplicated in a
    # more exposed place (the audit log) than the field already lives.
    log_access(
        db, patient_id, current_user.id, current_user.role, "update_own_profile",
        fields=changed_fields, actor_facility=current_user.facility,
    )
    return patient


@router.get("/{patient_id}/audit-log")
def get_audit_log(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patients (and staff) can review exactly who accessed the record and
    when — this is the transparency half of the PDPA-aligned design.

    `actor_name` is resolved via a LIVE join against `users.full_name`
    (not a value stored/snapshotted on the AuditLog row itself) -- see
    models.AuditLog's class docstring for the reasoning: a later name
    correction (typo fix, legal name change) should be reflected in old
    history too, not stay frozen/wrong. `actor_facility`, in contrast, IS a
    snapshot straight off the row (no join needed) -- same docstring covers
    why those two fields are deliberately handled differently.

    `actor` is only ever a real `users.id` for a staff/patient action --
    the "system" actor and the unauthenticated emergency-scan endpoints'
    "emergency_responder:<name>" actor have no matching `User` row at all,
    so the join is skipped for those (and for a staff `User` account that
    has since been deleted, the lookup just degrades to `actor_name=None`
    rather than a 500 -- "who" for that row is still available via the raw
    `actor` id, just not resolvable to a live display name anymore).
    """
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's audit log")

    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id)
        .order_by(models.AuditLog.timestamp.desc())
        .all()
    )

    # Batch-resolve actor -> full_name in one query instead of one query per
    # row -- skip "system" and "emergency_responder:*" actors up front since
    # neither is ever a real users.id, so there's no point even trying them
    # against the User table.
    real_user_actor_ids = {
        l.actor for l in logs
        if l.actor != "system" and not l.actor.startswith("emergency_responder:")
    }
    actor_names = {}
    if real_user_actor_ids:
        for user_id, full_name in (
            db.query(models.User.id, models.User.full_name)
            .filter(models.User.id.in_(real_user_actor_ids))
            .all()
        ):
            actor_names[user_id] = full_name

    return [
        {
            "actor": l.actor, "actor_role": l.actor_role, "action": l.action,
            "fields_accessed": l.fields_accessed, "timestamp": str(l.timestamp),
            "detail": l.detail,
            # Additive fields -- existing web/mobile clients that only read
            # the keys above keep working unchanged.
            "actor_name": actor_names.get(l.actor),  # None if unresolvable (system/emergency/deleted account)
            "actor_facility": l.actor_facility,
        }
        for l in logs
    ]


def _get_document_or_404(db: Session, patient_id: str, document_id: str) -> models.ClinicalDocument:
    # Check the patient exists first -- there's no FK enforcement between
    # ClinicalDocument.patient_id and Patient.id (SQLite foreign_keys pragma
    # is off), so a bogus patient_id must not silently succeed just because
    # a matching (possibly orphaned) document row happens to exist. Mirrors
    # how the rest of the API treats a nonexistent patient_id (see
    # get_patient_full_record above).
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    document = (
        db.query(models.ClinicalDocument)
        .filter(models.ClinicalDocument.id == document_id, models.ClinicalDocument.patient_id == patient_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{patient_id}/documents/{document_id}")
def get_document_detail(
    patient_id: str, document_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Full document detail, including the (potentially large) raw_text OCR
    dump and ai_summary -- deliberately NOT part of _serialize_patient's
    'documents' summary list, fetched here on demand instead. Staff-only,
    same roles as the AI handover-brief/interaction-check endpoints -- a
    patient viewing their own record does not get document detail access in
    this pass."""
    document = _get_document_or_404(db, patient_id, document_id)

    log_access(db, patient_id, current_user.id, current_user.role, "view_document", detail=document_id,
               actor_facility=current_user.facility)
    return {
        "id": document.id,
        "doc_type": document.doc_type,
        "original_filename": document.original_filename,
        "uploaded_by_facility": document.uploaded_by_facility,
        "uploaded_at": str(document.uploaded_at),
        "raw_text": document.raw_text,
        "ai_summary": document.ai_summary,
        # Whether the ORIGINAL uploaded file (not just its OCR'd text) can be
        # fetched from GET .../documents/{document_id}/file below. False for
        # any document uploaded before file persistence existed, or if the
        # disk write failed at upload time.
        "file_available": bool(document.file_path) and os.path.isfile(document.file_path),
    }


@router.get("/{patient_id}/documents/{document_id}/file")
def get_document_file(
    patient_id: str, document_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Serves back the original uploaded file (X-ray image, scanned lab
    report, etc.) as persisted by POST /ai/digitise/{patient_id}. 404 if no
    file was ever persisted for this document (e.g. uploaded before this
    endpoint existed) -- only the OCR'd raw_text is available in that case,
    via GET /patients/{patient_id}/documents/{document_id} above."""
    document = _get_document_or_404(db, patient_id, document_id)

    if not document.file_path or not os.path.isfile(document.file_path):
        raise HTTPException(status_code=404, detail="Original file not available for this document")

    log_access(db, patient_id, current_user.id, current_user.role, "view_document_file", detail=document_id,
               actor_facility=current_user.facility)

    # Content-Type is guessed from the sanitized on-disk filename
    # (document.file_path is written as "{document_id}_{safe_basename}" by
    # POST /ai/digitise/{patient_id}), NEVER from the attacker-controlled
    # document.original_filename -- otherwise a file uploaded as e.g.
    # "evil.html" would be served back with Content-Type: text/html and
    # execute in this app's own origin when opened by staff (stored XSS).
    # Anything outside the small allowlist of types this app actually needs
    # falls back to application/octet-stream, which browsers only download.
    guessed_type, _ = mimetypes.guess_type(document.file_path)
    media_type = guessed_type if guessed_type in SAFE_DOCUMENT_MEDIA_TYPES else "application/octet-stream"

    return FileResponse(
        document.file_path,
        filename=document.original_filename or f"document_{document_id}",
        media_type=media_type,
    )
