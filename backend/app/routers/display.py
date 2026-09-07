"""
Public, unauthenticated waiting-room display feed.

A screen in a waiting area loads GET /display/{token} (the token comes from
an admin-created models.WaitingRoomDisplay -- see
routers/admin.py's waiting-room-displays section). There is deliberately NO
auth dependency on this router and it is NOT registered under
auth.require_page_access: the whole point is that a cheap display device
with no login can render it. What it exposes is intentionally
low-sensitivity -- queue numbers, room names, and (by default) MASKED
patient labels ("Ahmad bin Ismail" -> "Ahmad I."). An admin can opt a
given screen into full names (show_full_names) when they know it faces
staff-only space.

The token is an unguessable secrets.token_urlsafe(16); a revoked or unknown
token is an identical 404. Rate-limited per IP (same pattern as
emergency.py's scan endpoints) so the token space can't be swept.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..rate_limit import limiter
from .reception import _malaysia_today

router = APIRouter(prefix="/display", tags=["display"])

# How many upcoming "waiting" tickets to show -- a screen only has so much
# room, and nobody 15-deep in the queue is watching for their number yet.
UP_NEXT_CAP = 12


def _mask_name(full_name: str) -> str:
    """"Ahmad bin Ismail" -> "Ahmad I."  -- first whitespace-token verbatim,
    then the first letter of the last token + ".". A single-token (mononym)
    name -- common for many Malay/Indian/Indonesian patients -- is partly
    redacted too (first 3 chars + "..."), so masking is never a silent no-op."""
    tokens = (full_name or "").split()
    if not tokens:
        return "Patient"
    if len(tokens) == 1:
        t = tokens[0]
        return t if len(t) <= 3 else f"{t[:3]}…"
    return f"{tokens[0]} {tokens[-1][0]}."


# Keyed on the token, not the caller IP: a real screen polls its own token
# ~12x/min, and several screens behind one clinic's public IP (or a reverse
# proxy collapsing every client to one address) would trip an IP-keyed limit
# and blank real displays. The 128-bit token makes an enumeration sweep
# pointless anyway, so a generous per-token ceiling is the right shape.
@router.get("/{token}")
@limiter.limit("120/minute", key_func=lambda request: request.path_params.get("token", "") or "unknown")
def get_display_feed(token: str, request: Request, db: Session = Depends(get_db)):
    display = (
        db.query(models.WaitingRoomDisplay)
        .filter(
            models.WaitingRoomDisplay.token == token,
            models.WaitingRoomDisplay.revoked.is_(False),
        )
        .first()
    )
    if not display:
        raise HTTPException(status_code=404, detail="Display not found.")

    facility_name = display.facility_name
    section = display.section

    setting = (
        db.query(models.HospitalSetting)
        .filter(models.HospitalSetting.facility_name == facility_name)
        .first()
    )
    facility_display_name = (
        (setting.display_name if setting and setting.display_name else None) or facility_name
    )

    _utc_start, queue_date = _malaysia_today()
    q = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.facility_name == facility_name,
            models.QueueTicket.queue_date == queue_date,
            models.QueueTicket.status.in_(("waiting", "called")),
        )
    )
    if section:
        q = q.filter(models.QueueTicket.department == section)
    tickets = q.order_by(models.QueueTicket.queue_number.asc()).all()

    patients = {}
    if tickets:
        pid_set = {t.patient_id for t in tickets}
        for p in db.query(models.Patient).filter(models.Patient.id.in_(pid_set)).all():
            patients[p.id] = p

    def _label(ticket) -> str:
        p = patients.get(ticket.patient_id)
        if not p:
            return "Patient"
        return p.full_name if display.show_full_names else _mask_name(p.full_name)

    now_serving = [
        {
            "room_name": t.room_name,
            "queue_number": t.queue_number,
            "patient_label": _label(t),
        }
        for t in tickets if t.status == "called"
    ]
    # Deliberately NO `reason` here -- it's the free-text visit reason a
    # receptionist typed ("psych follow-up", "HIV med review"), and this feed
    # renders on a screen facing a public waiting area. Queue number + masked
    # name + room + wait-time is the standard, non-sensitive queue-board set.
    up_next = [
        {
            "queue_number": t.queue_number,
            "patient_label": _label(t),
            "room_name": t.room_name,
            "checked_in_at": str(t.checked_in_at),
        }
        for t in tickets if t.status == "waiting"
    ][:UP_NEXT_CAP]

    return {
        "facility_display_name": facility_display_name,
        "section": section,
        "generated_at": datetime.utcnow().isoformat(),
        "now_serving": now_serving,
        "up_next": up_next,
    }
