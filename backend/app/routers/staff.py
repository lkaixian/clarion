"""
Self-service staff clock-in/clock-out. Any staff member (admin, clinician,
records_officer, pharmacist, receptionist) can clock themselves in/out here
-- this router is
deliberately "for yourself only", it never accepts a target user_id from the
client. The admin-only READ-ONLY roster view of OTHER staff's live clock
status (GET /admin/staff, GET /admin/staff/{user_id}/clock-history) lives in
routers/admin.py instead, and reuses `_get_clock_status` from this module
rather than duplicating the "find the open event / find the most recent
closed event" query logic (same cross-router pure-logic reuse pattern as
ai/interactions.py vs routers/ai_router.py).

Admin-initiated clock actions (an admin clocking someone else in/out) and any
account editing/deactivation are explicitly OUT OF SCOPE for this pass -- see
the roster endpoints in admin.py, which are read-only.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access

router = APIRouter(prefix="/staff", tags=["staff"])


def _get_clock_status(db: Session, user_id: str) -> schemas.ClockStatusOut:
    """Shared read used by all three endpoints below (and by
    admin.py::list_staff_roster for each roster row) -- a single place that
    knows how to derive "clocked in?", "since when?", and "when did they last
    clock out?" from the StaffClockEvent rows, so that logic never drifts
    between the self-service and admin-roster call sites."""
    open_event = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == user_id,
            models.StaffClockEvent.clock_out_at.is_(None),
        )
        .order_by(models.StaffClockEvent.clock_in_at.desc())
        .first()
    )
    last_closed = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == user_id,
            models.StaffClockEvent.clock_out_at.isnot(None),
        )
        .order_by(models.StaffClockEvent.clock_out_at.desc())
        .first()
    )
    return schemas.ClockStatusOut(
        clocked_in=open_event is not None,
        since=open_event.clock_in_at if open_event else None,
        last_clock_out_at=last_closed.clock_out_at if last_closed else None,
    )


def batch_clock_status(db: Session, user_ids) -> dict:
    """`{user_id: ClockStatusOut}` for many users in TWO queries total --
    the roster form of `_get_clock_status`, which is 2 queries per user.
    Code-review follow-up 2026-09-07."""
    ids = [u for u in user_ids if u]
    if not ids:
        return {}

    # ORDER BY ... ASC + dict-overwrite => the last row kept per user is the
    # most recent one (same "latest wins" as the single-row `.first()` with
    # DESC).
    open_by_user: dict = {}
    for ev in (
        db.query(models.StaffClockEvent)
        .filter(models.StaffClockEvent.user_id.in_(ids), models.StaffClockEvent.clock_out_at.is_(None))
        .order_by(models.StaffClockEvent.clock_in_at.asc())
        .all()
    ):
        open_by_user[ev.user_id] = ev

    last_closed_by_user: dict = {}
    for ev in (
        db.query(models.StaffClockEvent)
        .filter(models.StaffClockEvent.user_id.in_(ids), models.StaffClockEvent.clock_out_at.isnot(None))
        .order_by(models.StaffClockEvent.clock_out_at.asc())
        .all()
    ):
        last_closed_by_user[ev.user_id] = ev

    out: dict = {}
    for uid in ids:
        oe = open_by_user.get(uid)
        lc = last_closed_by_user.get(uid)
        out[uid] = schemas.ClockStatusOut(
            clocked_in=oe is not None,
            since=oe.clock_in_at if oe else None,
            last_clock_out_at=lc.clock_out_at if lc else None,
        )
    return out


@router.post("/clock-in", response_model=schemas.ClockStatusOut)
def clock_in(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer", "pharmacist", "receptionist")),
):
    if not current_user.facility:
        # Same message convention as admin.py::_require_facility's
        # facility-less-create guard -- a staff account with no assigned
        # hospital has nowhere to snapshot facility_name from.
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )

    existing_open = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == current_user.id,
            models.StaffClockEvent.clock_out_at.is_(None),
        )
        .first()
    )
    if existing_open:
        raise HTTPException(
            status_code=409,
            detail=f"Already clocked in since {existing_open.clock_in_at.isoformat()}.",
        )

    event = models.StaffClockEvent(user_id=current_user.id, facility_name=current_user.facility)
    db.add(event)
    db.commit()

    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="staff_clock_in", actor_facility=current_user.facility,
    )
    return _get_clock_status(db, current_user.id)


@router.post("/clock-out", response_model=schemas.ClockStatusOut)
def clock_out(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer", "pharmacist", "receptionist")),
):
    open_event = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == current_user.id,
            models.StaffClockEvent.clock_out_at.is_(None),
        )
        .first()
    )
    if not open_event:
        raise HTTPException(status_code=409, detail="You are not currently clocked in.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    open_event.clock_out_at = now
    db.add(open_event)

    # Clocking out withdraws the clinician's "My Room" worklist -- release any
    # consultation-room claim they were holding so the Bilik frees up for the
    # next shift (see routers/reception.py's room-claim section). Kept here
    # rather than in reception.py so a clock-out through ANY path always does
    # it; the reverse dependency direction (reception imports staff) means we
    # touch models.RoomClaim directly instead of importing back.
    for claim in (
        db.query(models.RoomClaim)
        .filter(models.RoomClaim.user_id == current_user.id, models.RoomClaim.released_at.is_(None))
        .all()
    ):
        claim.released_at = now

    db.commit()

    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="staff_clock_out", actor_facility=current_user.facility,
    )
    return _get_clock_status(db, current_user.id)


@router.get("/clock-status", response_model=schemas.ClockStatusOut)
def get_clock_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer", "pharmacist", "receptionist")),
):
    """Read-only status check, no side effects -- doesn't log an access,
    same reasoning as emergency.py::get_current_card_status's docstring
    (a plain status poll isn't itself a meaningful audit event)."""
    return _get_clock_status(db, current_user.id)
