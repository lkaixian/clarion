"""Reception desk check-in (POST /reception/checkin) + the reception-desk
FacilitySection dropdown feed (GET /reception/sections)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import models, schemas, auth
from ...database import get_db
from ...audit import log_access
from ..auth_router import _resolve_patient_by_nric
from ._common import STAFF_ROLES, _malaysia_today, _room_load_today, _user_section

router = APIRouter()

# Bounded retry count for the queue-number insert race (see
# _next_queue_number's docstring) -- comfortably more attempts than any
# realistic concurrent-checkin burst at a single facility's front desk
# would ever produce.
MAX_QUEUE_NUMBER_ATTEMPTS = 5


def _resolve_patient(payload: schemas.ReceptionCheckinRequest, db: Session):
    """Returns (patient, source) or raises HTTPException(404). `source` is one
    of "ic" | "manual" | "qr" | "nfc" -- which identifier the receptionist
    used, recorded on QueueTicket.source.

    For card_reference/nfc_uid: deliberately does NOT hard-gate on
    `grant.revoked` or `grant.expires_at` the way /emergency/scan does.
    Reasoning: /emergency/scan's revoked/expired check exists to protect
    exposing MEDICAL DATA to an unauthenticated responder from a stale or
    deliberately-revoked credential -- that's a real disclosure risk. This
    endpoint requires a staff JWT already, discloses nothing more than "here
    is a queue ticket," and the identifier is only ever being used to look
    up WHICH existing patient record to attach a queue ticket to. A patient
    whose 30-day QR grant lapsed yesterday, or whose card was revoked after
    a reissue elsewhere, should still be checkable-in by a receptionist
    holding their printed card/screenshot -- rejecting that would just push
    the receptionist to fall back to manual patient_id lookup anyway, with
    no actual security benefit gained. The card_reference/nfc_uid values
    themselves are still effectively unguessable (same token_urlsafe(8)+
    space as /emergency/scan), so this isn't opening a brute-force surface.
    A completely unknown/never-issued reference still 404s below.
    """
    if payload.national_id:
        # Dash-tolerant IC/NRIC lookup, indexed (Security Audit M2) --
        # reuses the same resolver auth_router.login/OTP-reset uses.
        patient = _resolve_patient_by_nric(db, payload.national_id)
        if not patient:
            raise HTTPException(status_code=404, detail="No patient found for that IC number")
        return patient, "ic"

    if payload.patient_id:
        patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        return patient, "manual"

    if payload.card_reference:
        grant = (
            db.query(models.EmergencyToken)
            .filter(models.EmergencyToken.card_reference == payload.card_reference)
            .first()
        )
        if not grant:
            raise HTTPException(status_code=404, detail="No patient found for that card reference")
        patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        return patient, "qr"

    # payload.nfc_uid -- schemas.ReceptionCheckinRequest guarantees exactly
    # one of the four identifiers is set, so this is the only remaining case.
    # M7: EmergencyToken.nfc_uid stores the HMAC, so hash the presented UID.
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == auth.hash_nfc_uid(payload.nfc_uid))
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="No patient found for that NFC card")
    patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient, "nfc"


def _count_today_tickets(db: Session, facility_name: str, queue_date: str) -> int:
    return (
        db.query(func.count(models.QueueTicket.id))
        .filter(
            models.QueueTicket.facility_name == facility_name,
            models.QueueTicket.queue_date == queue_date,
        )
        .scalar()
    ) or 0


def _assign_room(db: Session, facility_name: str, department: str | None) -> models.ConsultationRoom | None:
    """Round-robin: the active ConsultationRoom at this facility with the
    fewest non-cancelled tickets today (ties broken by room_name for
    determinism). If `department` is given and at least one active room
    carries that exact department tag, only those rooms are candidates;
    otherwise every active room is. Returns None when the facility has no
    active rooms configured -- check-in still succeeds, just without a room."""
    _utc_start, queue_date = _malaysia_today()
    rooms = (
        db.query(models.ConsultationRoom)
        .filter(
            models.ConsultationRoom.facility_name == facility_name,
            models.ConsultationRoom.active.is_(True),
        )
        .all()
    )
    if not rooms:
        return None
    if department:
        dept_rooms = [r for r in rooms if r.department == department]
        if dept_rooms:
            rooms = dept_rooms
    rooms.sort(key=lambda r: (_room_load_today(db, r.id, queue_date), r.room_name))
    return rooms[0]


def _create_ticket_with_retry(
    db: Session,
    *,
    patient_id: str,
    facility_name: str,
    queue_date: str,
    department: str | None,
    reason: str | None,
    source: str,
    checked_in_by: str,
) -> models.QueueTicket:
    """Assigns `queue_number` as `1 + count of today's tickets for this
    facility` and inserts the new ticket, with a bounded retry loop against
    the `(facility_name, queue_date, queue_number)` unique constraint on
    QueueTicket (see that model's docstring for exactly why this is
    necessary, not just defensive: FastAPI runs sync `def` routes in a
    threadpool even under a single `uvicorn` process, and this app's SQLite
    engine sets `check_same_thread: False`, so two concurrent
    POST /reception/checkin calls for the same facility really can both
    read the same COUNT(*) before either commits).

    On a genuine collision (IntegrityError from the unique constraint), the
    failed insert is rolled back and the count is recomputed and retried --
    this always converges within a handful of attempts for realistic
    concurrency at a single front desk, and NEVER silently hands out a
    duplicate queue_number the way the old plain count-then-insert did."""
    # Round-robin a consultation room once, up front -- it doesn't depend on
    # queue_number so it needn't be recomputed inside the collision-retry loop.
    room = _assign_room(db, facility_name, department)
    room_id = room.id if room else None
    room_name = room.room_name if room else None

    last_error: IntegrityError | None = None
    for _attempt in range(MAX_QUEUE_NUMBER_ATTEMPTS):
        queue_number = _count_today_tickets(db, facility_name, queue_date) + 1
        ticket = models.QueueTicket(
            patient_id=patient_id,
            facility_name=facility_name,
            queue_date=queue_date,
            queue_number=queue_number,
            department=department,
            room_id=room_id,
            room_name=room_name,
            reason=reason,
            source=source,
            status="waiting",
            checked_in_by=checked_in_by,
        )
        db.add(ticket)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
            continue
        db.refresh(ticket)
        return ticket

    # Exhausted every retry -- an extraordinarily unlikely amount of
    # sustained concurrent contention for one facility. Surface a clean
    # 409 rather than either looping forever or letting the last
    # IntegrityError leak out as a raw 500.
    raise HTTPException(
        status_code=409,
        detail="Could not assign a queue number due to high concurrent check-in load — please retry.",
    ) from last_error


@router.post("/checkin", response_model=schemas.ReceptionCheckinResponse)
def checkin(
    payload: schemas.ReceptionCheckinRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )

    patient, source = _resolve_patient(payload, db)
    _utc_start, queue_date = _malaysia_today()

    # Per-counter scoping: a receptionist pinned to a section can ONLY check
    # patients into that section -- the client's payload.department is
    # ignored outright (not merged, not validated against it), so the front
    # desk can't accidentally or deliberately route a walk-in to another
    # counter's queue. An unscoped receptionist keeps free choice of
    # department via the payload, exactly as before.
    section = _user_section(current_user)
    effective_department = section if section is not None else payload.department

    ticket = _create_ticket_with_retry(
        db,
        patient_id=patient.id,
        facility_name=current_user.facility,
        queue_date=queue_date,
        department=effective_department,
        reason=payload.reason,
        source=source,
        checked_in_by=current_user.id,
    )

    log_access(
        db, patient.id, current_user.id, current_user.role, "reception_checkin",
        detail=(
            f"queue_number={ticket.queue_number} source={source} "
            f"department={effective_department or ''}"
            + (f" (forced by section={section})" if section is not None else "")
        ),
        actor_facility=current_user.facility,
    )

    return schemas.ReceptionCheckinResponse(
        ticket=schemas.QueueTicketOut.model_validate(ticket),
        patient_full_name=patient.full_name,
        patient_date_of_birth=patient.date_of_birth,
    )


@router.get("/sections", response_model=list[str])
def list_reception_sections(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Active FacilitySection names for the caller's own facility -- the
    reception-desk-readable counterpart to admin-only GET /admin/sections,
    so a receptionist's check-in "Department" dropdown can offer the real
    counter list this hospital uses (not a hardcoded guess). Names only; the
    admin console is where sections are actually managed. Empty list for a
    staffer with no facility, or a facility that hasn't defined any sections
    yet (the web falls back to its built-in list in that case)."""
    if not current_user.facility:
        return []
    return [
        name
        for (name,) in db.query(models.FacilitySection.name)
        .filter(
            models.FacilitySection.facility_name == current_user.facility,
            models.FacilitySection.active.is_(True),
        )
        .order_by(models.FacilitySection.name.asc())
        .all()
    ]
