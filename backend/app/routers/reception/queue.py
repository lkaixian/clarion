"""The reception queue board + per-ticket actions (call / complete / cancel /
assign-room) + a patient's own queue status."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ... import models, schemas, auth
from ...database import get_db
from ...audit import log_access
from ...printing import build_ticket_escpos
from ._common import (
    STAFF_ROLES,
    _call_ticket_impl,
    _cancel_ticket_impl,
    _get_ticket_for_staff,
    _malaysia_today,
    _user_section,
)

router = APIRouter()


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
    mechanism for this -- out of scope for this feature.

    "Now serving" is per QUEUE LINE, and a section IS a queue line: calling
    the General counter's next number must not auto-close the Emergency
    counter's currently-serving patient -- the auto-close only sweeps
    tickets in the SAME department (a facility not using sections has every
    ticket department=NULL and gets the old facility-wide behaviour)."""
    return schemas.QueueTicketOut.model_validate(_call_ticket_impl(ticket_id, db, current_user))


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
    ticket.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
    return schemas.QueueTicketOut.model_validate(_cancel_ticket_impl(ticket_id, db, current_user))


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


@router.get("/queue/{ticket_id}/ticket.escpos")
def print_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*STAFF_ROLES)),
):
    """P3.9: this ticket as raw ESC/POS command bytes for a
    compatible receipt printer -- see app/printing.py's module docstring for
    why this hands back bytes rather than talking to a printer directly.
    Same own-facility scoping as every other per-ticket action here
    (_get_ticket_for_staff)."""
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    setting = (
        db.query(models.HospitalSetting)
        .filter(models.HospitalSetting.facility_name == ticket.facility_name)
        .first()
    )
    facility_display_name = (
        (setting.display_name if setting and setting.display_name else None) or ticket.facility_name
    )
    ticket_bytes = build_ticket_escpos(
        facility_display_name=facility_display_name,
        queue_number=ticket.queue_number,
        department=ticket.department,
        room_name=ticket.room_name,
        checked_in_at=ticket.checked_in_at,
    )
    return Response(content=ticket_bytes, media_type="application/vnd.escpos")


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
