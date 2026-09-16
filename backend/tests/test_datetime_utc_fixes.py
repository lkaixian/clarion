"""Regression coverage for the two pre-existing naive/aware datetime issues
surfaced (not caused) by the 2026-09-16 datetime.utcnow() deprecation sweep,
and fixed directly after -- see healthcare/Implementation Roadmap.md's
changelog for that entry.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import auth, schemas


def test_epoch_utc_matches_for_naive_and_aware_equivalents():
    """auth._epoch_utc must treat a naive-UTC value the same as its
    aware-UTC equivalent -- plain .timestamp() on a naive datetime reads it
    as LOCAL time instead, which would diverge from this on any machine not
    running in the UTC timezone."""
    naive = datetime(2026, 6, 15, 12, 0, 0)
    aware = naive.replace(tzinfo=timezone.utc)
    assert auth._epoch_utc(naive) == auth._epoch_utc(aware)
    # And it must be the real UTC epoch, not a locally-shifted one.
    assert auth._epoch_utc(naive) == aware.timestamp()


def test_appointment_not_in_past_validator_accepts_offset_bearing_future_datetime():
    """A client sending an ISO datetime WITH a timezone offset (e.g.
    '+08:00') used to raise TypeError (naive-vs-aware compare) instead of
    validating cleanly."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(
        timezone(timedelta(hours=8))
    )
    appt = schemas.AppointmentCreate(facility_name="Facility A", scheduled_at=future)
    assert appt.scheduled_at == future


def test_appointment_not_in_past_validator_rejects_offset_bearing_past_datetime_cleanly():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).astimezone(
        timezone(timedelta(hours=8))
    )
    with pytest.raises(ValidationError, match="cannot be in the past"):
        schemas.AppointmentCreate(facility_name="Facility A", scheduled_at=past)


def test_reschedule_not_in_past_validator_rejects_offset_bearing_past_datetime_cleanly():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).astimezone(
        timezone(timedelta(hours=8))
    )
    with pytest.raises(ValidationError, match="cannot be in the past"):
        schemas.RescheduleAppointmentRequest(new_scheduled_at=past, reason_code="patient_requested")
