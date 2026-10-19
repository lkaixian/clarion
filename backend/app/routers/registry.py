"""Patient registry extras from the HIS dataset: coded demographics edit, sponsors, dependants.

  PATCH  /patients/{id}/demographics         staff (admin, records_officer, clinician, receptionist)
  GET    /sponsors                           any staff account
  POST   /sponsors, PATCH /sponsors/{id}     admin
  GET/POST/DELETE /patients/{id}/dependants  staff, patient must be known to the caller's facility

A patient the caller's facility has never dealt with is a 404, not a 403, so the response does
not confirm the record exists (same rule as the rest of the clinical routers)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..audit import log_access
from ..clinical_access import _patient_known_to_facility
from ..database import get_db
from ..demographics import DEMOGRAPHIC_FIELDS, validate_demographics

router = APIRouter(tags=["registry"])

_REGISTRY_ROLES = ("admin", "records_officer", "clinician", "receptionist")


def _fac(user: models.User) -> str:
    if not user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned")
    return user.facility


def _own_patient(db: Session, user: models.User, patient_id: str) -> models.Patient:
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if patient is None or not user.facility or not _patient_known_to_facility(db, patient_id, user.facility):
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


# ---- demographics ---------------------------------------------------------

class DemographicsUpdate(BaseModel):
    title_code: Optional[str] = Field(default=None, max_length=32)
    religion_code: Optional[str] = Field(default=None, max_length=32)
    race_code: Optional[str] = Field(default=None, max_length=32)
    nation_code: Optional[str] = Field(default=None, max_length=32)
    marital_code: Optional[str] = Field(default=None, max_length=32)
    occupation_code: Optional[str] = Field(default=None, max_length=32)
    address_line: Optional[str] = Field(default=None, max_length=255)
    postcode: Optional[str] = Field(default=None, max_length=16)
    city: Optional[str] = Field(default=None, max_length=128)
    state_code: Optional[str] = Field(default=None, max_length=32)
    sponsor_code: Optional[str] = Field(default=None, max_length=32)
    sponsor_member_no: Optional[str] = Field(default=None, max_length=64)

    class Config:
        extra = "forbid"  # identity fields (name, NRIC, DOB) are not editable here


@router.patch("/patients/{patient_id}/demographics")
def update_demographics(
    patient_id: str, payload: DemographicsUpdate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_REGISTRY_ROLES)),
):
    patient = _own_patient(db, user, patient_id)
    submitted = payload.model_dump(exclude_unset=True)
    clean = validate_demographics(db, submitted, user.facility)
    for field, value in clean.items():
        setattr(patient, field, value)
    db.commit()
    # Field names only: the values are personal data and the audit log is the wider audience.
    log_access(db, patient_id, user.id, user.role, "update_demographics",
               fields=sorted(clean), actor_facility=user.facility)
    return {f: getattr(patient, f) for f in DEMOGRAPHIC_FIELDS}


# ---- sponsors --------------------------------------------------------------

class SponsorIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    company_number: Optional[str] = Field(default=None, max_length=64)
    street_1: Optional[str] = Field(default=None, max_length=255)
    street_2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    postcode: Optional[str] = Field(default=None, max_length=16)
    state_code: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=64)
    entitlement_code: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = None
    active: bool = True


class SponsorPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company_number: Optional[str] = Field(default=None, max_length=64)
    street_1: Optional[str] = Field(default=None, max_length=255)
    street_2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    postcode: Optional[str] = Field(default=None, max_length=16)
    state_code: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=64)
    entitlement_code: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = None
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class SponsorOut(SponsorIn):
    id: str

    class Config:
        from_attributes = True


def _check_entitlement(db: Session, code: Optional[str]) -> None:
    if code and db.query(models.ReferenceCode.id).filter_by(kind="entitlements", code=code).first() is None:
        raise HTTPException(status_code=422, detail=f"Unknown entitlement code: {code}")


@router.get("/sponsors", response_model=List[SponsorOut])
def list_sponsors(
    active_only: bool = True, db: Session = Depends(get_db), user: models.User = Depends(auth.get_staff_user),
):
    q = db.query(models.Sponsor).filter(models.Sponsor.facility_name == _fac(user))
    if active_only:
        q = q.filter(models.Sponsor.active.is_(True))
    return q.order_by(models.Sponsor.name.asc()).all()


@router.post("/sponsors", response_model=SponsorOut, status_code=201)
def create_sponsor(
    payload: SponsorIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin")),
):
    _check_entitlement(db, payload.entitlement_code)
    row = models.Sponsor(**{**payload.model_dump(), "code": payload.code.strip(), "facility_name": _fac(user)})
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A sponsor with that code already exists")
    db.refresh(row)
    return row


@router.patch("/sponsors/{sponsor_id}", response_model=SponsorOut)
def update_sponsor(
    sponsor_id: str, payload: SponsorPatch, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    row = db.query(models.Sponsor).filter_by(id=sponsor_id, facility_name=_fac(user)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sponsor not found")
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
               if v is not None or k not in ("name", "active")}
    _check_entitlement(db, changes.get("entitlement_code"))
    for k, v in changes.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


# ---- dependants ------------------------------------------------------------

class DependantIn(BaseModel):
    dependant_id: str
    relation_code: Optional[str] = Field(default=None, max_length=32)


@router.get("/patients/{patient_id}/dependants")
def list_dependants(
    patient_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_REGISTRY_ROLES)),
):
    _own_patient(db, user, patient_id)
    rows = (
        db.query(models.PatientDependant, models.Patient)
        .join(models.Patient, models.Patient.id == models.PatientDependant.dependant_id)
        .filter(models.PatientDependant.patient_id == patient_id)
        .order_by(models.PatientDependant.created_at.asc()).all()
    )
    names = {
        r.code: r.name for r in db.query(models.ReferenceCode).filter_by(kind="relationships").all()
    }
    return [
        {"id": link.id, "dependant_id": dep.id, "dependant_name": dep.full_name,
         "relation_code": link.relation_code, "relation": names.get(link.relation_code)}
        for link, dep in rows
        if _patient_known_to_facility(db, dep.id, user.facility)  # a link made elsewhere stays invisible here
    ]


@router.post("/patients/{patient_id}/dependants", status_code=201)
def add_dependant(
    patient_id: str, payload: DependantIn, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_REGISTRY_ROLES)),
):
    _own_patient(db, user, patient_id)
    dep = _own_patient(db, user, payload.dependant_id)  # linking exposes the name, so same rule
    if dep.id == patient_id:
        raise HTTPException(status_code=400, detail="A patient cannot be their own dependant")
    if payload.relation_code and db.query(models.ReferenceCode.id).filter_by(
        kind="relationships", code=payload.relation_code
    ).first() is None:
        raise HTTPException(status_code=422, detail=f"Unknown relationship code: {payload.relation_code}")
    link = models.PatientDependant(
        patient_id=patient_id, dependant_id=dep.id, relation_code=payload.relation_code, created_by=user.id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already linked")
    log_access(db, patient_id, user.id, user.role, "add_dependant", detail=link.id, actor_facility=user.facility)
    return {"id": link.id, "dependant_id": dep.id, "dependant_name": dep.full_name,
            "relation_code": link.relation_code}


@router.delete("/patients/{patient_id}/dependants/{link_id}", status_code=204)
def remove_dependant(
    patient_id: str, link_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_REGISTRY_ROLES)),
):
    _own_patient(db, user, patient_id)
    link = db.query(models.PatientDependant).filter_by(id=link_id, patient_id=patient_id).first()
    if link is None or not _patient_known_to_facility(db, link.dependant_id, user.facility):
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()
    log_access(db, patient_id, user.id, user.role, "remove_dependant", detail=link_id, actor_facility=user.facility)
