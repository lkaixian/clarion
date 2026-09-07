"""Clinician room claims + the "My Room" worklist (GET /reception/rooms,
POST /reception/rooms/{room_id}/claim, POST /reception/rooms/release,
GET /reception/my-room)."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ... import models, schemas, auth
from ...database import get_db
from ...audit import log_access
from ..staff import _get_clock_status
from ._common import (
    CONSULT_ROOM_ROLES,
    STAFF_ROLES,
    _active_claim_for_room,
    _active_claim_for_user,
    _claim_out,
    _claim_room_impl,
    _malaysia_today,
    _room_out,
    _user_section,
)

router = APIRouter()


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
    return _claim_room_impl(room_id, db, current_user)


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
