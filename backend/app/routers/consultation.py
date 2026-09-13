"""
Clinician "Start session" -- clock-in + claim-a-room in one step, plus the
focused per-room consultation worklist and consultation sign-off.

This is the clinician's home page now that the default clinician role no
longer has the Reception page (see app/permissions.py::DEFAULT_ROLE_PAGES /
rewrite_legacy_clinician_pages). Everything here is an ADDITIVE convenience
layer over the existing primitives:
  - "start session" = staff.py's clock-in + reception.py's claim_room, in
    one transaction,
  - the worklist = reception.py's "My Room" (today's QueueTickets routed to
    the claimed room), with the patient's name/DOB joined in,
  - call / complete reuse reception.py's per-department "auto-close the
    previously-called ticket" logic verbatim.

Sign-off (POST .../complete) is the one genuinely new thing: it REQUIRES a
saved digital signature (routers/profile.py) and writes a signed outpatient
Encounter into the patient's cross-facility history.

reception.py does NOT import this module, so importing its helpers here is
cycle-free (same direction as admin.py importing reception.py).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from .staff import _get_clock_status
from .reception import (
    _malaysia_today,
    _active_claim_for_user,
    _active_claim_for_room,
    _user_section,
    _room_out,
    _claim_out,
    _get_ticket_for_staff,
    # The shared queue/room LOGIC -- not the route handlers (see the note by
    # these `_impl` defs in reception.py). Calling the routes directly would
    # silently break the day one gained a new Depends(...).
    _call_ticket_impl,
    _cancel_ticket_impl,
    _claim_room_impl,
)
from .profile import (
    save_signature_from_b64,
    copy_signature_snapshot,
)
from .patients import _serialize_patient
from ..storage import apply_object_meta
from ..ai.cds_hint import generate_cds_hint

router = APIRouter(prefix="/consultation", tags=["consultation"])

# admin / records_officer keep the Reception page and could equally work
# from there; a clinician can ONLY work from here now.
CONSULTATION_ROLES = ("admin", "records_officer", "clinician")


def _ticket_in_my_room_or_404(ticket_id: str, current_user: models.User, db: Session) -> models.QueueTicket:
    """The consultation worklist is per-CLAIMED-ROOM: you can only call /
    complete / cancel a ticket that is routed to the room you currently
    hold. Without this, a clinician could sign off (and attribute a signed
    Encounter to themselves for) any patient in their facility/section --
    including one sitting in a colleague's room.

    Layers on top of `_get_ticket_for_staff` (facility + section scoped-404),
    then requires an active RoomClaim whose room == ticket.room_id. Same
    non-leaking 404 as "ticket not found" so it doesn't confirm a ticket id
    the caller has no business seeing; a 409 only once we know they DO hold a
    room but not this ticket's."""
    ticket = _get_ticket_for_staff(ticket_id, current_user, db)
    claim = _active_claim_for_user(db, current_user.id)
    if claim is None:
        raise HTTPException(status_code=409, detail="Start a consultation session (claim a room) first.")
    if ticket.room_id != claim.room_id:
        raise HTTPException(status_code=404, detail="Queue ticket not found")
    return ticket


def _room_state(db: Session, room: models.ConsultationRoom) -> schemas.ConsultationRoomStateOut:
    """Room fields (+ today's routed-ticket count) plus who currently holds
    it -- reuses reception.py's _room_out / _active_claim_for_room / _claim_out
    so the shape never drifts from the Reception room board."""
    base = _room_out(db, room)
    claim = _active_claim_for_room(db, room.id)
    return schemas.ConsultationRoomStateOut(
        **base.model_dump(),
        claim=_claim_out(db, claim, room.room_name) if claim else None,
    )


def _consultation_ticket_out(
    ticket: models.QueueTicket, patient: "models.Patient | None"
) -> schemas.ConsultationTicketOut:
    return schemas.ConsultationTicketOut(
        **schemas.QueueTicketOut.model_validate(ticket).model_dump(),
        patient_full_name=patient.full_name if patient else None,
        patient_date_of_birth=patient.date_of_birth if patient else None,
    )


def _my_room(db: Session, current_user: models.User) -> schemas.ConsultationMyRoomOut:
    """Mirrors reception.py::_my_room's guard exactly: nothing is shown
    unless the caller is BOTH clocked in AND holds an active RoomClaim."""
    clocked_in = _get_clock_status(db, current_user.id).clocked_in
    claim = _active_claim_for_user(db, current_user.id)
    if not clocked_in or not claim:
        return schemas.ConsultationMyRoomOut(clocked_in=clocked_in, room=None, tickets=[])

    room = (
        db.query(models.ConsultationRoom)
        .filter(models.ConsultationRoom.id == claim.room_id)
        .first()
    )
    if not room:
        return schemas.ConsultationMyRoomOut(clocked_in=clocked_in, room=None, tickets=[])

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
    patients = {}
    if tickets:
        pid_set = {t.patient_id for t in tickets}
        for p in db.query(models.Patient).filter(models.Patient.id.in_(pid_set)).all():
            patients[p.id] = p

    return schemas.ConsultationMyRoomOut(
        clocked_in=True,
        room=_room_state(db, room),
        tickets=[_consultation_ticket_out(t, patients.get(t.patient_id)) for t in tickets],
    )


@router.get("/rooms", response_model=list[schemas.ConsultationRoomStateOut])
def list_consultation_rooms(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Active consultation rooms for the caller's facility, each annotated
    with who (if anyone) currently holds it -- the "pick a room" list for
    Start session. Section-scoped identically to the Reception room board."""
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
    section = _user_section(current_user)
    if section is not None:
        rooms = [r for r in rooms if r.department == section or r.department is None]
    return [_room_state(db, r) for r in rooms]


@router.get("/my-room", response_model=schemas.ConsultationMyRoomOut)
def get_my_room(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    return _my_room(db, current_user)


@router.post("/session/start", response_model=schemas.ConsultationMyRoomOut)
def start_session(
    payload: schemas.ConsultationSessionStartRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """One step: if the caller has no open shift, clock them in; then claim
    `room_id`. The claim reuses reception.py::claim_room verbatim, so all of
    its rules carry over -- releases any room this user already held, 409 if
    another clinician holds the target room, non-leaking 404 on a
    section-mismatch, IntegrityError -> 409 on a claim race."""
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )

    # Claim the room FIRST -- if it 409s (held) / 404s (section mismatch) /
    # races, nothing has been committed yet, so the caller is never left
    # clocked-in with no room (a half-started session). claim_room itself
    # requires the caller to be clocked in, so if they aren't, do a bare
    # clock-in immediately before it -- and roll that back if the claim then
    # fails, so a failed start leaves NO trace.
    open_event = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == current_user.id,
            models.StaffClockEvent.clock_out_at.is_(None),
        )
        .first()
    )
    clock_event = None
    if not open_event:
        clock_event = models.StaffClockEvent(
            user_id=current_user.id, facility_name=current_user.facility,
        )
        db.add(clock_event)
        db.flush()  # visible to claim_room's clocked-in check, not yet committed

    try:
        _claim_room_impl(payload.room_id, db, current_user)
    except HTTPException:
        if clock_event is not None:
            db.rollback()  # undo the just-added clock-in
        raise

    log_access(
        db, None, current_user.id, current_user.role, "consultation_session_start",
        detail=f"room_id={payload.room_id}", actor_facility=current_user.facility,
    )
    return _my_room(db, current_user)


@router.post("/session/end", response_model=schemas.ConsultationMyRoomOut)
def end_session(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Close the caller's open shift and release their room claim (best
    effort -- a no-op if they had neither). Returns the now-cleared state."""
    now = datetime.utcnow()

    open_event = (
        db.query(models.StaffClockEvent)
        .filter(
            models.StaffClockEvent.user_id == current_user.id,
            models.StaffClockEvent.clock_out_at.is_(None),
        )
        .first()
    )
    if open_event:
        open_event.clock_out_at = now
        db.add(open_event)

    for claim in (
        db.query(models.RoomClaim)
        .filter(
            models.RoomClaim.user_id == current_user.id,
            models.RoomClaim.released_at.is_(None),
        )
        .all()
    ):
        claim.released_at = now

    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "consultation_session_end",
        actor_facility=current_user.facility,
    )
    return _my_room(db, current_user)


@router.post("/tickets/{ticket_id}/call", response_model=schemas.QueueTicketOut)
def call_consultation_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Call the next patient. Confined to a ticket routed to the room the
    caller currently holds (_ticket_in_my_room_or_404), then delegates to
    reception.py::call_ticket for the per-department "auto-close the
    previously-called ticket" sweep."""
    _ticket_in_my_room_or_404(ticket_id, current_user, db)
    return schemas.QueueTicketOut.model_validate(_call_ticket_impl(ticket_id, db, current_user))


@router.post("/tickets/{ticket_id}/cancel", response_model=schemas.QueueTicketOut)
def cancel_consultation_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Mark a no-show. Clinicians lost the Reception page (and its cancel
    action), so the consultation worklist needs its own -- same per-room
    confinement as call/complete, then delegates to reception.py::cancel_ticket.
    No signature (nothing clinical happened)."""
    _ticket_in_my_room_or_404(ticket_id, current_user, db)
    return schemas.QueueTicketOut.model_validate(_cancel_ticket_impl(ticket_id, db, current_user))


@router.post("/tickets/{ticket_id}/complete")
def complete_consultation_ticket(
    ticket_id: str,
    payload: schemas.ConsultationCompleteRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Sign off a consultation: marks the ticket done AND writes a signed
    outpatient Encounter into the patient's history. REQUIRES a saved
    digital signature -- 409 if the caller has none and passed no
    `signature_b64` to save on the spot."""
    ticket = _ticket_in_my_room_or_404(ticket_id, current_user, db)
    if ticket.status in ("done", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Ticket is already '{ticket.status}'")

    if not current_user.signature_object_key and not payload.signature_b64:
        raise HTTPException(
            status_code=409,
            detail="Save your signature in your profile before signing off a consultation.",
        )
    if payload.signature_b64 and not current_user.signature_object_key:
        save_signature_from_b64(db, current_user, payload.signature_b64)

    referral = None
    if payload.referral_service_request_id:
        referral = (
            db.query(models.ServiceRequest)
            .filter(models.ServiceRequest.id == payload.referral_service_request_id)
            .first()
        )
        # The reference must be real, for this patient, and authored by this
        # facility.  A signed clinical record must never become a cross-site
        # identifier oracle or point at another facility's work.
        if (
            referral is None
            or referral.patient_id != ticket.patient_id
            or not current_user.facility
            or referral.ordering_facility_name != current_user.facility
        ):
            raise HTTPException(status_code=404, detail="Referral service request not found")

    now = datetime.utcnow()
    ticket.status = "done"
    ticket.completed_at = now

    encounter = models.Encounter(
        patient_id=ticket.patient_id,
        facility_name=current_user.facility or ticket.facility_name,
        encounter_type="outpatient",
        reason=ticket.reason,
        notes=payload.note,
        started_at=ticket.checked_in_at,
        signed_by=current_user.id,
        signed_by_name=current_user.full_name,
        signed_by_role=current_user.role,
    )
    db.add(encounter)
    db.flush()  # need encounter.id for the per-row signature snapshot key

    structured_values = (
        payload.subjective, payload.objective, payload.assessment, payload.plan,
        payload.treatment_plan, payload.follow_up_at, payload.referral_service_request_id,
    )
    if any(value is not None for value in structured_values):
        db.add(models.ConsultationNote(
            encounter_id=encounter.id,
            patient_id=ticket.patient_id,
            facility_name=current_user.facility or ticket.facility_name,
            subjective=payload.subjective,
            objective=payload.objective,
            assessment=payload.assessment,
            plan=payload.plan,
            treatment_plan=payload.treatment_plan,
            follow_up_at=payload.follow_up_at,
            referral_service_request_id=referral.id if referral else None,
            signed_by=current_user.id,
            signed_by_name=current_user.full_name,
            signed_at=now,
        ))

    apply_object_meta(
        encounter,
        copy_signature_snapshot(current_user, f"encounters/{encounter.id}.png"),
        "signature",
    )
    db.add(encounter)
    db.commit()
    db.refresh(ticket)
    db.refresh(encounter)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "consultation_complete",
        detail=f"queue_number={ticket.queue_number} encounter_id={encounter.id}",
        actor_facility=current_user.facility,
    )

    return {
        "ticket": schemas.QueueTicketOut.model_validate(ticket).model_dump(),
        "encounter_id": encounter.id,
    }


@router.post("/tickets/{ticket_id}/cds-hint", response_model=schemas.CdsHintOut)
def get_cds_hint(
    ticket_id: str,
    payload: schemas.CdsHintRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Reference-only clinical decision support hint (P4.3b) for a ticket
    currently in the caller's own room -- see ai/cds_hint.py. Nothing here
    is persisted; it's advisory only, called as many times as the clinician
    likes while drafting the note, never at sign-off."""
    ticket = _ticket_in_my_room_or_404(ticket_id, current_user, db)
    patient = db.query(models.Patient).filter(models.Patient.id == ticket.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    record = _serialize_patient(patient, db, current_user)
    draft_note = {
        "subjective": payload.subjective, "objective": payload.objective,
        "assessment": payload.assessment, "plan": payload.plan,
    }
    result = generate_cds_hint(record, draft_note, reason=ticket.reason)

    log_access(
        db, ticket.patient_id, current_user.id, current_user.role, "generate_cds_hint",
        actor_facility=current_user.facility,
    )
    return result


@router.get("/encounters/{encounter_id}/note", response_model=schemas.ConsultationNoteOut)
def get_consultation_note(
    encounter_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CONSULTATION_ROLES)),
):
    """Return a structured note only to its authoring facility.

    Cross-facility clinical sharing stays centralised in patients.py; this
    focused consultation endpoint deliberately has no broader read mode.
    """
    note = (
        db.query(models.ConsultationNote)
        .filter(models.ConsultationNote.encounter_id == encounter_id)
        .first()
    )
    if note is None or not current_user.facility or note.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Consultation note not found")
    return schemas.ConsultationNoteOut.model_validate(note)
