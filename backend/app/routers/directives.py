"""Critical personal directives (organ donation, blood transfusion, implanted device, advance directive).

APPEND-ONLY history (models.CriticalDirective): a change is a new row, the newest row per (patient, kind)
is the current one. Two sources, always labelled and never merged:
  * patient-declared  -- PUT /profile/directives/{kind}: the logged-in patient's OWN record, or the profile
    they are acting for (auth.get_current_user already re-checks guardianship.may_act_for on every request,
    including the pending-approval rule; nothing is re-invented here).
  * recorded by staff -- POST /patients/{id}/directives: needs the signed form number (`evidence_ref`).
    A staff entry never edits the patient's own row; it is a newer row, and the emergency view says who stated it.
This is NOT legal proof of anything -- the UI says so next to every value.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..audit import log_access
from ..clinical_access import _hidden_author_facilities, _patient_known_to_facility
from ..database import get_db

router = APIRouter(tags=["directives"])

Kind = Literal["organ_donation", "blood_transfusion", "implanted_device", "advance_directive"]
CHOICE_KINDS = ("organ_donation", "blood_transfusion")
CHOICES = ("yes", "no", "undecided")
# Staff entries override what a patient declared, so only roles that handle signed clinical forms may write.
STAFF_WRITE_ROLES = ("admin", "records_officer", "clinician")
STAFF_READ_ROLES = STAFF_WRITE_ROLES + ("receptionist", "pharmacist")

# control chars plus zero-width / bidi-override characters that could spoof the text responders read
_CTRL = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    return " ".join(_CTRL.sub(" ", v).split())


class DirectiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    note: Optional[str] = None
    # id of the entry you were looking at ("" if there was none). Saving over a newer one is a 409.
    based_on: str = Field(max_length=36)

    @field_validator("value", "note", mode="before")
    @classmethod
    def _text(cls, v):
        if v is not None and not isinstance(v, str):
            raise ValueError("must be text")
        return _clean(v)

    @field_validator("note")
    @classmethod
    def _note_len(cls, v):
        if v is not None and len(v) > 500:
            raise ValueError("note is at most 500 characters")
        return v or None


class StaffDirectiveIn(DirectiveIn):
    kind: Kind
    evidence_ref: str

    @field_validator("evidence_ref", mode="before")
    @classmethod
    def _ev(cls, v):
        if not isinstance(v, str):
            raise ValueError("must be text")
        v = _clean(v)
        if not v or len(v) > 120:
            raise ValueError("evidence_ref (the signed form number) is required, at most 120 characters")
        return v


def _check_value(kind: str, value: str) -> None:
    if kind in CHOICE_KINDS:
        if value not in CHOICES:
            raise HTTPException(status_code=422, detail=f"value for {kind} must be one of yes, no, undecided")
    elif len(value) > 300:
        raise HTTPException(status_code=422, detail="value is at most 300 characters")


def source_label(source: str, evidence_ref: Optional[str], public: bool = False) -> str:
    if source == "patient":
        return "patient-declared"
    if source == "guardian":
        return "declared by a guardian"
    return "recorded by staff" if public else f"recorded by staff (form {evidence_ref})"


def _out(r: models.CriticalDirective) -> dict:
    return {
        "id": r.id, "kind": r.kind, "value": r.value, "note": r.note, "source": r.source,
        "evidence_ref": r.evidence_ref, "label": source_label(r.source, r.evidence_ref),
        "recorded_by_name": r.recorded_by_name, "recorded_by_role": r.recorded_by_role,
        "recorded_by_facility": r.recorded_by_facility, "recorded_at": str(r.recorded_at),
    }


def _all_rows(db: Session, patient_id: str) -> list:
    # id is a tiebreak only; _append keeps recorded_at strictly increasing per (patient, kind)
    return (db.query(models.CriticalDirective).filter(models.CriticalDirective.patient_id == patient_id)
            .order_by(models.CriticalDirective.recorded_at.desc(), models.CriticalDirective.id).all())


def _current(rows: list) -> dict:
    cur: dict = {}
    for r in rows:  # newest first
        cur.setdefault(r.kind, r)
    return cur


def current_for_emergency(db: Session, patient_id: str, public: bool = False) -> list:
    """The ONLY fields the emergency views get: kind, value, source and its label. No note, no staff
    name. A cleared (empty) value is omitted. The unauthenticated public tier gets the yes/no/undecided
    kinds only (never staff-typed free text) and no form number."""
    return [
        {"kind": r.kind, "value": r.value, "source": r.source,
         "label": source_label(r.source, r.evidence_ref, public)}
        for r in _current(_all_rows(db, patient_id)).values()
        if r.value and (not public or r.kind in CHOICE_KINDS)
    ]


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="This item was changed by someone else since you opened it. "
                                                  "The latest value is now shown; check it and save again.")


def _append(db: Session, patient_id: str, *, kind: str, value: str, note, source: str, evidence_ref, user,
            based_on: str):
    real = auth.real_user(user)
    _check_value(kind, value)
    latest = (db.query(models.CriticalDirective.id).filter_by(patient_id=patient_id, kind=kind)
              .order_by(models.CriticalDirective.recorded_at.desc(), models.CriticalDirective.id).first())
    if based_on != (latest[0] if latest else ""):
        raise _conflict()
    now = datetime.now(timezone.utc)
    prev = (db.query(models.CriticalDirective.recorded_at)
            .filter_by(patient_id=patient_id, kind=kind).order_by(models.CriticalDirective.recorded_at.desc()).first())
    if prev and prev[0] is not None:
        p = prev[0] if prev[0].tzinfo else prev[0].replace(tzinfo=timezone.utc)
        if now <= p:
            now = p + timedelta(microseconds=1)
    row = models.CriticalDirective(
        patient_id=patient_id, kind=kind, value=value, note=note, source=source, evidence_ref=evidence_ref,
        recorded_by=real.id, recorded_by_name=real.full_name, recorded_by_role=user.role,
        recorded_by_facility=getattr(user, "facility", None), recorded_at=now, supersedes_id=based_on,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # someone saved over the same version at the same instant
        db.rollback()
        raise _conflict()
    db.refresh(row)
    log_access(db, patient_id, real.id, user.role, "write_critical_directive",
               detail=f"kind={kind} source={source}", actor_facility=getattr(user, "facility", None))
    return row


def _my_patient_id(user) -> str:
    pid = getattr(user, "patient_id", None)
    if user.role != "patient" or not pid:
        raise HTTPException(status_code=403, detail="Only a patient login has a record of its own")
    return pid


@router.get("/profile/directives")
def my_directives(db: Session = Depends(get_db), user=Depends(auth.get_current_user)):
    rows = _all_rows(db, _my_patient_id(user))
    return {"current": [_out(r) for r in _current(rows).values()], "history": [_out(r) for r in rows]}


@router.put("/profile/directives/{kind}", status_code=201)
def declare_my_directive(kind: Kind, payload: DirectiveIn, db: Session = Depends(get_db),
                         user=Depends(auth.get_current_user)):
    pid = _my_patient_id(user)
    source = "guardian" if isinstance(user, auth.ActingUser) else "patient"  # a guardian is not the patient
    return _out(_append(db, pid, kind=kind, value=payload.value, note=payload.note, source=source,
                        evidence_ref=None, user=user, based_on=payload.based_on))


def _known_patient_or_404(db: Session, patient_id: str, user) -> None:
    if (db.get(models.Patient, patient_id) is None or not user.facility
            or not _patient_known_to_facility(db, patient_id, user.facility)):
        raise HTTPException(status_code=404, detail="Patient not found")


@router.post("/patients/{patient_id}/directives", status_code=201)
def record_staff_directive(patient_id: str, payload: StaffDirectiveIn, db: Session = Depends(get_db),
                           user: models.User = Depends(auth.require_roles(*STAFF_WRITE_ROLES))):
    _known_patient_or_404(db, patient_id, user)
    return _out(_append(db, patient_id, kind=payload.kind, value=payload.value, note=payload.note,
                        source="staff", evidence_ref=payload.evidence_ref, user=user,
                        based_on=payload.based_on))


@router.get("/patients/{patient_id}/directives")
def patient_directives(patient_id: str, db: Session = Depends(get_db),
                       user: models.User = Depends(auth.require_roles(*STAFF_READ_ROLES))):
    _known_patient_or_404(db, patient_id, user)
    log_access(db, patient_id, user.id, user.role, "read_critical_directives", actor_facility=user.facility)
    rows = _all_rows(db, patient_id)
    hidden = _hidden_author_facilities(db, user.facility)  # same opt-out the medication list honours
    # A current value stated by a facility that hides its records is dropped, never replaced by an older one.
    current = [r for r in _current(rows).values() if r.recorded_by_facility not in hidden]
    return {"current": [_out(r) for r in current],
            "history": [_out(r) for r in rows if r.recorded_by_facility not in hidden]}
