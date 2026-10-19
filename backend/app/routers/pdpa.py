"""PDPA -- consent ledger + data-subject-request workflow (roadmap P2.10,
the tender).

Research (healthcare/Malaysia Health Regulation.md): Malaysia's PDPA has NO
right to erasure. Clinical records run on the s.40 "medical purposes" basis
(no consent needed) and are kept per Act 586 / MMC. So:

  - CONSENT here is only for OPTIONAL purposes (research, marketing, SMS
    reminders, cross-facility sharing) + the `pdpa_notice` acknowledgement.
    An append-only ledger; the newest row for a (patient, purpose) wins.
  - DATA-SUBJECT REQUESTS are access / correction / portability /
    withdraw_consent / objection -- never "delete". `access` / `portability`
    generate a machine-readable export of the patient's own record (a staff
    handler must have the request assigned + in_progress first). A
    `withdraw_consent` request is a tracked TICKET for the DPO to action;
    the actual withdrawal is `POST /pdpa/consent` (the patient can do it
    themselves, or the RO on their behalf).

Access model: a patient only ever touches their own record. Staff
(records_officer / admin) are facility-scoped -- own facility, a patient the
facility has a relationship to (the P2.2 scope), or an audited
`break_glass_reason`. A platform admin (`facility is None`) sees everything.
Registered plainly in main.py (not page-gated).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models, mpi_client, schemas
from ..audit import log_access
from ..clinical_access import _facility_known_patient_ids_select, _patient_known_to_facility
from ..database import get_db

router = APIRouter(prefix="/pdpa", tags=["pdpa"])

# DSR access-request statutory period (s.30): 21 days, +14 extendable.
_DSR_DUE_DAYS = 21
_DSR_STAFF_ROLES = ("admin", "records_officer")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _staff_may_reach_patient(db: Session, current_user: models.User, patient_id: str) -> bool:
    """A records_officer / admin may act on a patient their facility has a
    relationship to; a platform admin (no facility) on anyone. Reuses the
    P2.2 single-patient scope check."""
    if not current_user.facility:            # platform admin
        return True
    return _patient_known_to_facility(db, patient_id, current_user.facility)


_AGE_OF_MAJORITY = 18


def _is_guardian_of_minor(db: Session, current_user: models.User, patient_id: str) -> bool:
    """The signed-in patient is the recorded guardian of `patient_id`
    (a PatientDependant link) and that dependant is under 18."""
    from .emergency import _age_from_dob  # lazy: emergency imports this module's neighbours
    if not current_user.patient_id:
        return False
    linked = db.query(models.PatientDependant.id).filter_by(
        patient_id=current_user.patient_id, dependant_id=patient_id).first()
    child = db.query(models.Patient.date_of_birth).filter_by(id=patient_id).first()
    age = _age_from_dob(child[0]) if child else None
    return bool(linked) and age is not None and age < _AGE_OF_MAJORITY


def _resolve_target_patient(db: Session, current_user: models.User, patient_id: Optional[str],
                            *, scope_staff: bool = True, allow_guardian: bool = False) -> str:
    """A patient always acts on their own record (or, with `allow_guardian`, on
    a minor dependant they are the recorded guardian of); staff must name a
    patient, and (when `scope_staff`) that patient must be in the staff
    member's facility scope."""
    if current_user.role == "patient":
        if patient_id and patient_id != current_user.patient_id:
            if not (allow_guardian and _is_guardian_of_minor(db, current_user, patient_id)):
                raise HTTPException(status_code=403, detail="Patients can only act on their own record")
            return patient_id
        if not current_user.patient_id:
            raise HTTPException(status_code=400, detail="This account is not linked to a patient")
        return current_user.patient_id
    if not patient_id:
        raise HTTPException(status_code=400, detail="patient_id is required for staff")
    if not db.query(models.Patient.id).filter(models.Patient.id == patient_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")
    if scope_staff and not _staff_may_reach_patient(db, current_user, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")   # non-leaking
    return patient_id


def _effective_consent(db: Session, patient_id: str) -> dict:
    """Newest ledger row per purpose -> {purpose: bool}. Purposes never
    recorded are absent (caller treats as 'not given')."""
    out: dict = {}
    rows = (
        db.query(models.ConsentRecord)
        .filter(models.ConsentRecord.patient_id == patient_id)
        .order_by(models.ConsentRecord.created_at.desc(), models.ConsentRecord.id.desc())
        .all()
    )
    for r in rows:
        out.setdefault(r.purpose, r.granted)
    return out


def _dsr_or_404(db: Session, dsr_id: str) -> models.DataSubjectRequest:
    row = db.query(models.DataSubjectRequest).filter(models.DataSubjectRequest.id == dsr_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Data-subject request not found")
    return row


def _dsr_in_scope_or_404(db: Session, current_user: models.User, dsr_id: str) -> models.DataSubjectRequest:
    row = _dsr_or_404(db, dsr_id)
    if not _can_see_dsr(db, current_user, row):
        raise HTTPException(status_code=404, detail="Data-subject request not found")
    return row


def _can_see_dsr(db: Session, current_user: models.User, dsr: models.DataSubjectRequest) -> bool:
    if current_user.role == "patient":
        return dsr.patient_id == current_user.patient_id
    if current_user.role not in _DSR_STAFF_ROLES:
        return False
    if not current_user.facility:                     # platform admin
        return True
    if dsr.facility_name == current_user.facility:
        return True
    return _staff_may_reach_patient(db, current_user, dsr.patient_id)


# --------------------------------------------------------------------------
# consent
# --------------------------------------------------------------------------

@router.get("/consent")
def get_consent(
    patient_id: Optional[str] = Query(None, description="staff only; a patient omits it"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in ("patient",) + _DSR_STAFF_ROLES + ("clinician",):
        raise HTTPException(status_code=403, detail="Not permitted")
    pid = _resolve_target_patient(db, current_user, patient_id, allow_guardian=True)
    if current_user.role != "patient":
        log_access(db, pid, current_user.id, current_user.role, "view_consent_ledger",
                   actor_facility=current_user.facility)
    return {
        "patient_id": pid,
        "purposes": list(models.CONSENT_PURPOSES),
        "effective": _effective_consent(db, pid),
    }


@router.post("/consent", response_model=schemas.ConsentRecordOut)
def record_consent(
    payload: schemas.ConsentRecordIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Front-line clinicians may record the one consent asked at the desk (sharing
    # with other facilities); every other purpose stays with admin / records officer.
    staff_ok = _DSR_STAFF_ROLES + (("clinician",) if payload.purpose == "cross_facility_sharing" else ())
    if current_user.role not in ("patient",) + staff_ok:
        raise HTTPException(status_code=403, detail="Not permitted")
    if payload.purpose not in models.CONSENT_PURPOSES:
        raise HTTPException(status_code=400,
                            detail=f"purpose must be one of {list(models.CONSENT_PURPOSES)}")
    pid = _resolve_target_patient(db, current_user, payload.patient_id, allow_guardian=True)
    if current_user.role == "patient":
        source = "portal" if pid == current_user.patient_id else "guardian"
    else:
        source = "staff"
    row = models.ConsentRecord(
        patient_id=pid, purpose=payload.purpose, granted=payload.granted,
        source=source,
        note=payload.note, recorded_by=current_user.id, recorded_by_role=current_user.role,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, pid, current_user.id, current_user.role,
               "consent_granted" if payload.granted else "consent_withdrawn",
               detail=f"purpose={payload.purpose}" + (" on_behalf_of_minor" if source == "guardian" else ""),
               actor_facility=current_user.facility)
    if payload.purpose == "cross_facility_sharing":
        # Late grant: publish the visits signed here before it. Withdrawal: take our pointers off central.
        (mpi_client.enqueue_backfill if payload.granted else mpi_client.enqueue_withdraw)(db, pid)
    return row


# --------------------------------------------------------------------------
# data-subject requests
# --------------------------------------------------------------------------

@router.post("/requests", response_model=schemas.DataSubjectRequestOut)
def file_request(
    payload: schemas.DataSubjectRequestIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in ("patient",) + _DSR_STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not permitted")
    if payload.kind not in models.DSR_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(models.DSR_KINDS)}")
    pid = _resolve_target_patient(db, current_user, payload.patient_id)
    now = datetime.now(timezone.utc)
    row = models.DataSubjectRequest(
        patient_id=pid, kind=payload.kind, status="open", detail=payload.detail,
        facility_name=current_user.facility,
        requested_by=current_user.id, requested_at=now,
        due_at=now + timedelta(days=_DSR_DUE_DAYS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, pid, current_user.id, current_user.role, "data_subject_request_filed",
               detail=f"kind={payload.kind} id={row.id}", actor_facility=current_user.facility)
    return row


@router.get("/requests", response_model=List[schemas.DataSubjectRequestOut])
def list_requests(
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    break_glass_reason: Optional[str] = Query(
        None, description="staff: see every facility's requests, not just your own -- audited"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.DataSubjectRequest)
    if current_user.role == "patient":
        if not current_user.patient_id:
            return []
        q = q.filter(models.DataSubjectRequest.patient_id == current_user.patient_id)
    elif current_user.role in _DSR_STAFF_ROLES:
        broke = bool(break_glass_reason and break_glass_reason.strip())
        if current_user.facility and not broke:
            # facility-scoped: requests filed here, or for a patient this
            # facility has a relationship to (the P2.2 scope). An orphan
            # portal-filed request (patient with no facility relationship
            # anywhere) is NOT broadcast -- it surfaces only to a platform
            # admin (or via break_glass). `assign` stamps a facility.
            known = _facility_known_patient_ids_select(current_user.facility)
            q = q.filter(
                (models.DataSubjectRequest.facility_name == current_user.facility)
                | models.DataSubjectRequest.patient_id.in_(select(known.c.patient_id))
            )
            log_access(db, None, current_user.id, current_user.role, "list_data_subject_requests",
                       actor_facility=current_user.facility)
        else:
            log_access(db, None, current_user.id, current_user.role,
                       "list_data_subject_requests_break_glass",
                       detail=(break_glass_reason or "").strip()[:200] or None,
                       actor_facility=current_user.facility)
    else:
        raise HTTPException(status_code=403, detail="Not permitted")

    if status:
        q = q.filter(models.DataSubjectRequest.status == status)
    if kind:
        q = q.filter(models.DataSubjectRequest.kind == kind)
    return (
        q.order_by(models.DataSubjectRequest.requested_at.desc(),
                   models.DataSubjectRequest.id.desc())
        .offset(skip).limit(limit).all()
    )


@router.get("/requests/{dsr_id}", response_model=schemas.DataSubjectRequestOut)
def get_request(
    dsr_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = _dsr_or_404(db, dsr_id)
    if not _can_see_dsr(db, current_user, row):
        raise HTTPException(status_code=404, detail="Data-subject request not found")
    if current_user.role != "patient":
        log_access(db, row.patient_id, current_user.id, current_user.role,
                   "view_data_subject_request", detail=f"id={dsr_id} kind={row.kind}",
                   actor_facility=current_user.facility)
    return row


@router.post("/requests/{dsr_id}/assign", response_model=schemas.DataSubjectRequestOut)
def assign_request(
    dsr_id: str,
    assigned_to: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_DSR_STAFF_ROLES)),
):
    row = _dsr_in_scope_or_404(db, current_user, dsr_id)
    row.status = "in_progress"
    row.assigned_to = assigned_to or current_user.id
    if row.facility_name is None:
        row.facility_name = current_user.facility   # claim a portal-filed request
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "data_subject_request_in_progress", detail=f"id={dsr_id}",
               actor_facility=current_user.facility)
    return row


@router.post("/requests/{dsr_id}/complete", response_model=schemas.DataSubjectRequestOut)
def complete_request(
    dsr_id: str,
    note: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_DSR_STAFF_ROLES)),
):
    row = _dsr_in_scope_or_404(db, current_user, dsr_id)
    row.status = "completed"
    row.resolution_note = (note or "").strip() or None
    row.resolved_by = current_user.id
    row.resolved_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "data_subject_request_completed", detail=f"id={dsr_id} kind={row.kind}",
               actor_facility=current_user.facility)
    return row


@router.post("/requests/{dsr_id}/reject", response_model=schemas.DataSubjectRequestOut)
def reject_request(
    dsr_id: str,
    note: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_DSR_STAFF_ROLES)),
):
    row = _dsr_in_scope_or_404(db, current_user, dsr_id)
    row.status = "rejected"
    row.resolution_note = note.strip()
    row.resolved_by = current_user.id
    row.resolved_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "data_subject_request_rejected", detail=f"id={dsr_id}",
               actor_facility=current_user.facility)
    return row


@router.post("/requests/{dsr_id}/extend", response_model=schemas.DataSubjectRequestOut)
def extend_request(
    dsr_id: str,
    note: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_DSR_STAFF_ROLES)),
):
    """The PDPA s.30 +14-day extension. Allowed once (a due date already
    past requested_at + 21 + 14 days is not extended further)."""
    row = _dsr_in_scope_or_404(db, current_user, dsr_id)
    hard_cap = (row.requested_at or datetime.now(timezone.utc)) + timedelta(days=_DSR_DUE_DAYS + 14)
    base = row.due_at or (row.requested_at + timedelta(days=_DSR_DUE_DAYS))
    if base >= hard_cap:
        raise HTTPException(status_code=409, detail="Already extended by the maximum 14 days")
    row.due_at = base + timedelta(days=14)
    row.resolution_note = ((row.resolution_note or "") + f" [extended: {note.strip()}]").strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "data_subject_request_extended", detail=f"id={dsr_id}",
               actor_facility=current_user.facility)
    return row


@router.get("/requests/{dsr_id}/export")
def export_request_data(
    dsr_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """The machine-readable data for an `access` / `portability` request:
    the patient's own record (PDPA s.30 / s.43A). Structured JSON, the same
    serializer the clinical UI uses. `bypass_sharing_filter=True` -- the
    data SUBJECT is entitled to their whole record regardless of any
    cross-facility opt-out; a staff handler may only generate it once the
    request is assigned to them and in_progress."""
    row = _dsr_in_scope_or_404(db, current_user, dsr_id)
    if row.kind not in ("access", "portability"):
        raise HTTPException(status_code=400, detail="Export is only for access / portability requests")
    if current_user.role != "patient":
        if row.status != "in_progress" or row.assigned_to != current_user.id:
            raise HTTPException(
                status_code=409,
                detail="Assign this request to yourself and set it in_progress before exporting")

    from .patients import _serialize_patient
    patient = db.query(models.Patient).filter(models.Patient.id == row.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    record = _serialize_patient(patient, db, current_user, bypass_sharing_filter=True)
    consent = [
        {"purpose": c.purpose, "granted": c.granted, "at": str(c.created_at), "source": c.source}
        for c in db.query(models.ConsentRecord)
        .filter(models.ConsentRecord.patient_id == row.patient_id)
        .order_by(models.ConsentRecord.created_at.asc()).all()
    ]
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "data_subject_export_generated", detail=f"id={dsr_id} kind={row.kind}",
               actor_facility=current_user.facility)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request": {"id": row.id, "kind": row.kind, "requested_at": str(row.requested_at)},
        "format": "clarion-patient-record/v1",
        "record": record,
        "consent_history": consent,
    }
