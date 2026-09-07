"""Ward admissions + Ward Map.

Per-bed admission/discharge, usable by any staff role (same STAFF_ROLES as
check-in). models.Admission is the source of truth for the bed grid; the
legacy aggregate Ward.occupied_beds counter is deliberately NOT touched
here (see the approved plan's assumptions). Each admission also records an
`inpatient` Encounter on the patient, mirroring patients.py::add_encounter.
"""
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, schemas, auth
from ...database import get_db
from ...audit import log_access
from ..auth_router import _resolve_patient_by_nric
from ._common import STAFF_ROLES

router = APIRouter()


def _resolve_patient_for_admission(db: Session, patient_id: str | None, national_id: str | None) -> models.Patient:
    """IC/patient_id patient lookup for AdmissionCreate. Kept separate from
    _resolve_patient (which is tied to ReceptionCheckinRequest's 4-identifier
    space); the IC path reuses the same indexed resolver (Security Audit M2)."""
    if national_id:
        patient = _resolve_patient_by_nric(db, national_id)
        if patient:
            return patient
        raise HTTPException(status_code=404, detail="No patient found for that IC number")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


def _active_admission_for_patient(db: Session, patient_id: str) -> models.Admission | None:
    return (
        db.query(models.Admission)
        .filter(
            models.Admission.patient_id == patient_id,
            models.Admission.discharged_at.is_(None),
        )
        .first()
    )


def _floor_allows_gender(floor: models.Floor | None, gender: str | None) -> bool:
    """NULL gender_restriction (mixed) always allows; otherwise the patient's
    gender must match exactly (case-insensitive)."""
    if floor is None or not floor.gender_restriction:
        return True
    return (gender or "").strip().lower() == floor.gender_restriction


def _occupied_beds_for_ward(db: Session, ward_id: str, exclude_admission_id: str | None = None) -> set[int]:
    q = db.query(models.Admission.bed_number).filter(
        models.Admission.ward_id == ward_id,
        models.Admission.discharged_at.is_(None),
    )
    if exclude_admission_id:
        q = q.filter(models.Admission.id != exclude_admission_id)
    return {row.bed_number for row in q.all()}


def _get_admission_for_staff(admission_id: str, current_user: models.User, db: Session) -> models.Admission:
    # Non-leaking scoped-404 -- see _get_ticket_for_staff.
    adm = db.query(models.Admission).filter(models.Admission.id == admission_id).first()
    if not adm or not current_user.facility or adm.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Admission not found")
    return adm


def _serialize_admission(db: Session, adm: models.Admission, *, patients=None, wards=None, floors=None) -> dict:
    # A list caller passes prebuilt {id: row} maps (see list_admissions) so
    # this is zero queries per row; a single-row caller passes nothing and
    # gets the per-row lookups. Code-review follow-up 2026-09-07.
    patient = (
        patients.get(adm.patient_id) if patients is not None
        else db.query(models.Patient).filter(models.Patient.id == adm.patient_id).first()
    )
    ward = (
        wards.get(adm.ward_id) if wards is not None
        else db.query(models.Ward).filter(models.Ward.id == adm.ward_id).first()
    )
    floor = None
    if ward is not None and ward.floor_id:
        floor = (
            floors.get(ward.floor_id) if floors is not None
            else db.query(models.Floor).filter(models.Floor.id == ward.floor_id).first()
        )
    return {
        "id": adm.id,
        "patient_id": adm.patient_id,
        "patient_name": patient.full_name if patient else "Unknown patient",
        "national_id": patient.national_id if patient else None,
        "ward_id": adm.ward_id,
        "ward_name": ward.ward_name if ward else "Unknown ward",
        "floor_id": floor.id if floor else None,
        "floor_label": floor.floor_label if floor else None,
        "bed_number": adm.bed_number,
        "admitted_at": adm.admitted_at,
        "admitted_by": adm.admitted_by,
        "discharged_at": adm.discharged_at,
        "notes": adm.notes,
    }


@router.post("/admissions", response_model=schemas.AdmissionOut)
def create_admission(
    payload: schemas.AdmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )
    facility = current_user.facility
    patient = _resolve_patient_for_admission(db, payload.patient_id, payload.national_id)

    if _active_admission_for_patient(db, patient.id):
        raise HTTPException(status_code=409, detail="That patient already has an active admission.")

    gender = (patient.gender or "").strip().lower() or None

    if payload.ward_id and payload.bed_number:
        ward = (
            db.query(models.Ward)
            .filter(models.Ward.id == payload.ward_id, models.Ward.facility_name == facility)
            .first()
        )
        if not ward:
            raise HTTPException(status_code=404, detail="Ward not found")
        if payload.bed_number < 1 or payload.bed_number > ward.total_beds:
            raise HTTPException(
                status_code=400,
                detail=f"Bed number must be between 1 and {ward.total_beds} for this ward.",
            )
        if payload.bed_number in _occupied_beds_for_ward(db, ward.id):
            raise HTTPException(status_code=409, detail="That bed is already occupied.")
        floor = (
            db.query(models.Floor).filter(models.Floor.id == ward.floor_id).first()
            if ward.floor_id
            else None
        )
        if not _floor_allows_gender(floor, gender):
            raise HTTPException(
                status_code=400,
                detail=f"This floor is {floor.gender_restriction}-only and does not match the patient's gender.",
            )
        chosen_ward, chosen_bed = ward, payload.bed_number
    else:
        floors_query = db.query(models.Floor).filter(models.Floor.facility_name == facility)
        if payload.floor_id:
            floor = floors_query.filter(models.Floor.id == payload.floor_id).first()
            if not floor:
                raise HTTPException(status_code=404, detail="Floor not found")
            if not _floor_allows_gender(floor, gender):
                raise HTTPException(
                    status_code=400,
                    detail=f"This floor is {floor.gender_restriction}-only and does not match the patient's gender.",
                )
            candidate_floors = [floor]
        else:
            candidate_floors = [
                f
                for f in floors_query.order_by(models.Floor.floor_label.asc()).all()
                if _floor_allows_gender(f, gender)
            ]

        chosen_ward = None
        chosen_bed = None
        for f in candidate_floors:
            wards = (
                db.query(models.Ward)
                .filter(models.Ward.floor_id == f.id)
                .order_by(models.Ward.ward_name.asc())
                .all()
            )
            for w in wards:
                taken = _occupied_beds_for_ward(db, w.id)
                free = [b for b in range(1, w.total_beds + 1) if b not in taken]
                if free:
                    chosen_ward = w
                    chosen_bed = random.choice(free)
                    break
            if chosen_ward is not None:
                break
        if chosen_ward is None:
            raise HTTPException(
                status_code=409,
                detail="No free bed is available on a floor matching this patient.",
            )

    admission = models.Admission(
        facility_name=facility,
        patient_id=patient.id,
        ward_id=chosen_ward.id,
        bed_number=chosen_bed,
        admitted_by=current_user.id,
        gender_at_admission=patient.gender,
        notes=payload.notes,
    )
    db.add(admission)
    # Mirror patients.py::add_encounter -- an admission is a genuine
    # inpatient encounter in the patient's cross-facility history.
    db.add(
        models.Encounter(
            patient_id=patient.id,
            facility_name=facility,
            encounter_type="inpatient",
            reason=f"Ward admission — {chosen_ward.ward_name} bed {chosen_bed}",
        )
    )
    db.commit()
    db.refresh(admission)

    log_access(
        db, patient.id, current_user.id, current_user.role, "reception_admit_patient",
        detail=f"ward={chosen_ward.ward_name} bed={chosen_bed}",
        actor_facility=facility,
    )
    return _serialize_admission(db, admission)


@router.patch("/admissions/{admission_id}", response_model=schemas.AdmissionOut)
def update_admission(
    admission_id: str,
    payload: schemas.AdmissionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Move a patient to another ward/bed or edit their admission notes.
    409 on a bed collision; re-checks the destination floor's gender rule on
    a ward move."""
    adm = _get_admission_for_staff(admission_id, current_user, db)
    if adm.discharged_at is not None:
        raise HTTPException(status_code=400, detail="That admission has already been discharged.")

    submitted_fields = payload.model_dump(exclude_unset=True)
    target_ward_id = submitted_fields.get("ward_id", adm.ward_id)
    target_bed = submitted_fields.get("bed_number", adm.bed_number)

    ward = (
        db.query(models.Ward)
        .filter(models.Ward.id == target_ward_id, models.Ward.facility_name == current_user.facility)
        .first()
    )
    if not ward:
        raise HTTPException(status_code=404, detail="Ward not found")
    if target_bed < 1 or target_bed > ward.total_beds:
        raise HTTPException(
            status_code=400,
            detail=f"Bed number must be between 1 and {ward.total_beds} for this ward.",
        )

    if "ward_id" in submitted_fields and ward.floor_id:
        floor = db.query(models.Floor).filter(models.Floor.id == ward.floor_id).first()
        patient = db.query(models.Patient).filter(models.Patient.id == adm.patient_id).first()
        gender = (patient.gender or "").strip().lower() if patient else None
        if not _floor_allows_gender(floor, gender):
            raise HTTPException(
                status_code=400,
                detail=f"This floor is {floor.gender_restriction}-only and does not match the patient's gender.",
            )

    if (target_ward_id, target_bed) != (adm.ward_id, adm.bed_number):
        if target_bed in _occupied_beds_for_ward(db, target_ward_id, exclude_admission_id=adm.id):
            raise HTTPException(status_code=409, detail="That bed is already occupied.")

    for field, value in submitted_fields.items():
        setattr(adm, field, value)
    if submitted_fields:
        db.commit()
        db.refresh(adm)

    log_access(
        db, adm.patient_id, current_user.id, current_user.role, "reception_update_admission",
        fields=sorted(submitted_fields.keys()), actor_facility=current_user.facility,
    )
    return _serialize_admission(db, adm)


@router.post("/admissions/{admission_id}/discharge", response_model=schemas.AdmissionOut)
def discharge_admission(
    admission_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    adm = _get_admission_for_staff(admission_id, current_user, db)
    if adm.discharged_at is not None:
        raise HTTPException(status_code=400, detail="That admission has already been discharged.")

    adm.discharged_at = datetime.utcnow()
    adm.discharged_by = current_user.id
    db.commit()
    db.refresh(adm)

    log_access(
        db, adm.patient_id, current_user.id, current_user.role, "reception_discharge_patient",
        detail=f"ward_id={adm.ward_id} bed={adm.bed_number}", actor_facility=current_user.facility,
    )
    return _serialize_admission(db, adm)


@router.get("/admissions", response_model=list[schemas.AdmissionOut])
def list_admissions(
    active: bool = True,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    if not current_user.facility:
        return []
    query = db.query(models.Admission).filter(models.Admission.facility_name == current_user.facility)
    if active:
        query = query.filter(models.Admission.discharged_at.is_(None))
    admissions = query.order_by(models.Admission.admitted_at.desc()).all()
    if not admissions:
        return []
    patients = {
        p.id: p for p in db.query(models.Patient)
        .filter(models.Patient.id.in_({a.patient_id for a in admissions})).all()
    }
    wards = {
        w.id: w for w in db.query(models.Ward)
        .filter(models.Ward.id.in_({a.ward_id for a in admissions})).all()
    }
    floor_ids = {w.floor_id for w in wards.values() if w.floor_id}
    floors = {
        f.id: f for f in db.query(models.Floor).filter(models.Floor.id.in_(floor_ids)).all()
    } if floor_ids else {}
    return [
        _serialize_admission(db, a, patients=patients, wards=wards, floors=floors)
        for a in admissions
    ]


@router.get("/ward-map", response_model=schemas.WardMapOut)
def get_ward_map(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Nested floors -> wards -> beds for the caller's facility. Floors
    ordered by floor_label, wards by ward_name, beds 1..total_beds."""
    if not current_user.facility:
        return schemas.WardMapOut(floors=[])
    facility = current_user.facility

    floors = (
        db.query(models.Floor)
        .filter(models.Floor.facility_name == facility)
        .order_by(models.Floor.floor_label.asc())
        .all()
    )
    active = (
        db.query(models.Admission)
        .filter(
            models.Admission.facility_name == facility,
            models.Admission.discharged_at.is_(None),
        )
        .all()
    )
    by_ward_bed = {(a.ward_id, a.bed_number): a for a in active}
    patient_ids = {a.patient_id for a in active}
    patients = {}
    if patient_ids:
        for p in db.query(models.Patient).filter(models.Patient.id.in_(patient_ids)).all():
            patients[p.id] = p

    out_floors = []
    for f in floors:
        wards = (
            db.query(models.Ward)
            .filter(models.Ward.floor_id == f.id)
            .order_by(models.Ward.ward_name.asc())
            .all()
        )
        out_wards = []
        for w in wards:
            beds = []
            for bed_number in range(1, w.total_beds + 1):
                adm = by_ward_bed.get((w.id, bed_number))
                adm_out = None
                if adm is not None:
                    p = patients.get(adm.patient_id)
                    adm_out = schemas.WardMapBedAdmission(
                        id=adm.id,
                        patient_id=adm.patient_id,
                        patient_name=p.full_name if p else "Unknown patient",
                        national_id=p.national_id if p else None,
                        admitted_at=adm.admitted_at,
                        notes=adm.notes,
                    )
                beds.append(
                    schemas.WardMapBed(bed_number=bed_number, occupied=adm is not None, admission=adm_out)
                )
            out_wards.append(schemas.WardMapWard(id=w.id, ward_name=w.ward_name, beds=beds))
        out_floors.append(
            schemas.WardMapFloor(
                id=f.id,
                floor_label=f.floor_label,
                gender_restriction=f.gender_restriction,
                wards=out_wards,
            )
        )
    return schemas.WardMapOut(floors=out_floors)
