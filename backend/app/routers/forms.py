"""Configurable clinical forms (his_open_1 `forms`, `form_positions`, `form_values`).

  POST /forms                                  admin: define a form (new version of an existing code)
  GET  /forms                                  admin, clinician, records_officer: active forms
  POST /forms/{id}/deactivate                  admin
  POST /patients/{pid}/forms/{id}/responses    admin, clinician, records_officer: fill one in
  GET  /patients/{pid}/form-responses          same roles, this facility's responses only

A form is a list of typed fields; a response is checked against it (required, type, select
options, no unknown keys). Forms are never edited in place: a changed form is a new version,
so an old response is still read with the field list it was filled in against. Responses are
append-only."""
import math
import re
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..audit import log_access
from ..clinical_access import _patient_known_to_facility
from ..database import get_db

router = APIRouter(tags=["forms"])

FIELD_TYPES = ("text", "number", "select", "boolean", "date")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_READERS = ("admin", "clinician", "records_officer")


class FieldDef(BaseModel):
    key: str
    label: str = Field(min_length=1, max_length=200)
    type: str
    required: bool = False
    options: Optional[List[str]] = None


class FormIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    fields: List[FieldDef] = Field(min_length=1, max_length=100)


class ResponseIn(BaseModel):
    values: Dict[str, Any]
    encounter_id: Optional[str] = None


def _facility(user: models.User) -> str:
    if not user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned")
    return user.facility


def _check_definition(fields: List[FieldDef]) -> None:
    seen = set()
    for f in fields:
        if not _KEY.match(f.key):
            raise HTTPException(status_code=422, detail=f"Field key '{f.key}': lowercase letters, digits, underscore")
        if f.key in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate field key '{f.key}'")
        seen.add(f.key)
        if f.type not in FIELD_TYPES:
            raise HTTPException(status_code=422, detail=f"Field '{f.key}': type must be one of {', '.join(FIELD_TYPES)}")
        if f.type == "select" and not (f.options and all(o.strip() for o in f.options)):
            raise HTTPException(status_code=422, detail=f"Field '{f.key}': a select needs options")


def check_values(fields: list, values: dict) -> dict:
    """Validates a response against a form's field list; returns the cleaned values."""
    defs = {f["key"]: f for f in fields}
    unknown = sorted(set(values) - set(defs))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not on this form: {', '.join(unknown)}")
    out: Dict[str, Any] = {}
    for key, f in defs.items():
        v = values.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            if f.get("required"):
                raise HTTPException(status_code=422, detail=f"{f['label']} is required")
            continue
        t = f["type"]
        bad = HTTPException(status_code=422, detail=f"{f['label']}: expected {t}")
        if t == "text":
            if not isinstance(v, str) or len(v) > 4000:
                raise bad
            out[key] = v.strip()
        elif t == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise bad
            out[key] = v
        elif t == "boolean":
            if not isinstance(v, bool):
                raise bad
            out[key] = v
        elif t == "date":
            try:
                date.fromisoformat(str(v))
            except ValueError:
                raise bad
            out[key] = str(v)
        elif t == "select":
            if v not in (f.get("options") or []):
                raise HTTPException(status_code=422, detail=f"{f['label']}: pick one of the listed options")
            out[key] = v
    return out


def _form_out(f: models.ClinicalForm) -> dict:
    return {"id": f.id, "code": f.code, "version": f.version, "name": f.name, "fields": f.fields,
            "active": f.active, "created_at": f.created_at}


@router.post("/forms", status_code=201)
def create_form(payload: FormIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin"))):
    facility = _facility(user)
    _check_definition(payload.fields)
    code = payload.code.strip()
    latest = db.query(func.max(models.ClinicalForm.version)).filter_by(facility_name=facility, code=code).scalar() or 0
    form = models.ClinicalForm(
        facility_name=facility, code=code, version=latest + 1, name=payload.name,
        fields=[f.model_dump() for f in payload.fields], created_by=user.id,
    )
    db.add(form)
    try:
        db.commit()
    except IntegrityError:  # two admins saving the same code at once
        db.rollback()
        raise HTTPException(status_code=409, detail="That form was just changed; reload and try again")
    db.refresh(form)
    # Older versions stop being offered, but stay readable for the responses filled in on them.
    db.query(models.ClinicalForm).filter(
        models.ClinicalForm.facility_name == facility, models.ClinicalForm.code == code,
        models.ClinicalForm.version < form.version,
    ).update({"active": False})
    db.commit()
    return _form_out(form)


@router.get("/forms")
def list_forms(
    include_inactive: bool = False, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_READERS)),
):
    q = db.query(models.ClinicalForm).filter(models.ClinicalForm.facility_name == _facility(user))
    if not include_inactive:
        q = q.filter(models.ClinicalForm.active.is_(True))
    return [_form_out(f) for f in q.order_by(models.ClinicalForm.name.asc(), models.ClinicalForm.version.desc()).all()]


@router.post("/forms/{form_id}/deactivate")
def deactivate_form(form_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin"))):
    f = db.query(models.ClinicalForm).filter_by(id=form_id, facility_name=_facility(user)).first()
    if f is None:
        raise HTTPException(status_code=404, detail="Form not found")
    f.active = False
    db.commit()
    return _form_out(f)


@router.post("/patients/{patient_id}/forms/{form_id}/responses", status_code=201)
def submit_response(
    patient_id: str, form_id: str, payload: ResponseIn, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_READERS)),
):
    facility = _facility(user)
    form = db.query(models.ClinicalForm).filter_by(id=form_id, facility_name=facility).first()
    if form is None or not form.active:
        raise HTTPException(status_code=404, detail="Form not found")
    if not _patient_known_to_facility(db, patient_id, facility):
        raise HTTPException(status_code=404, detail="Patient not found")
    if payload.encounter_id and db.query(models.Encounter.id).filter_by(
        id=payload.encounter_id, patient_id=patient_id, facility_name=facility
    ).first() is None:
        raise HTTPException(status_code=422, detail="That encounter does not belong to this patient")
    cleaned = check_values(form.fields, payload.values)
    row = models.FormResponse(
        form_id=form.id, patient_id=patient_id, encounter_id=payload.encounter_id, facility_name=facility,
        answers=cleaned, submitted_by=user.id, submitted_by_name=user.full_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, patient_id, user.id, user.role, "submit_form", detail=f"{form.code} v{form.version}",
               actor_facility=facility)
    return {"id": row.id, "form_id": form.id, "values": row.answers, "created_at": row.created_at}


@router.get("/patients/{patient_id}/form-responses")
def list_responses(
    patient_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_READERS)),
):
    facility = _facility(user)
    rows = (
        db.query(models.FormResponse, models.ClinicalForm)
        .join(models.ClinicalForm, models.ClinicalForm.id == models.FormResponse.form_id)
        .filter(models.FormResponse.patient_id == patient_id, models.FormResponse.facility_name == facility)
        .order_by(models.FormResponse.created_at.desc()).limit(200).all()
    )
    log_access(db, patient_id, user.id, user.role, "list_form_responses", actor_facility=facility)
    return [
        {"id": r.id, "form_code": f.code, "form_version": f.version, "form_name": f.name, "fields": f.fields,
         "values": r.answers, "submitted_by_name": r.submitted_by_name, "created_at": r.created_at,
         "encounter_id": r.encounter_id}
        for r, f in rows
    ]
