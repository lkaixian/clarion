"""
Reminder-offset computation for doctor-published appointments
(models.Appointment).

This module deliberately holds ONLY pure, no-I/O logic (no DB session, no
HTTP), mirroring the split already used between ai/interactions.py (pure
domain logic) and routers/ai_router.py (the HTTP layer that calls it) --
see routers/appointments.py for the endpoints that call into this module.

Why the exact hour-offset values (24, 3) live ONLY here, not duplicated as
magic numbers anywhere else in this codebase: `compute_reminder_offsets` is
the single source of truth for "when does a reminder fire for this
appointment". A client (web display, or a future mobile port of the same
rule) can call this same function -- or, if it needs to reproduce the
result without a shared Python runtime, replicate it EXACTLY from this
docstring/implementation -- rather than re-deriving the rule from prose
scattered across tickets/chat history. If these constants ever need to
change (e.g. product decides on 48h instead of 24h), there is exactly one
place to edit.
"""

from datetime import date as date_cls, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import models

# Always-on reminder offsets (hours before scheduled_at), regardless of
# fasting/extra reminders. See module docstring for why these live only here.
STANDARD_REMINDER_HOURS_BEFORE = [24, 3]

# P3.10 self-booking slot grid. Same "Asia/Kuala_Lumpur,
# hardcoded rather than a per-facility configurable schedule" hackathon-scope
# call routers/reception/_common.py::_malaysia_today already made for the
# queue-reset hour -- a real deployment would want per-facility opening
# hours, not built here since nothing today needs it.
MALAYSIA_TZ = ZoneInfo("Asia/Kuala_Lumpur")
SLOT_MINUTES = 30
CLINIC_OPEN_HOUR = 8
CLINIC_CLOSE_HOUR = 17


def compute_available_slots(local_date: date_cls, booked_at: set[datetime]) -> list[datetime]:
    """Fixed `SLOT_MINUTES`-wide grid within clinic hours on `local_date`
    (Malaysia-local), minus any start time already in `booked_at`. Returns
    naive-UTC datetimes -- same convention models.Appointment.scheduled_at is
    read/written in elsewhere in this module (see compute_reminder_offsets's
    use of datetime.utcnow()) -- so callers must pass `booked_at` as
    naive-UTC too. Past slots (earlier than "now") are dropped so a patient
    can never book a time that has already gone by."""
    now = datetime.utcnow()
    cursor = datetime(local_date.year, local_date.month, local_date.day, CLINIC_OPEN_HOUR, tzinfo=MALAYSIA_TZ)
    close = datetime(local_date.year, local_date.month, local_date.day, CLINIC_CLOSE_HOUR, tzinfo=MALAYSIA_TZ)
    slots = []
    while cursor < close:
        slot_utc = cursor.astimezone(timezone.utc).replace(tzinfo=None)
        if slot_utc > now and slot_utc not in booked_at:
            slots.append(slot_utc)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return slots


def compute_reminder_offsets(appointment: models.Appointment) -> list[dict]:
    """
    Returns a list of {"label": str, "hours_before": int, "fires_at": datetime}
    reminders for this appointment, computed (not stored) from its fields.

    Rules (see module docstring for why the concrete numbers live here and
    nowhere else):
      - Always: 24 hours before ("1 day before"), 3 hours before.
      - If fasting_required: an additional reminder at fasting_hours before
        the appointment, labelled to name the action ("Start fasting now"),
        not just the timing.
      - Any doctor-added extra_reminder_hours_before entries, each as their
        own reminder.

    Dropped/collapsed:
      - Any reminder whose fires_at has already passed (relative to
        datetime.utcnow()) is dropped entirely -- there's no point telling a
        client to display a reminder that should have already fired.
      - Duplicate hours_before values collapse to a SINGLE reminder. This
        matters because the three sources above (standard, fasting, doctor
        extra) are independent and can easily collide on the same number --
        e.g. fasting_hours=3 would otherwise produce both "3 hours before"
        and "Start fasting now" at the exact same fires_at, which reads as a
        confusing duplicate notification to the patient, not two distinct
        reminders. When two sources collide on the same hours_before, the
        MORE SPECIFIC/actionable label wins (fasting > doctor-added extra >
        generic standard), since "Start fasting now" carries information a
        bare "3 hours before" doesn't. THIS DE-DUP IS EASY TO SILENTLY BREAK
        in a future edit (e.g. adding a new reminder source that appends
        without checking existing hours_before first) -- if you add a new
        source, route it through the same collapsing dict keyed on
        hours_before, don't just list.append() a new entry.
    """
    now = datetime.utcnow()

    # hours_before -> label, built in priority order (later entries in this
    # function only overwrite an existing key if they're considered more
    # specific -- see the "more specific wins" note above). Using a dict
    # keyed on hours_before is what makes the de-dup automatic/hard to
    # accidentally break, rather than a list + a manual dedup pass after.
    offsets: dict[int, str] = {}

    # Standard reminders (lowest priority -- easily overwritten by a more
    # specific label at the same offset).
    for hours in STANDARD_REMINDER_HOURS_BEFORE:
        label = "1 day before" if hours == 24 else f"{hours} hours before"
        offsets[hours] = label

    # Doctor-added extra reminders (mid priority -- more specific than a
    # generic standard reminder since a clinician chose this offset
    # deliberately, but still just a timing nudge, not an action).
    if appointment.extra_reminder_hours_before:
        for hours in appointment.extra_reminder_hours_before:
            offsets[hours] = f"{hours} hours before"

    # Fasting reminder (highest priority -- names the action, not just the
    # timing, so it should win any collision with the sources above).
    if appointment.fasting_required and appointment.fasting_hours is not None:
        offsets[appointment.fasting_hours] = "Start fasting now"

    reminders = []
    for hours_before, label in offsets.items():
        fires_at = appointment.scheduled_at - timedelta(hours=hours_before)
        if fires_at <= now:
            # Already passed -- never surface a stale reminder.
            continue
        reminders.append({
            "label": label,
            "hours_before": hours_before,
            "fires_at": fires_at,
        })

    # Sort by fires_at ascending (earliest-firing reminder first) so a
    # client can display them in the order they'll actually occur without
    # needing to re-sort itself.
    reminders.sort(key=lambda r: r["fires_at"])
    return reminders
