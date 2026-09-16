from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..appointments import MALAYSIA_TZ, compute_available_slots, compute_reminder_offsets
from ..clinical_access import _patient_known_to_facility

# Roles allowed to read/write another person's appointments. Matches the
# create/update/reschedule gate below -- an appointment's reason /
# precaution_notes / fasting instructions are clinical detail, so a
# receptionist or pharmacist is intentionally excluded even though they may
# hold the `patients` page for check-in purposes.
_APPOINTMENT_STAFF_ROLES = ("admin", "clinician", "records_officer")

router = APIRouter(prefix="/patients", tags=["appointments"])


def _latest_reschedule_request(db: Session, appointment_id: str) -> models.AppointmentRescheduleRequest | None:
    return (
        db.query(models.AppointmentRescheduleRequest)
        .filter(models.AppointmentRescheduleRequest.appointment_id == appointment_id)
        .order_by(models.AppointmentRescheduleRequest.created_at.desc())
        .first()
    )


def _serialize_appointment(a: models.Appointment, db: Session) -> dict:
    # reminders is computed on every read (never persisted) -- see
    # appointments.compute_reminder_offsets's docstring for why. This is the
    # one place both the create and list/patch responses funnel through, so
    # every AppointmentOut-shaped response includes it consistently.
    latest_request = _latest_reschedule_request(db, a.id)
    return {
        "id": a.id,
        "patient_id": a.patient_id,
        "facility_name": a.facility_name,
        "venue": a.venue,
        "scheduled_at": a.scheduled_at,
        "reason": a.reason,
        "fasting_required": a.fasting_required,
        "fasting_hours": a.fasting_hours,
        "precaution_notes": a.precaution_notes,
        "extra_reminder_hours_before": a.extra_reminder_hours_before,
        "status": a.status,
        "created_by": a.created_by,
        "created_at": a.created_at,
        "department": a.department,
        "clinician_id": a.clinician_id,
        "self_booked": a.self_booked,
        "previous_scheduled_at": a.previous_scheduled_at,
        "reschedule_reason_code": a.reschedule_reason_code,
        "reschedule_reason_other": a.reschedule_reason_other,
        "reminders": compute_reminder_offsets(a),
        "latest_reschedule_request": (
            schemas.RescheduleRequestOut.model_validate(latest_request) if latest_request else None
        ),
    }


def _get_appointment_or_404(db: Session, patient_id: str, appointment_id: str) -> models.Appointment:
    # Scoped to patient_id too, not just appointment_id -- mirrors
    # patients.py::_get_document_or_404's reasoning: there's no FK
    # enforcement between Appointment.patient_id and Patient.id (SQLite
    # foreign_keys pragma is off), so a caller can't be trusted to have the
    # right patient_id/appointment_id pairing just because both individually
    # resolve to *some* row.
    appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id, models.Appointment.patient_id == patient_id)
        .first()
    )
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@router.post("/{patient_id}/appointments", response_model=schemas.AppointmentOut)
def create_appointment(
    patient_id: str,
    payload: schemas.AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_APPOINTMENT_STAFF_ROLES)),
):
    """Doctor/staff-published appointment (follow-up visit, procedure, etc.).
    Reminder timing is never stored -- see compute_reminder_offsets."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    appointment = models.Appointment(
        patient_id=patient_id, created_by=current_user.id, **payload.model_dump()
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "create_appointment",
        detail=payload.facility_name, actor_facility=current_user.facility,
    )
    return _serialize_appointment(appointment, db)


@router.get("/{patient_id}/appointments", response_model=List[schemas.AppointmentOut])
def list_appointments(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patient (own record only) + clinical staff (admin / clinician /
    records_officer -- the same set that can create/modify an appointment).
    A receptionist or pharmacist is intentionally excluded even with the
    `patients` page: an appointment's reason / precaution_notes / fasting
    instructions are clinical detail, not front-desk data. Security Audit
    Code-review follow-up 2026-09-07 -- this endpoint previously accepted any authenticated non-patient
    token, unscoped and with no cross-facility distinction in the audit log.

    Cancelled/completed appointments are included, not hidden -- the client
    filters/styles by status (same "don't hide history server-side" stance
    as get_audit_log)."""
    if current_user.role == "patient":
        if current_user.patient_id != patient_id:
            raise HTTPException(status_code=403, detail="Cannot view another patient's appointments")
    elif current_user.role not in _APPOINTMENT_STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Requires one of roles: {_APPOINTMENT_STAFF_ROLES}",
        )

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    appointments = (
        db.query(models.Appointment)
        .filter(models.Appointment.patient_id == patient_id)
        .order_by(models.Appointment.scheduled_at.asc())
        .all()
    )

    # Mirror get_patient_full_record's break-glass audit: a staff caller
    # whose facility has no established relationship to this patient gets a
    # DISTINCT audit action, so a cross-facility appointment read stays
    # reviewable after the fact rather than indistinguishable from a routine
    # local lookup.
    is_cross_facility = (
        current_user.role != "patient"
        and (
            not current_user.facility
            or not _patient_known_to_facility(db, patient_id, current_user.facility)
        )
    )
    log_access(
        db, patient_id, current_user.id, current_user.role,
        "view_appointments_cross_facility" if is_cross_facility else "view_appointments",
        actor_facility=current_user.facility,
    )
    return [_serialize_appointment(a, db) for a in appointments]


@router.patch("/{patient_id}/appointments/{appointment_id}", response_model=schemas.AppointmentOut)
def update_appointment(
    patient_id: str,
    appointment_id: str,
    payload: schemas.AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_APPOINTMENT_STAFF_ROLES)),
):
    """Staff-only partial update, including the status transition (e.g. to
    "cancelled" -- soft-cancel only, matches EmergencyToken.revoked's
    pattern; this never hard-deletes a row)."""
    appointment = _get_appointment_or_404(db, patient_id, appointment_id)

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(appointment, field, value)

    # Re-validate fasting_hours/fasting_required against the MERGED row, not
    # just the raw PATCH payload -- schemas.AppointmentUpdate deliberately
    # skips this check itself (see its docstring) because a PATCH containing
    # only fasting_hours, against a row that ALREADY has
    # fasting_required=True, must stay valid. But a PATCH that sets
    # fasting_hours on a row where fasting_required is (and stays) False
    # must still be rejected here, after the merge.
    if appointment.fasting_hours is not None and not appointment.fasting_required:
        raise HTTPException(
            status_code=400,
            detail="fasting_hours can only be set when fasting_required is true.",
        )

    if submitted_fields:
        db.add(appointment)
        db.commit()
        db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_appointment",
        fields=sorted(submitted_fields.keys()), detail=appointment_id,
        actor_facility=current_user.facility,
    )
    return _serialize_appointment(appointment, db)


@router.post("/{patient_id}/appointments/{appointment_id}/reschedule", response_model=schemas.AppointmentOut)
def reschedule_appointment(
    patient_id: str,
    appointment_id: str,
    payload: schemas.RescheduleAppointmentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_APPOINTMENT_STAFF_ROLES)),
):
    """Staff-only action that actually moves an appointment's scheduled_at
    -- the one place Appointment.previous_scheduled_at/reschedule_reason_*
    get written (see models.Appointment's docstring). Used both when a
    clinician reschedules unprompted, and after accepting a patient's
    reschedule request (POST .../reschedule-requests/{id}/accept) once a
    new time has actually been agreed with the patient by phone -- accepting
    a request never moves scheduled_at by itself, see
    AppointmentRescheduleRequest's docstring for why.

    Only valid against a "scheduled" appointment -- rescheduling a
    cancelled/completed one would silently resurrect it, which is never the
    intent (cancel a stale appointment and create a fresh one instead)."""
    appointment = _get_appointment_or_404(db, patient_id, appointment_id)
    if appointment.status != "scheduled":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reschedule an appointment with status '{appointment.status}'.",
        )

    appointment.previous_scheduled_at = appointment.scheduled_at
    appointment.scheduled_at = payload.new_scheduled_at
    appointment.reschedule_reason_code = payload.reason_code
    appointment.reschedule_reason_other = payload.reason_other

    # Any reschedule request still pending against this appointment is now
    # moot -- the appointment has actually moved, so leaving it "pending"
    # would misleadingly suggest staff still haven't acted on it. Marked
    # accepted (not silently deleted) so the patient still sees what
    # happened to their request.
    pending_request = (
        db.query(models.AppointmentRescheduleRequest)
        .filter(
            models.AppointmentRescheduleRequest.appointment_id == appointment_id,
            models.AppointmentRescheduleRequest.status == "pending",
        )
        .first()
    )
    if pending_request:
        pending_request.status = "accepted"
        pending_request.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        pending_request.resolved_by = current_user.id

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "reschedule_appointment",
        detail=f"appointment={appointment_id} reason={payload.reason_code}",
        actor_facility=current_user.facility,
    )
    return _serialize_appointment(appointment, db)


@router.post(
    "/{patient_id}/appointments/{appointment_id}/reschedule-requests",
    response_model=schemas.RescheduleRequestOut,
)
def request_reschedule(
    patient_id: str,
    appointment_id: str,
    payload: schemas.RescheduleRequestCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patient-only, own-record-only: asks staff to reschedule this
    appointment. Does NOT move scheduled_at -- see
    AppointmentRescheduleRequest's docstring. At most one pending request
    per appointment (checked here, not a DB constraint -- see that same
    docstring); the patient must wait for staff to accept/reject the
    existing one first."""
    if current_user.role != "patient" or current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Only the patient themself can request a reschedule.")

    appointment = _get_appointment_or_404(db, patient_id, appointment_id)
    if appointment.status != "scheduled":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot request a reschedule for an appointment with status '{appointment.status}'.",
        )

    existing_pending = (
        db.query(models.AppointmentRescheduleRequest)
        .filter(
            models.AppointmentRescheduleRequest.appointment_id == appointment_id,
            models.AppointmentRescheduleRequest.status == "pending",
        )
        .first()
    )
    if existing_pending:
        raise HTTPException(
            status_code=400,
            detail="A reschedule request for this appointment is already pending.",
        )

    request_row = models.AppointmentRescheduleRequest(
        appointment_id=appointment_id,
        patient_id=patient_id,
        requested_by=current_user.id,
        reason_code=payload.reason_code,
        reason_other=payload.reason_other,
    )
    db.add(request_row)
    db.commit()
    db.refresh(request_row)

    log_access(
        db, patient_id, current_user.id, current_user.role, "request_appointment_reschedule",
        detail=f"appointment={appointment_id} reason={payload.reason_code}",
    )
    return schemas.RescheduleRequestOut.model_validate(request_row)


def _get_reschedule_request_or_404(
    db: Session, patient_id: str, appointment_id: str, request_id: str
) -> models.AppointmentRescheduleRequest:
    request_row = (
        db.query(models.AppointmentRescheduleRequest)
        .filter(
            models.AppointmentRescheduleRequest.id == request_id,
            models.AppointmentRescheduleRequest.appointment_id == appointment_id,
            models.AppointmentRescheduleRequest.patient_id == patient_id,
        )
        .first()
    )
    if not request_row:
        raise HTTPException(status_code=404, detail="Reschedule request not found")
    if request_row.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{request_row.status}'")
    return request_row


@router.post(
    "/{patient_id}/appointments/{appointment_id}/reschedule-requests/{request_id}/accept",
    response_model=schemas.RescheduleRequestOut,
)
def accept_reschedule_request(
    patient_id: str,
    appointment_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_APPOINTMENT_STAFF_ROLES)),
):
    """Staff-only. Accepting only records "we'll call the patient to agree
    a new time" -- it deliberately does NOT reschedule the appointment
    itself; use POST .../reschedule for that once a time has actually been
    agreed (see AppointmentRescheduleRequest's docstring for why this is
    split into two steps)."""
    request_row = _get_reschedule_request_or_404(db, patient_id, appointment_id, request_id)
    request_row.status = "accepted"
    request_row.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    request_row.resolved_by = current_user.id
    db.commit()
    db.refresh(request_row)

    log_access(
        db, patient_id, current_user.id, current_user.role, "accept_reschedule_request",
        detail=f"appointment={appointment_id} request={request_id}",
        actor_facility=current_user.facility,
    )
    return schemas.RescheduleRequestOut.model_validate(request_row)


@router.post(
    "/{patient_id}/appointments/{appointment_id}/reschedule-requests/{request_id}/reject",
    response_model=schemas.RescheduleRequestOut,
)
def reject_reschedule_request(
    patient_id: str,
    appointment_id: str,
    request_id: str,
    payload: schemas.RescheduleRequestRejectBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_APPOINTMENT_STAFF_ROLES)),
):
    """Staff-only. The appointment is left exactly as-is -- rejecting is
    purely informational for the patient (optionally with clinician_note
    explaining why), not a state change on the appointment itself."""
    request_row = _get_reschedule_request_or_404(db, patient_id, appointment_id, request_id)
    request_row.status = "rejected"
    request_row.clinician_note = payload.clinician_note
    request_row.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    request_row.resolved_by = current_user.id
    db.commit()
    db.refresh(request_row)

    log_access(
        db, patient_id, current_user.id, current_user.role, "reject_reschedule_request",
        detail=f"appointment={appointment_id} request={request_id}",
        actor_facility=current_user.facility,
    )
    return schemas.RescheduleRequestOut.model_validate(request_row)


# ---------------------------------------------------------------------------
# P3.10: patient self-service booking by department/doctor.
# ---------------------------------------------------------------------------

def _to_aware_utc(dt: datetime) -> datetime:
    """Normalise to AWARE UTC -- a genuinely offset-bearing input (e.g. a
    client that legitimately sends '+08:00' instead of 'Z') is CONVERTED,
    not just re-labelled, so the wall-clock instant it names is preserved;
    a naive input (models.Appointment.scheduled_at may come back naive
    depending on backend -- see TZDateTime's docstring in models.py) is
    tagged UTC, this codebase's established assumption for a naive stored
    value. Deliberately NOT the naive-UTC convention compute_reminder_
    offsets uses -- see compute_available_slots's docstring for why this
    subsystem needs aware datetimes specifically (the Dart interop bug a
    naive round-trip produced)."""
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clinicians_for(
    db: Session, facility_name: str, department: Optional[str], clinician_id: Optional[str]
) -> list[models.User]:
    """Candidate clinicians for a self-booking query: an exact clinician_id
    if given, else every clinician at this facility either pinned to
    `department` or unscoped (User.section is NULL means "sees the whole
    facility" everywhere else this column is used -- see User.section's
    docstring -- so an unscoped clinician is a valid "general" pick too)."""
    q = db.query(models.User).filter(models.User.role == "clinician", models.User.facility == facility_name)
    if clinician_id:
        q = q.filter(models.User.id == clinician_id)
    elif department:
        q = q.filter(or_(models.User.section == department, models.User.section.is_(None)))
    return q.order_by(models.User.full_name.asc()).all()


def _booked_times_for_clinician(db: Session, clinician_id: str) -> set[datetime]:
    rows = (
        db.query(models.Appointment.scheduled_at)
        .filter(models.Appointment.clinician_id == clinician_id, models.Appointment.status == "scheduled")
        .all()
    )
    return {_to_aware_utc(dt) for (dt,) in rows}


@router.post("/{patient_id}/appointments/self-book", response_model=schemas.AppointmentOut)
def self_book_appointment(
    patient_id: str,
    payload: schemas.SelfBookAppointmentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patient self-service booking -- own record only. Reuses the
    Appointment table (self_booked=True distinguishes this from a
    staff-published appointment, see models.Appointment's docstring) through
    a deliberately narrower schema than AppointmentCreate: no reason/
    precaution_notes/fasting fields, those stay staff-only clinical calls
    (see _APPOINTMENT_STAFF_ROLES above).

    The requested scheduled_at is NEVER trusted as a bare value -- it must
    exactly match a slot compute_available_slots would currently offer for
    the resolved clinician, recomputed here against live data. That check
    alone is a read-then-write race, though (two concurrent requests can
    both pass it before either commits -- the exact class of bug
    models.QueueTicket's docstring warns about for the same reason FastAPI
    runs sync `def` routes in a threadpool): the real guarantee is
    models.Appointment's `uq_appointments_active_clinician_slot` DB
    constraint, caught below as an IntegrityError and turned into a clean
    409 -- security-review follow-up, P3.9/P3.10 wave."""
    if current_user.role != "patient" or current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Only the patient themself can self-book an appointment.")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    clinicians = _clinicians_for(db, payload.facility_name, payload.department, payload.clinician_id)
    if not clinicians:
        raise HTTPException(status_code=400, detail="No clinician available for that facility/department")

    requested = _to_aware_utc(payload.scheduled_at)
    local_date = requested.astimezone(MALAYSIA_TZ).date()

    matched_clinician = None
    for clinician in clinicians:
        booked = _booked_times_for_clinician(db, clinician.id)
        if requested in compute_available_slots(local_date, booked):
            matched_clinician = clinician
            break
    if matched_clinician is None:
        raise HTTPException(status_code=409, detail="That slot is no longer available — please pick another.")

    appointment = models.Appointment(
        patient_id=patient_id,
        facility_name=payload.facility_name,
        department=payload.department,
        clinician_id=matched_clinician.id,
        scheduled_at=requested,
        status="scheduled",
        self_booked=True,
        created_by=current_user.id,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request for the SAME clinician+slot won the race and
        # committed first -- the in-Python check above passed for both, but
        # the DB constraint (uq_appointments_active_clinician_slot) only
        # lets one through. No retry-with-a-different-slot here (unlike
        # _create_ticket_with_retry's next-number case): the patient asked
        # for this exact time, so a clean 409 is the right answer, same as
        # the "someone else took it" outcome the in-Python check already
        # produces above -- the Flutter client already refreshes its slot
        # list on this response either way.
        db.rollback()
        raise HTTPException(status_code=409, detail="That slot is no longer available — please pick another.")
    db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "self_book_appointment",
        detail=f"facility={payload.facility_name} clinician={matched_clinician.id}",
    )
    return _serialize_appointment(appointment, db)
