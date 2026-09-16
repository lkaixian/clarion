"""
Shared reception helpers.

Everything in here is used by two or more of the reception sub-routers, or is
imported directly by another router (consultation.py / admin.py / display.py /
patients.py). The parent package re-exports the names other modules rely on --
see ``reception/__init__.py``.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import models, schemas
from ...audit import log_access
from ..staff import _get_clock_status

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


# The `_impl` functions below hold the queue/room logic that BOTH a reception
# route and consultation.py need. consultation.py imports and calls these
# directly -- never the route handlers -- so a route gaining a new
# `Depends(...)` can't silently change what consultation.py runs
# (code-review follow-up 2026-09-07).
def _call_ticket_impl(ticket_id: str, db: Session, current_user: models.User) -> models.QueueTicket:
    """See call_ticket's docstring. Returns the mutated ticket row."""
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    if ticket.status not in ("waiting", "called"):
        raise HTTPException(status_code=400, detail=f"Cannot call a ticket with status '{ticket.status}'")

    previously_called_q = db.query(models.QueueTicket).filter(
        models.QueueTicket.facility_name == current_user.facility,
        models.QueueTicket.status == "called",
        models.QueueTicket.id != ticket.id,
    )
    if ticket.department is not None:
        previously_called_q = previously_called_q.filter(models.QueueTicket.department == ticket.department)
    else:
        previously_called_q = previously_called_q.filter(models.QueueTicket.department.is_(None))
    previously_called = previously_called_q.all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
    return ticket


def _cancel_ticket_impl(ticket_id: str, db: Session, current_user: models.User) -> models.QueueTicket:
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    if ticket.status in ("done", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Ticket is already '{ticket.status}'")

    ticket.status = "cancelled"
    ticket.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(ticket)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "reception_cancel_ticket",
        detail=f"queue_number={ticket.queue_number}", actor_facility=current_user.facility,
    )
    return ticket


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


# Clinician room-claim helpers (the routes are in rooms.py).
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


def _claim_room_impl(room_id: str, db: Session, current_user: models.User):
    """See claim_room's docstring. Returns the RoomClaimOut. Shared with
    consultation.py's "start session" (code-review follow-up 2026-09-07)."""
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
