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

This router is a package: the endpoints live in `checkin` / `queue` /
`stations` / `rooms` / `admissions`, and the helpers shared between them
(or imported by consultation.py / admin.py / display.py / patients.py)
live in `_common` and are re-exported from here so
`from .reception import _malaysia_today` keeps working unchanged.
"""
from fastapi import APIRouter

# Re-exported so `from .reception import ...` keeps working for the other
# router modules that reach in: admin.py / display.py / patients.py want
# `_malaysia_today`; consultation.py wants the room-claim + queue helpers
# below (it reuses reception's LOGIC, not its route handlers).
from ._common import (  # noqa: F401
    _active_claim_for_room,
    _active_claim_for_user,
    _call_ticket_impl,
    _cancel_ticket_impl,
    _claim_out,
    _claim_room_impl,
    _get_ticket_for_staff,
    _malaysia_today,
    _room_out,
    _user_section,
)
from . import admissions, checkin, queue, rooms, stations

router = APIRouter(prefix="/reception", tags=["reception"])
router.include_router(checkin.router)
router.include_router(queue.router)
router.include_router(stations.router)
router.include_router(rooms.router)
router.include_router(admissions.router)

__all__ = [
    "router",
    "_malaysia_today",
    "_user_section",
    "_get_ticket_for_staff",
    "_call_ticket_impl",
    "_cancel_ticket_impl",
    "_claim_room_impl",
    "_active_claim_for_user",
    "_active_claim_for_room",
    "_room_out",
    "_claim_out",
]
