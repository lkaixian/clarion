"""
Reception desk check-in + queue number system.

A receptionist (the dedicated `receptionist` role, or admin / clinician /
records_officer -- see STAFF_ROLES below; the "no separate receptionist
role" note in the original feature brief no longer holds, a `receptionist`
role was added when per-facility page-access control landed, and by default
that role can reach ONLY the Reception page) identifies a walk-in patient
by their IC/NRIC
number (`national_id`, the default front-desk path), an existing emergency
QR code (`card_reference`), a registered physical NFC card (`nfc_uid`), or a
direct internal `patient_id` (fallback), and the system assigns a
per-facility, reset-daily queue number.

CRITICAL: identifying a patient here via card_reference/nfc_uid is a PURE
READ lookup against the same `EmergencyToken` table /emergency/scan and
/emergency/nfc/scan use -- it must NEVER revoke, consume, expire, or
otherwise mutate that row. That grant is the patient's actual
emergency-access credential; this router only ever reuses its identifier
space to find a `patient_id`, the same way a receptionist might read a
name off a badge without it being an official use of the badge. See
`_resolve_patient` below for exactly what is (and isn't) checked.
"""
import base64
import io
import random
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from .auth_router import _resolve_patient_by_nric
from .staff import _get_clock_status

router = APIRouter(prefix="/reception", tags=["reception"])

STAFF_ROLES = ("admin", "records_officer", "clinician", "receptionist")

# Claiming / releasing a consultation room is a "clinician sitting down to see
# patients" action -- a receptionist works the front desk and routes walk-ins
# but never holds a consult room. They can still SEE the room board
# (GET /reception/rooms, GET /reception/my-room) via STAFF_ROLES above.
CONSULT_ROOM_ROLES = ("admin", "records_officer", "clinician")

# This project's target market is Malaysia (Bahasa Melayu localization,
# MySejahtera integration, etc.), so the queue's "day" boundary is computed
# in Malaysia local time (UTC+8, no DST), not UTC -- resetting at UTC
# midnight would silently reset the queue at 8am local time, mid-morning,
# while patients are still physically waiting. Hardcoded to a single
# timezone rather than made per-facility-configurable, which is the right
# hackathon-scope call for a single-country demo app; a real multi-region
# deployment would need this to vary per facility.
#
# `zoneinfo.ZoneInfo` (stdlib, no new import) resolves IANA tz names from
# the OS's own tz database on Linux/macOS, but Windows ships no such
# database at all -- without the `tzdata` PyPI package (added to
# requirements.txt) this raises ZoneInfoNotFoundError on any Windows dev
# machine, discovered directly while verifying this fix in this
# environment, not just inferred from documentation.
MALAYSIA_TZ = ZoneInfo("Asia/Kuala_Lumpur")

# Bounded retry count for the queue-number insert race (see
# _next_queue_number's docstring) -- comfortably more attempts than any
# realistic concurrent-checkin burst at a single facility's front desk
# would ever produce.
MAX_QUEUE_NUMBER_ATTEMPTS = 5


def _malaysia_today() -> tuple[datetime, str]:
    """Returns (utc_start_of_today_in_malaysia, queue_date_string).

    `utc_start_of_today_in_malaysia` is Malaysia-local midnight for "today",
    converted to a naive UTC datetime -- comparable directly against this
    app's existing naive-UTC `DateTime` columns (every other timestamp
    column in this codebase, e.g. QueueTicket.checked_in_at, is stored as
    naive UTC via datetime.utcnow(), so this converts TO that convention
    rather than switching the whole table to timezone-aware columns).
    `queue_date_string` is the Malaysia-local ISO calendar date (e.g.
    "2026-08-19"), stored on QueueTicket.queue_date and used as part of the
    per-facility uniqueness key -- see models.QueueTicket's docstring.
    """
    now_malaysia = datetime.now(MALAYSIA_TZ)
    local_midnight = now_malaysia.replace(hour=0, minute=0, second=0, microsecond=0)
    queue_date_string = local_midnight.date().isoformat()
    # Convert Malaysia-local midnight to the equivalent naive UTC instant so
    # it can be compared directly against the naive-UTC checked_in_at column.
    utc_start = local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return utc_start, queue_date_string


def _user_section(current_user) -> "str | None":
    """The FacilitySection name this staff member's reception console is
    hard-scoped to (models.User.section), or None if they're unscoped.

    When non-None, EVERY reception surface below is narrowed to that one
    section: the queue board only shows tickets whose `department` matches,
    check-ins are forced to that department (the client's payload.department
    is ignored entirely), per-ticket actions 404 on other sections' tickets,
    and the room board hides other sections' tagged rooms. An admin sets
    this via PATCH /admin/staff/{id}. `getattr` with a default keeps this
    safe against any partially-constructed test user object.
    """
    return getattr(current_user, "section", None)


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
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == payload.nfc_uid)
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


def _room_load_today(db: Session, room_id: str, queue_date: str) -> int:
    """Non-cancelled tickets routed to this room today -- the round-robin
    key (a cancelled check-in shouldn't keep counting against a room's load)."""
    return (
        db.query(func.count(models.QueueTicket.id))
        .filter(
            models.QueueTicket.room_id == room_id,
            models.QueueTicket.queue_date == queue_date,
            models.QueueTicket.status != "cancelled",
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


def _today_tickets_query(db: Session, facility_name: str):
    _utc_start, queue_date = _malaysia_today()
    return (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.facility_name == facility_name,
            models.QueueTicket.queue_date == queue_date,
        )
        .order_by(models.QueueTicket.queue_number.asc())
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


@router.get("/queue", response_model=schemas.QueueBoardOut)
def get_queue(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Today's (Malaysia-local calendar date) queue for the calling staff
    member's own facility -- same "manager admin, not super admin" scoping
    already documented on MedicineInventoryItem/Ward (see routers/admin.py's
    module docstring): always `current_user.facility`, never
    client-supplied. A staff account with no facility assigned sees an
    empty board, matching admin.py's list-endpoint convention for the same
    edge case."""
    section = _user_section(current_user)
    if not current_user.facility:
        return schemas.QueueBoardOut(tickets=[], now_serving=None, waiting_count=0, section=section)

    tickets = _today_tickets_query(db, current_user.facility).all()
    # Per-counter scoping: a receptionist pinned to a section sees ONLY that
    # section's tickets. The filter is applied to the already-fetched list
    # (not pushed into the query) so now_serving/waiting_count below are
    # computed against the SAME narrowed set the caller is shown.
    if section is not None:
        tickets = [t for t in tickets if t.department == section]
    now_serving_ticket = next((t for t in tickets if t.status == "called"), None)
    waiting_count = sum(1 for t in tickets if t.status == "waiting")

    return schemas.QueueBoardOut(
        tickets=[schemas.QueueTicketOut.model_validate(t) for t in tickets],
        now_serving=now_serving_ticket.queue_number if now_serving_ticket else None,
        waiting_count=waiting_count,
        section=section,
    )


def _get_ticket_for_staff(ticket_id: str, current_user: models.User, db: Session) -> models.QueueTicket:
    # Same non-leaking scoped-404 as admin.py's _get_*_or_404: "doesn't
    # exist" and "belongs to another facility" are the SAME generic 404, so
    # a staffer can't use the response to confirm a ticket id exists elsewhere.
    ticket = db.query(models.QueueTicket).filter(models.QueueTicket.id == ticket_id).first()
    if not ticket or not current_user.facility or ticket.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Queue ticket not found")
    # Per-counter scoping: a section-pinned staffer can't call/complete/
    # cancel/assign-room on a ticket that belongs to another section -- it's
    # the SAME generic 404 as "wrong facility", so the response never
    # confirms the ticket exists in a section they can't see. Every one of
    # /queue/{id}/call, /complete, /cancel, /assign-room routes through here,
    # so this single check covers all four.
    section = _user_section(current_user)
    if section is not None and ticket.department != section:
        raise HTTPException(status_code=404, detail="Queue ticket not found")
    return ticket


@router.post("/queue/{ticket_id}/call", response_model=schemas.QueueTicketOut)
def call_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Sets this ticket to `called`. If another ticket at this facility is
    already `called`, it is auto-completed first (status -> `done`,
    `completed_at` = now) rather than rejecting the new call -- chosen
    because in real front-desk use, calling the next number IS the signal
    that the previous one's turn is over (the receptionist doesn't
    separately click "complete" on every ticket before calling the next),
    and a hard rejection here would just force an extra click for no real
    benefit. A ticket that was actually skipped/no-show is still
    distinguishable in the log/audit trail (status transitioned straight
    from `called` to `done`, since there is no intermediate "serving"
    status), so this doesn't lose information, just avoids an unnecessary
    blocking step.

    Known, accepted edge case (not a bug, no fix needed): if staff never
    call another ticket AND never manually hit Complete/Cancel on the day's
    LAST `called` ticket, it's left sitting in `called` state indefinitely
    -- there's no background job that auto-closes it. This is harmless: the
    Malaysia-local date filter (`queue_date`, see models.QueueTicket) means
    it naturally drops off every future day's board on its own, and staff
    can still manually complete/cancel it at any time via the endpoints
    below. Deliberately not building an "auto-close stale tickets"
    mechanism for this -- out of scope for this feature."""
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    if ticket.status not in ("waiting", "called"):
        raise HTTPException(status_code=400, detail=f"Cannot call a ticket with status '{ticket.status}'")

    # "Now serving" is per QUEUE LINE, and a section IS a queue line: calling
    # the General counter's next number must not auto-close the Emergency
    # counter's currently-serving patient. So the auto-close only sweeps
    # tickets in the SAME department as the one being called. A facility that
    # doesn't use sections/departments at all (every ticket department=NULL)
    # still gets the old facility-wide behaviour via the `IS NULL` match.
    previously_called_q = db.query(models.QueueTicket).filter(
        models.QueueTicket.facility_name == current_user.facility,
        models.QueueTicket.status == "called",
        models.QueueTicket.id != ticket.id,
    )
    if ticket.department is not None:
        previously_called_q = previously_called_q.filter(
            models.QueueTicket.department == ticket.department
        )
    else:
        previously_called_q = previously_called_q.filter(
            models.QueueTicket.department.is_(None)
        )
    previously_called = previously_called_q.all()
    now = datetime.utcnow()
    for other in previously_called:
        other.status = "done"
        other.completed_at = now

    ticket.status = "called"
    ticket.called_at = now
    db.commit()
    db.refresh(ticket)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "reception_call_ticket",
        detail=f"queue_number={ticket.queue_number} auto_completed={len(previously_called)}",
        actor_facility=current_user.facility,
    )
    return schemas.QueueTicketOut.model_validate(ticket)


@router.post("/queue/{ticket_id}/complete", response_model=schemas.QueueTicketOut)
def complete_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    if ticket.status in ("done", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Ticket is already '{ticket.status}'")

    ticket.status = "done"
    ticket.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "reception_complete_ticket",
        detail=f"queue_number={ticket.queue_number}", actor_facility=current_user.facility,
    )
    return schemas.QueueTicketOut.model_validate(ticket)


@router.post("/queue/{ticket_id}/cancel", response_model=schemas.QueueTicketOut)
def cancel_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    if ticket.status in ("done", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Ticket is already '{ticket.status}'")

    ticket.status = "cancelled"
    ticket.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "reception_cancel_ticket",
        detail=f"queue_number={ticket.queue_number}", actor_facility=current_user.facility,
    )
    return schemas.QueueTicketOut.model_validate(ticket)


@router.post("/queue/{ticket_id}/assign-room", response_model=schemas.QueueTicketOut)
def assign_ticket_room(
    ticket_id: str,
    payload: schemas.AssignRoomRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Manually override which consultation room a ticket is routed to --
    the round-robin auto-assignment at check-in is only a starting point.
    Room must belong to the caller's own facility (same scoping as
    _get_ticket_for_staff)."""
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    room = (
        db.query(models.ConsultationRoom)
        .filter(
            models.ConsultationRoom.id == payload.room_id,
            models.ConsultationRoom.facility_name == current_user.facility,
        )
        .first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="Consultation room not found")

    # Same section confinement as claim_room / list_reception_rooms: a
    # section-scoped user can only route to a room tagged for their section
    # (or an untagged shared room). Non-leaking 404, matching the room-not-
    # found response above.
    section = _user_section(current_user)
    if section is not None and room.department is not None and room.department != section:
        raise HTTPException(status_code=404, detail="Consultation room not found")

    ticket.room_id = room.id
    ticket.room_name = room.room_name
    db.commit()
    db.refresh(ticket)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "reception_assign_room",
        detail=f"queue_number={ticket.queue_number} room={room.room_name}",
        actor_facility=current_user.facility,
    )
    return schemas.QueueTicketOut.model_validate(ticket)


@router.get("/queue/status/{patient_id}", response_model=schemas.QueueStatusOut)
def get_queue_status(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """A patient can view their own queue status (403 otherwise, same
    `current_user.role == "patient" and current_user.patient_id != patient_id`
    pattern used throughout emergency.py); staff can view any patient's.
    Mirrors GET /emergency/current/{patient_id}'s `{"active": false}`
    convention exactly for "nothing to show"."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's queue status")

    _utc_start, queue_date = _malaysia_today()
    active_ticket = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.patient_id == patient_id,
            models.QueueTicket.queue_date == queue_date,
            models.QueueTicket.status.in_(["waiting", "called"]),
        )
        .order_by(models.QueueTicket.checked_in_at.desc())
        .first()
    )
    if not active_ticket:
        return schemas.QueueStatusOut(active=False)

    # A section-scoped STAFF caller only sees tickets in their own section --
    # same confinement as the queue board / _get_ticket_for_staff. A patient
    # viewing their OWN status is unaffected (they passed the check above).
    staff_section = _user_section(current_user) if current_user.role != "patient" else None
    if staff_section is not None and active_ticket.department != staff_section:
        return schemas.QueueStatusOut(active=False)

    facility_tickets = _today_tickets_query(db, active_ticket.facility_name).all()
    now_serving_ticket = next((t for t in facility_tickets if t.status == "called"), None)
    people_ahead = sum(
        1 for t in facility_tickets
        if t.status == "waiting" and t.queue_number < active_ticket.queue_number
    )

    return schemas.QueueStatusOut(
        active=True,
        ticket=schemas.QueueTicketOut.model_validate(active_ticket),
        now_serving=now_serving_ticket.queue_number if now_serving_ticket else None,
        people_ahead=people_ahead,
    )


# ---------- Self-check-in QR (ReceptionStation) ----------
# QR payload prefix -- mirrors emergency.py's `CLARION-EMERGENCY:{ref}`
# convention exactly, just a different scheme name, so both this app's QR
# formats are trivially distinguishable by a scanner without guessing.
STATION_QR_PREFIX = "CLARION-STATION:"


def _render_station_qr_base64(token: str) -> str:
    """Render a ReceptionStation's QR PNG and return it as a
    `data:image/png;base64,...` string -- same approach as
    emergency.py::_render_qr_base64 (fully deterministic from `token`,
    nothing about the image itself is ever persisted)."""
    img = qrcode.make(f"{STATION_QR_PREFIX}{token}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _station_out(station: models.ReceptionStation) -> schemas.ReceptionStationOut:
    return schemas.ReceptionStationOut(
        id=station.id,
        facility_name=station.facility_name,
        department=station.department,
        revoked=station.revoked,
        created_at=station.created_at,
        token=station.token,
        qr_base64=_render_station_qr_base64(station.token),
    )


def _get_active_station(db: Session, facility_name: str) -> models.ReceptionStation | None:
    return (
        db.query(models.ReceptionStation)
        .filter(
            models.ReceptionStation.facility_name == facility_name,
            models.ReceptionStation.revoked.is_(False),
        )
        .order_by(models.ReceptionStation.created_at.desc())
        .first()
    )


@router.get("/station", response_model=schemas.ReceptionStationStatusOut)
def get_station(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """The calling staff member's own facility's active self-check-in QR, if
    one has been generated -- same "always current_user.facility, never
    client-supplied" scoping as GET /reception/queue."""
    if not current_user.facility:
        return schemas.ReceptionStationStatusOut(active=False)
    station = _get_active_station(db, current_user.facility)
    if not station:
        return schemas.ReceptionStationStatusOut(active=False)
    return schemas.ReceptionStationStatusOut(active=True, station=_station_out(station))


def _require_not_section_scoped(current_user) -> None:
    """The self-check-in QR is a single FACILITY-level resource (at most one
    active per facility). A section-scoped account works one counter and must
    not be able to revoke or re-mint the facility's shared QR -- or point a
    replacement at a section it isn't on. That's a front-desk-supervisor /
    admin action; an unscoped staff account (or admin) still does it here."""
    if _user_section(current_user) is not None:
        raise HTTPException(
            status_code=403,
            detail="Managing the facility self-check-in QR isn't available for a section-scoped account.",
        )


@router.post("/station", response_model=schemas.ReceptionStationOut)
def create_or_replace_station(
    payload: schemas.ReceptionStationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Generates a new self-check-in QR for the calling staff member's
    facility, revoking whatever station was previously active there first
    (see models.ReceptionStation's docstring for why this is enforced here,
    not via a DB constraint) -- this is also how a facility rotates its QR
    if a printed copy is lost/compromised, not just first-time setup."""
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )
    _require_not_section_scoped(current_user)

    previous = _get_active_station(db, current_user.facility)
    if previous:
        previous.revoked = True

    station = models.ReceptionStation(
        facility_name=current_user.facility,
        token=secrets.token_urlsafe(16),
        department=payload.department,
        created_by=current_user.id,
    )
    db.add(station)
    db.commit()
    db.refresh(station)

    log_access(
        db, None, current_user.id, current_user.role, "reception_station_create",
        detail=f"facility={current_user.facility} replaced_previous={bool(previous)}",
        actor_facility=current_user.facility,
    )
    return _station_out(station)


@router.post("/station/revoke", response_model=schemas.ReceptionStationStatusOut)
def revoke_station(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Turns off self-check-in for the calling staff member's facility
    entirely (no replacement generated) -- e.g. a printed QR was lost/
    compromised and the desk wants to fall back to staff-only check-in
    until a new one is generated."""
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )
    _require_not_section_scoped(current_user)
    station = _get_active_station(db, current_user.facility)
    if not station:
        raise HTTPException(status_code=404, detail="No active self-check-in station for your facility.")

    station.revoked = True
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "reception_station_revoke",
        detail=f"facility={current_user.facility}", actor_facility=current_user.facility,
    )
    return schemas.ReceptionStationStatusOut(active=False)


@router.post("/self-checkin", response_model=schemas.ReceptionCheckinResponse)
def self_checkin(
    payload: schemas.SelfCheckinRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patient-authenticated counterpart to POST /reception/checkin: a
    patient scans their clinic's printed QR (see ReceptionStation) from the
    mobile app and checks THEMSELVES into the queue -- no receptionist
    involved. Reuses the exact same ticket-issuing path
    (_create_ticket_with_retry) as the staff flow, so both produce
    identically-shaped QueueTicket rows; only `source` ("self_qr" vs.
    "manual"/"qr"/"nfc") and `checked_in_by` (the patient's own user id,
    not a staff member's) differ."""
    if current_user.role != "patient" or not current_user.patient_id:
        raise HTTPException(status_code=403, detail="Only a patient account can self-check-in.")

    station = (
        db.query(models.ReceptionStation)
        .filter(models.ReceptionStation.token == payload.station_token)
        .first()
    )
    if not station or station.revoked:
        raise HTTPException(status_code=404, detail="This check-in code is no longer valid — ask the front desk for a new one.")

    patient = db.query(models.Patient).filter(models.Patient.id == current_user.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    _utc_start, queue_date = _malaysia_today()
    ticket = _create_ticket_with_retry(
        db,
        patient_id=patient.id,
        facility_name=station.facility_name,
        queue_date=queue_date,
        department=station.department,
        reason=payload.reason,
        source="self_qr",
        checked_in_by=current_user.id,
    )

    log_access(
        db, patient.id, current_user.id, current_user.role, "reception_self_checkin",
        detail=f"queue_number={ticket.queue_number} facility={station.facility_name}",
    )

    return schemas.ReceptionCheckinResponse(
        ticket=schemas.QueueTicketOut.model_validate(ticket),
        patient_full_name=patient.full_name,
        patient_date_of_birth=patient.date_of_birth,
    )


# ---------- Clinician room claims + "My Room" worklist ----------
# A clinician self-selects the Bilik they're sitting in (typically right
# after clocking in); that claim is what makes the room's patients show up
# in their "My Room" worklist. The claim is auto-released on clock-out (see
# routers/staff.py::clock_out) -- "once clock over, the info is withdrawn".
# This is PURELY ADDITIVE: it never restricts the clinician's existing
# ability to open any patient record, it just gives them a focused list.
def _active_claim_for_user(db: Session, user_id: str) -> models.RoomClaim | None:
    return (
        db.query(models.RoomClaim)
        .filter(models.RoomClaim.user_id == user_id, models.RoomClaim.released_at.is_(None))
        .order_by(models.RoomClaim.claimed_at.desc())
        .first()
    )


def _active_claim_for_room(db: Session, room_id: str) -> models.RoomClaim | None:
    return (
        db.query(models.RoomClaim)
        .filter(models.RoomClaim.room_id == room_id, models.RoomClaim.released_at.is_(None))
        .first()
    )


def _room_out(db: Session, room: models.ConsultationRoom) -> schemas.ConsultationRoomOut:
    return schemas.ConsultationRoomOut(
        id=room.id,
        facility_name=room.facility_name,
        room_name=room.room_name,
        department=room.department,
        active=room.active,
        updated_by=room.updated_by,
        updated_at=room.updated_at,
        created_at=room.created_at,
        waiting_today=_room_load_today(db, room.id, _malaysia_today()[1]),
    )


def _claim_out(db: Session, claim: models.RoomClaim, room_name: str) -> schemas.RoomClaimOut:
    who = db.query(models.User.full_name).filter(models.User.id == claim.user_id).first()
    return schemas.RoomClaimOut(
        room_id=claim.room_id,
        room_name=room_name,
        user_id=claim.user_id,
        claimed_by_name=who[0] if who else None,
        claimed_at=claim.claimed_at,
    )


@router.get("/rooms", response_model=list[schemas.ReceptionRoomOut])
def list_reception_rooms(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """Active consultation rooms for the caller's facility, each annotated
    with who (if anyone) currently holds it -- the "claim a Bilik" picker."""
    if not current_user.facility:
        return []
    rooms = (
        db.query(models.ConsultationRoom)
        .filter(
            models.ConsultationRoom.facility_name == current_user.facility,
            models.ConsultationRoom.active.is_(True),
        )
        .order_by(models.ConsultationRoom.room_name.asc())
        .all()
    )
    # Per-counter scoping: a section-pinned staffer only sees rooms tagged
    # for their section, plus untagged (department IS NULL) rooms which are
    # shared/claimable by anyone. Other sections' tagged rooms are hidden.
    section = _user_section(current_user)
    if section is not None:
        rooms = [r for r in rooms if r.department == section or r.department is None]
    out = []
    for room in rooms:
        base = _room_out(db, room)
        claim = _active_claim_for_room(db, room.id)
        out.append(schemas.ReceptionRoomOut(
            **base.model_dump(),
            claim=_claim_out(db, claim, room.room_name) if claim else None,
        ))
    return out


@router.post("/rooms/{room_id}/claim", response_model=schemas.RoomClaimOut)
def claim_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULT_ROOM_ROLES)),
):
    """Take a Bilik. Requires the caller to be currently clocked in (the
    claim is meaningless off-shift and would just be dead state to clean
    up). Claiming releases any room this user was already holding, so a
    clinician always holds at most one. 409 if someone else holds the room."""
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned — contact a system administrator.")
    if not _get_clock_status(db, current_user.id).clocked_in:
        raise HTTPException(status_code=409, detail="Clock in before claiming a room.")

    room = (
        db.query(models.ConsultationRoom)
        .filter(
            models.ConsultationRoom.id == room_id,
            models.ConsultationRoom.facility_name == current_user.facility,
            models.ConsultationRoom.active.is_(True),
        )
        .first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="Consultation room not found")

    # Per-counter scoping: a section-pinned clinician can't hold another
    # section's tagged room -- same generic 404 as "room doesn't exist" so
    # it doesn't confirm the room to someone who shouldn't see it. A room
    # with department IS NULL is shared and claimable by anyone.
    section = _user_section(current_user)
    if section is not None and room.department is not None and room.department != section:
        raise HTTPException(status_code=404, detail="Consultation room not found")

    existing_on_room = _active_claim_for_room(db, room_id)
    if existing_on_room and existing_on_room.user_id != current_user.id:
        raise HTTPException(status_code=409, detail="That room is currently claimed by another clinician.")

    now = datetime.utcnow()
    prior = _active_claim_for_user(db, current_user.id)
    if prior and prior.room_id != room_id:
        prior.released_at = now

    if existing_on_room and existing_on_room.user_id == current_user.id:
        claim = existing_on_room
    else:
        claim = models.RoomClaim(
            facility_name=current_user.facility, room_id=room_id, user_id=current_user.id,
        )
        db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against another concurrent claim on this same room
        # (the partial unique index on room_claims fired). Surface it as the
        # same 409 the pre-check above would have given.
        db.rollback()
        raise HTTPException(status_code=409, detail="That room was just claimed by another clinician.")
    db.refresh(claim)

    log_access(
        db, None, current_user.id, current_user.role, "reception_claim_room",
        detail=f"room={room.room_name}", actor_facility=current_user.facility,
    )
    return _claim_out(db, claim, room.room_name)


@router.post("/rooms/release", response_model=schemas.MyRoomOut)
def release_room(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULT_ROOM_ROLES)),
):
    """Give up the room the caller currently holds (no-op if they hold none)."""
    claim = _active_claim_for_user(db, current_user.id)
    if claim:
        claim.released_at = datetime.utcnow()
        db.commit()
        log_access(
            db, None, current_user.id, current_user.role, "reception_release_room",
            actor_facility=current_user.facility,
        )
    return _my_room(db, current_user)


def _my_room(db: Session, current_user: models.User) -> schemas.MyRoomOut:
    clocked_in = _get_clock_status(db, current_user.id).clocked_in
    claim = _active_claim_for_user(db, current_user.id)
    # The "withdrawn on clock-out" rule: even if a stale claim row somehow
    # survived, an off-shift clinician sees nothing.
    if not clocked_in or not claim:
        return schemas.MyRoomOut(clocked_in=clocked_in, room=None, tickets=[])

    room = db.query(models.ConsultationRoom).filter(models.ConsultationRoom.id == claim.room_id).first()
    if not room:
        return schemas.MyRoomOut(clocked_in=clocked_in, room=None, tickets=[])

    _utc_start, queue_date = _malaysia_today()
    tickets = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.room_id == room.id,
            models.QueueTicket.queue_date == queue_date,
        )
        .order_by(models.QueueTicket.queue_number.asc())
        .all()
    )
    return schemas.MyRoomOut(
        clocked_in=clocked_in,
        room=_room_out(db, room),
        tickets=[schemas.QueueTicketOut.model_validate(t) for t in tickets],
    )


@router.get("/my-room", response_model=schemas.MyRoomOut)
def get_my_room(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    return _my_room(db, current_user)


# ---------- Ward admissions + Ward Map ----------
# Per-bed admission/discharge, usable by any staff role (same STAFF_ROLES as
# check-in). models.Admission is the source of truth for the bed grid; the
# legacy aggregate Ward.occupied_beds counter is deliberately NOT touched
# here (see the approved plan's assumptions). Each admission also records an
# `inpatient` Encounter on the patient, mirroring patients.py::add_encounter.
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
