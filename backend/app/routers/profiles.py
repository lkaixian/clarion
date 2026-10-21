"""Family profiles under one patient login: add a child or an elderly parent, switch between
them, and (for an adult who later gets their own login) remove the link.

  GET    /profiles                    the profiles this login can act as, and which one is active
  POST   /profiles                    add a child / parent; created unverified (`provisional`)
  POST   /profiles/switch             {patient_id} -> a token for that profile (own id = back to self)
  GET    /profiles/guardians          logins' owners who can act for me
  DELETE /profiles/guardians/{id}     an adult removes a carer's access (not available for minors)

Switching never changes who is logged in: the token still belongs to the login, with an extra
`act_as` claim that is re-checked against the link on every request (see auth.get_current_user),
and every audit row is written under the login's own user id.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..audit import log_access
from ..database import get_db
from ..guardianship import (
    AGE_OF_MAJORITY, MAX_PROFILES_PER_ACCOUNT, SELF_SERVICE_RELATION_CODES, age_of, link_for, may_act_for,
    needs_approval,
)
from ..rate_limit import limiter
from .auth_router import _user_out_for

router = APIRouter(prefix="/profiles", tags=["profiles"])

_SENIOR_AGE = 60
_age = age_of


class ProfileCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    date_of_birth: str  # YYYY-MM-DD
    relation_code: str
    gender: Optional[str] = Field(default=None, max_length=64)
    # No IC number here on purpose: typing one would let a carer claim a real person's identity before
    # they register. The clinic desk links a record that already has one.

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Enter the person's full name.")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _real_birthdate(cls, v: str) -> str:
        try:
            born = date.fromisoformat(v)
        except ValueError:
            raise ValueError("Enter the date of birth as YYYY-MM-DD.")
        if born > date.today() or _age(v) > 125:
            raise ValueError("Enter a real date of birth.")
        return v

    @field_validator("relation_code")
    @classmethod
    def _allowed_relation(cls, v: str) -> str:
        if v not in SELF_SERVICE_RELATION_CODES:
            raise ValueError("Choose Child, Mother, Father, Grandmother, Grandfather, Guardian or Others.")
        return v


class ProfileSwitch(BaseModel):
    patient_id: str


def _home(current_user) -> models.User:
    """The login itself (never the profile it is currently acting for), which must be a patient
    login with its own patient record."""
    user = auth.real_user(current_user)
    if user.role != "patient" or not user.patient_id:
        raise HTTPException(status_code=403, detail="Only patient logins can manage family profiles")
    return user


def _profile(patient: models.Patient, *, link=None, is_self=False, has_own_login=False) -> dict:
    return {
        "patient_id": patient.id, "full_name": patient.full_name, "date_of_birth": patient.date_of_birth,
        "age": _age(patient.date_of_birth), "is_self": is_self,
        "relation_code": link.relation_code if link else None, "link_id": link.id if link else None,
        "provisional": bool(patient.provisional), "has_own_login": has_own_login,
    }


@router.get("")
def list_profiles(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    user = _home(current_user)
    me = db.get(models.Patient, user.patient_id)
    rows = (
        db.query(models.PatientDependant, models.Patient)
        .join(models.Patient, models.Patient.id == models.PatientDependant.dependant_id)
        .filter(models.PatientDependant.patient_id == user.patient_id,
                models.PatientDependant.relation_code.in_(SELF_SERVICE_RELATION_CODES))
        .order_by(models.PatientDependant.created_at.asc()).all()
    )
    has_login = {pid for (pid,) in db.query(models.User.patient_id).filter(
        models.User.patient_id.in_([p.id for _, p in rows] or [""])).all()}
    return {
        "active_patient_id": current_user.patient_id,
        "profiles": [_profile(me, is_self=True, has_own_login=True)]
        + [{**_profile(p, link=link, has_own_login=p.id in has_login), "pending_approval": needs_approval(db, link)}
           for link, p in rows],
    }


@router.post("", status_code=201)
@limiter.limit("10/hour")
def add_profile(request: Request, payload: ProfileCreate, db: Session = Depends(get_db),
                current_user=Depends(auth.get_current_user)):
    user = _home(current_user)
    count = db.query(models.PatientDependant).filter_by(patient_id=user.patient_id).count()
    if count >= MAX_PROFILES_PER_ACCOUNT:
        raise HTTPException(status_code=400, detail=f"At most {MAX_PROFILES_PER_ACCOUNT} family profiles per login.")
    age = _age(payload.date_of_birth)
    patient = models.Patient(
        full_name=payload.full_name, date_of_birth=payload.date_of_birth, gender=payload.gender,
        provisional=True, senior_citizen_mode=bool(age is not None and age >= _SENIOR_AGE),
    )
    db.add(patient)
    try:
        db.flush()
        link = models.PatientDependant(
            patient_id=user.patient_id, dependant_id=patient.id, relation_code=payload.relation_code, created_by=user.id)
        db.add(link)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not save this profile. Please try again.")
    db.refresh(patient)
    log_access(db, patient.id, user.id, user.role, "add_family_profile", detail=f"link={link.id}")
    return _profile(patient, link=link)


@router.post("/switch", response_model=schemas.Token)
@limiter.limit("30/minute")
def switch_profile(request: Request, payload: ProfileSwitch, db: Session = Depends(get_db),
                   current_user=Depends(auth.get_current_user)):
    user = _home(current_user)
    if not may_act_for(db, user, payload.patient_id):
        link = link_for(db, user, payload.patient_id)
        waiting = link is not None and link.relation_code in SELF_SERVICE_RELATION_CODES and needs_approval(db, link)
        raise HTTPException(status_code=403,
                            detail="Waiting for their approval." if waiting else "You cannot act for this profile.")
    claims = {"sub": user.id, "role": user.role}
    if payload.patient_id != user.patient_id:
        claims["act_as"] = payload.patient_id
        log_access(db, payload.patient_id, user.id, user.role, "switch_profile")
    token = auth.create_access_token(claims, password_changed_at=user.password_changed_at)
    return schemas.Token(access_token=token, user=_user_out_for(db, user, payload.patient_id))


@router.get("/guardians")
def list_guardians(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    user = _home(current_user)
    rows = (
        db.query(models.PatientDependant, models.Patient)
        .join(models.Patient, models.Patient.id == models.PatientDependant.patient_id)
        .filter(models.PatientDependant.dependant_id == user.patient_id).all()
    )
    return [{"link_id": link.id, "full_name": guardian.full_name, "relation_code": link.relation_code,
             "approved": link.approved_at is not None, "pending": needs_approval(db, link)}
            for link, guardian in rows]


@router.delete("/guardians/{link_id}", status_code=204)
def remove_guardian(link_id: str, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    user = _home(current_user)
    link = db.query(models.PatientDependant).filter_by(id=link_id, dependant_id=user.patient_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    me = db.get(models.Patient, user.patient_id)
    age = _age(me.date_of_birth if me else None)
    if age is None or age < AGE_OF_MAJORITY:
        raise HTTPException(status_code=403, detail="A parent or guardian of someone under 18 cannot be removed here.")
    db.delete(link)
    db.commit()
    log_access(db, user.patient_id, user.id, user.role, "remove_guardian", detail=link_id)


@router.post("/guardians/{link_id}/approve", status_code=204)
def approve_guardian(link_id: str, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """An adult with a login of their own lets a carer who already added them act for them."""
    user = _home(current_user)
    link = db.query(models.PatientDependant).filter_by(id=link_id, dependant_id=user.patient_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    link.approved_at = datetime.now(timezone.utc)
    db.commit()
    log_access(db, user.patient_id, user.id, user.role, "approve_guardian", detail=link_id)
