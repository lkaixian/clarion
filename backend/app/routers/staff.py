"""
Self-service staff clock-in/clock-out. Any staff member (admin, clinician,
records_officer) can clock themselves in/out here -- this router is
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
from datetime import datetime

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


@router.post("/clock-in", response_model=schemas.ClockStatusOut)
def clock_in(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
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
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
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

    open_event.clock_out_at = datetime.utcnow()
    db.add(open_event)
    db.commit()

    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="staff_clock_out", actor_facility=current_user.facility,
    )
    return _get_clock_status(db, current_user.id)


@router.get("/clock-status", response_model=schemas.ClockStatusOut)
def get_clock_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    """Read-only status check, no side effects -- doesn't log an access,
    same reasoning as emergency.py::get_current_card_status's docstring
    (a plain status poll isn't itself a meaningful audit event)."""
    return _get_clock_status(db, current_user.id)
