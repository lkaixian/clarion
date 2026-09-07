"""Self-check-in QR (ReceptionStation): the facility's printed QR code and the
patient-authenticated self-check-in that consumes it."""
import base64
import io
import secrets

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, schemas, auth
from ...database import get_db
from ...audit import log_access
from ._common import STAFF_ROLES, _malaysia_today, _require_not_section_scoped
from .checkin import _create_ticket_with_retry

router = APIRouter()

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
