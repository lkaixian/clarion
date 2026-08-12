from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access

router = APIRouter(prefix="/patients", tags=["patients"])


def _serialize_patient(p: models.Patient) -> dict:
    return {
        "id": p.id, "full_name": p.full_name, "date_of_birth": p.date_of_birth,
        "gender": p.gender, "national_id": p.national_id, "blood_type": p.blood_type,
        "phone": p.phone, "senior_citizen_mode": p.senior_citizen_mode,
        "conditions": [{"name": c.name, "status": c.status, "is_chronic": c.is_chronic} for c in p.conditions],
        "medications": [{"drug_name": m.drug_name, "active": m.active, "prescribed_by_facility": m.prescribed_by_facility} for m in p.medications],
        "allergies": [{"substance": a.substance, "severity": a.severity} for a in p.allergies],
        "encounters": [{"facility_name": e.facility_name, "encounter_type": e.encounter_type, "started_at": str(e.started_at)} for e in p.encounters],
    }


@router.post("", response_model=schemas.PatientOut)
def create_patient(
    payload: schemas.PatientCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = models.Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    log_access(db, patient.id, current_user.id, current_user.role, "create_patient")
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
               fields=["all"])
    return _serialize_patient(patient)


@router.post("/{patient_id}/conditions")
def add_condition(
    patient_id: str, payload: schemas.ConditionCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    condition = models.Condition(patient_id=patient_id, **payload.model_dump())
    db.add(condition)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_condition", detail=payload.name)
    return {"status": "ok"}


@router.post("/{patient_id}/medications")
def add_medication(
    patient_id: str, payload: schemas.MedicationCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    med = models.MedicationStatement(patient_id=patient_id, **payload.model_dump())
    db.add(med)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_medication", detail=payload.drug_name)
    return {"status": "ok"}


@router.post("/{patient_id}/allergies")
def add_allergy(
    patient_id: str, payload: schemas.AllergyCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    allergy = models.AllergyIntolerance(patient_id=patient_id, **payload.model_dump())
    db.add(allergy)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_allergy", detail=payload.substance)
    return {"status": "ok"}


@router.post("/{patient_id}/encounters")
def add_encounter(
    patient_id: str, payload: schemas.EncounterCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Recording a transfer/visit here is what powers the 'what changed since
    last visit' transfer view on the web console."""
    encounter = models.Encounter(patient_id=patient_id, **payload.model_dump())
    db.add(encounter)
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "add_encounter", detail=payload.facility_name)
    return {"status": "ok"}


@router.get("/{patient_id}/audit-log")
def get_audit_log(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patients (and staff) can review exactly who accessed the record and
    when — this is the transparency half of the PDPA-aligned design."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's audit log")

    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id)
        .order_by(models.AuditLog.timestamp.desc())
        .all()
    )
    return [
        {
            "actor": l.actor, "actor_role": l.actor_role, "action": l.action,
            "fields_accessed": l.fields_accessed, "timestamp": str(l.timestamp),
            "detail": l.detail,
        }
        for l in logs
    ]
