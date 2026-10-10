"""
Dental module (P3.2, the tender).

Only the tooth chart is new here. Everything else the clause asks for reuses
an existing engine unchanged -- see models.py's "Dental engine" section
comment for the full clause-by-clause mapping:
  - "Sign-off" + queue/appointments ->
    routers/consultation.py + routers/reception (a room/ticket tagged
    department="Dental" -- no schema or code change needed there).
  - X-ray references -> routers/ancillary.py's
    ServiceRequest(module="xray", source_encounter_id=...) directly.
  - Medication -> routers/patients.py's existing
    add_medication/update_medication.
  - Diagnosis reporting -> routers/patients.py's existing
    Condition CRUD. DMC/Referral Letter/Timeslip document generation is
    P3.5's job (no document-generation engine exists yet).

Each DentalChartEntry is create-with-signature -- same immutable-once-signed
shape as ancillary.py::sign_off_service_request and
patients.py::add_record_annotation. RBAC: CHART_ROLES only
(admin/records_officer/clinician) -- a receptionist is a front-desk role,
not a clinical reader/writer, same line ancillary.py and patients.py already
draw.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas, auth, seal
from ..database import get_db
from ..audit import log_access
from ..storage import apply_object_meta
from ..clinical_access import _hidden_author_facilities
from .profile import save_signature_from_b64, copy_signature_snapshot

router = APIRouter(prefix="/dental", tags=["dental"])

CHART_ROLES = ("admin", "records_officer", "clinician")


@router.get("/chart-options", response_model=schemas.DentalChartOptionsOut)
def get_chart_options(
    current_user: models.User = Depends(auth.require_roles(*CHART_ROLES)),
):
    """Static FDI tooth codes + finding/treatment vocabularies -- so the
    tooth-chart UI never hardcodes them."""
    return schemas.DentalChartOptionsOut(
        tooth_codes=list(models.DENTAL_TOOTH_CODES),
        findings=list(models.DENTAL_FINDINGS),
        treatments=list(models.DENTAL_TREATMENTS),
    )


@router.get("/chart/{patient_id}", response_model=List[schemas.DentalChartEntryOut])
def get_dental_chart(
    patient_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CHART_ROLES)),
):
    """A patient's full tooth-chart history, newest first -- same universal
    cross-facility clinical read as patients.py::get_patient_full_record,
    MINUS whatever an authoring facility has opted out of public sharing
    (HospitalSetting.records_shared_publicly). The hidden-facility exclusion
    is applied in SQL BEFORE offset/limit (learned the hard way in P3.1's
    review: filtering after pagination under-fills/misaligns pages)."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    q = db.query(models.DentalChartEntry).filter(models.DentalChartEntry.patient_id == patient_id)

    hidden = _hidden_author_facilities(db, current_user.facility)
    if hidden:
        q = q.filter(
            or_(
                models.DentalChartEntry.facility_name.is_(None),
                models.DentalChartEntry.facility_name.notin_(hidden),
            )
        )

    rows = q.order_by(models.DentalChartEntry.created_at.desc()).offset(offset).limit(limit).all()

    log_access(
        db, patient_id, current_user.id, current_user.role, "view_dental_chart",
        actor_facility=current_user.facility,
    )
    return rows


@router.post("/chart", response_model=schemas.DentalChartEntryOut, status_code=201)
def create_dental_chart_entry(
    payload: schemas.DentalChartEntryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CHART_ROLES)),
):
    """Record + sign one tooth-level observation in a single atomic action
    -- same shape as ancillary.py::sign_off_service_request. REQUIRES a
    saved digital signature; pass `signature_b64` to save one on the spot."""
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if payload.encounter_id:
        encounter = db.query(models.Encounter).filter(models.Encounter.id == payload.encounter_id).first()
        if encounter is None or encounter.patient_id != payload.patient_id:
            raise HTTPException(status_code=404, detail="encounter_id not found for this patient")

    if not current_user.signature_object_key and not payload.signature_b64:
        raise HTTPException(
            status_code=409,
            detail="Save your signature in your profile before recording a dental chart entry.",
        )
    if payload.signature_b64 and not current_user.signature_object_key:
        save_signature_from_b64(db, current_user, payload.signature_b64)

    entry = models.DentalChartEntry(
        patient_id=payload.patient_id,
        encounter_id=payload.encounter_id,
        tooth_code=payload.tooth_code,
        finding=payload.finding,
        treatment=payload.treatment,
        notes=payload.notes,
        facility_name=current_user.facility,
        recorded_by=current_user.id,
        recorded_by_name=current_user.full_name,
        recorded_by_role=current_user.role,
        signed_by=current_user.id,
        signed_by_name=current_user.full_name,
        signed_by_role=current_user.role,
    )
    db.add(entry)
    db.flush()  # need entry.id for the per-row signature snapshot key

    apply_object_meta(
        entry,
        copy_signature_snapshot(current_user, f"dental-chart/{entry.id}.png"),
        "signature",
    )
    seal.seal("dental_entry", entry)
    db.add(entry)
    db.commit()
    db.refresh(entry)

    log_access(
        db, patient.id, current_user.id, current_user.role, "dental_chart_entry_created",
        detail=f"tooth={entry.tooth_code} finding={entry.finding} treatment={entry.treatment} entry_id={entry.id}",
        actor_facility=current_user.facility,
    )
    return entry
