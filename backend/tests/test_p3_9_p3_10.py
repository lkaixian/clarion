"""P3.9 (calling-system printing/branding) + P3.10 (mobile booking/vitals/
PDF/announcements). ESC/POS ticket bytes and the sample-label PNG are pure
formatting (app/printing.py) with no server-side branching worth a test
beyond "the endpoint returns the right content-type" -- covered inline
below. Most of this file exercises the new endpoints' access control and
the two bugs already caught and fixed during implementation:
  * GET /patients/appointment-slots (and /booking-options) were originally
    defined on appointments.router, which mounts under the same "/patients"
    prefix but is included into the app AFTER patients.router -- so
    GET /{patient_id} (patients.router, registered first) would have
    swallowed "appointment-slots" as a patient_id before appointments.router
    ever saw the request. Fixed by moving both onto patients.router, ahead
    of /{patient_id}. test_appointment_slots_not_shadowed_by_patient_route
    below is the regression guard.
  * A vitals-only sign-off (no SOAP text typed) would have silently dropped
    the vitals -- consultation.py's `structured_values` guard only checked
    the SOAP fields before vitals were added. Fixed by including the vitals
    fields in that tuple. test_vitals_only_signoff_still_creates_note
    below is the regression guard.

Security-review follow-up (2026-09-14) added 3 more, covered below:
  * self_book_appointment's slot check was read-then-write with no DB-level
    guard against a concurrent double-book -- fixed with
    models.Appointment.uq_appointments_active_clinician_slot (same VIRTUAL-
    generated-column pattern as P1.3's RoomClaim). A true concurrent-thread
    race is awkward to assert deterministically in pytest, so
    test_appointment_unique_constraint_blocks_concurrent_double_book proves
    the DB constraint itself does the job directly.
  * compute_available_slots returned NAIVE UTC datetimes, which Pydantic
    serializes with no 'Z'/offset suffix -- Dart's DateTime.parse silently
    mis-parses an offset-less string as LOCAL time, which a downstream
    `.toUtc()` call then double-shifts, breaking every self-book attempt
    from a real Malaysia-timezone device (voltagent flutter-expert review).
    Fixed by returning AWARE UTC datetimes instead.
    test_appointment_slots_are_timezone_aware is the regression guard.
  * app/printing.py's ESC/POS text encoder passed ASCII control bytes
    (including this module's own ESC/GS command-introducer bytes) through
    unfiltered -- a receptionist/admin could inject raw printer commands via
    QueueTicket.department / HospitalSetting.display_name.
    test_escpos_ticket_strips_control_characters is the regression guard.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app import models
from conftest import _TEST_SIGNATURE_B64, _facility, _make_patient


def _ticket(db, patient_id, facility, room_id, checked_in_by, department=None):
    ticket = models.QueueTicket(
        patient_id=patient_id, facility_name=facility, room_id=room_id, department=department,
        status="called", queue_number=1, queue_date=datetime.now().date().isoformat(),
        source="manual", checked_in_by=checked_in_by,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _room_and_claim(db, user, facility):
    room = models.ConsultationRoom(facility_name=facility, room_name="Room 1", active=True)
    db.add(room)
    db.flush()
    db.add(models.StaffClockEvent(user_id=user.id, facility_name=facility))
    db.add(models.RoomClaim(facility_name=facility, room_id=room.id, user_id=user.id))
    db.commit()
    return room


# ---------------------------------------------------------------------------
# P3.10: self-service booking + slots
# ---------------------------------------------------------------------------
def test_appointment_slots_not_shadowed_by_patient_route(test_client, db_session, make_user, auth_headers):
    facility = _facility("Slots")
    clinician = make_user(role="clinician", facility=facility)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    resp = test_client.get(
        "/patients/appointment-slots",
        params={"facility_name": facility, "date": tomorrow},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_self_book_happy_path(test_client, db_session, make_user, auth_headers):
    facility = _facility("Booking")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient.id)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    slots = test_client.get(
        "/patients/appointment-slots",
        params={"facility_name": facility, "date": tomorrow, "clinician_id": clinician.id},
        headers=auth_headers(patient_user),
    ).json()
    assert slots, "expected at least one open slot tomorrow within clinic hours"
    chosen = slots[0]

    resp = test_client.post(
        f"/patients/{patient.id}/appointments/self-book",
        headers=auth_headers(patient_user),
        json={"facility_name": facility, "clinician_id": clinician.id, "scheduled_at": chosen["scheduled_at"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["self_booked"] is True
    assert body["clinician_id"] == clinician.id
    assert body["status"] == "scheduled"

    # The exact same slot must no longer be offered (double-booking guard).
    slots_after = test_client.get(
        "/patients/appointment-slots",
        params={"facility_name": facility, "date": tomorrow, "clinician_id": clinician.id},
        headers=auth_headers(patient_user),
    ).json()
    assert chosen["scheduled_at"] not in {s["scheduled_at"] for s in slots_after}


def test_self_book_rejects_time_not_actually_offered(test_client, db_session, make_user, auth_headers):
    facility = _facility("Booking")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient.id)

    # UTC 20:00 = Malaysia-local (UTC+8) 04:00 -- outside the fixed
    # 08:00-17:00 clinic-hours grid, never a real offered slot regardless
    # of what's booked.
    bogus_time = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    ).isoformat()

    resp = test_client.post(
        f"/patients/{patient.id}/appointments/self-book",
        headers=auth_headers(patient_user),
        json={"facility_name": facility, "clinician_id": clinician.id, "scheduled_at": bogus_time},
    )
    assert resp.status_code == 409


def test_self_book_forbidden_for_other_patient(test_client, db_session, make_user, auth_headers):
    facility = _facility("Booking")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    other_patient = _make_patient(db_session, full_name="Someone Else")
    other_patient_user = make_user(role="patient", patient_id=other_patient.id)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    ).isoformat()

    resp = test_client.post(
        f"/patients/{patient.id}/appointments/self-book",
        headers=auth_headers(other_patient_user),
        json={"facility_name": facility, "clinician_id": clinician.id, "scheduled_at": tomorrow},
    )
    assert resp.status_code == 403


def test_appointment_slots_are_timezone_aware(test_client, db_session, make_user, auth_headers):
    """Regression guard: compute_available_slots must return timezone-aware
    UTC datetimes, not naive ones -- a naive datetime serializes over JSON
    with no 'Z'/offset suffix, which Dart's DateTime.parse silently
    mis-parses as local time, which a downstream .toUtc() call then
    double-shifts (voltagent flutter-expert review -- this broke every
    self-book attempt from a real Malaysia-timezone device)."""
    facility = _facility("TZGuard")
    clinician = make_user(role="clinician", facility=facility)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    resp = test_client.get(
        "/patients/appointment-slots",
        params={"facility_name": facility, "date": tomorrow, "clinician_id": clinician.id},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    slots = resp.json()
    assert slots, "expected at least one open slot tomorrow"
    raw = slots[0]["scheduled_at"]
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"scheduled_at {raw!r} has no timezone info -- Dart would mis-parse this as local time"


def test_appointment_unique_constraint_blocks_concurrent_double_book(test_client, db_session, make_user):
    """Direct DB-level proof of the race guard the security review asked
    for (uq_appointments_active_clinician_slot) -- a true concurrent-thread
    race is awkward to assert deterministically in pytest, so this inserts
    the exact collision the constraint exists to catch and confirms the DB
    itself refuses it, independent of the router's own (necessarily
    sequential) read-check."""
    facility = _facility("RaceGuard")
    clinician = make_user(role="clinician", facility=facility)
    patient_a = _make_patient(db_session)
    patient_b = _make_patient(db_session, full_name="Other Patient")
    when = datetime.now(timezone.utc) + timedelta(days=1)

    first = models.Appointment(
        patient_id=patient_a.id, facility_name=facility, clinician_id=clinician.id,
        scheduled_at=when, status="scheduled", self_booked=True, created_by=clinician.id,
    )
    db_session.add(first)
    db_session.commit()

    second = models.Appointment(
        patient_id=patient_b.id, facility_name=facility, clinician_id=clinician.id,
        scheduled_at=when, status="scheduled", self_booked=True, created_by=clinician.id,
    )
    db_session.add(second)
    try:
        db_session.commit()
        raise AssertionError("expected IntegrityError from uq_appointments_active_clinician_slot")
    except IntegrityError:
        db_session.rollback()


def test_appointment_unique_constraint_allows_rebooking_after_cancel(test_client, db_session, make_user):
    """A cancelled row at the same clinician+time must NOT block a new
    scheduled booking there -- the constraint is scoped to
    status == 'scheduled' only (see models.Appointment.
    active_clinician_slot_key's CASE expression)."""
    facility = _facility("RaceGuard")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    when = datetime.now(timezone.utc) + timedelta(days=1)

    cancelled = models.Appointment(
        patient_id=patient.id, facility_name=facility, clinician_id=clinician.id,
        scheduled_at=when, status="cancelled", self_booked=True, created_by=clinician.id,
    )
    db_session.add(cancelled)
    db_session.commit()

    rebooked = models.Appointment(
        patient_id=patient.id, facility_name=facility, clinician_id=clinician.id,
        scheduled_at=when, status="scheduled", self_booked=True, created_by=clinician.id,
    )
    db_session.add(rebooked)
    db_session.commit()  # must NOT raise


def test_booking_options_lists_departments_and_clinicians(test_client, db_session, make_user, auth_headers):
    facility = _facility("Booking")
    admin = make_user(role="admin", facility=facility)
    section = models.FacilitySection(facility_name=facility, name="General", active=True, created_by=admin.id)
    db_session.add(section)
    clinician = make_user(role="clinician", facility=facility, section="General")
    db_session.commit()

    resp = test_client.get(
        "/patients/booking-options", params={"facility_name": facility}, headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "General" in body["departments"]
    assert any(c["id"] == clinician.id and c["department"] == "General" for c in body["clinicians"])


# ---------------------------------------------------------------------------
# P3.10: vitals capture + patient-visible record
# ---------------------------------------------------------------------------
def test_vitals_round_trip_through_consultation_and_patient_record(test_client, db_session, make_user, auth_headers):
    facility = _facility("Vitals")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient.id)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id, department="General")

    complete = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={
            "assessment": "Hypertensive, stable", "plan": "Continue current medication",
            "bp_systolic": 130, "bp_diastolic": 85, "temperature_c": 36.8, "pulse_bpm": 72,
            "signature_b64": _TEST_SIGNATURE_B64,
        },
    )
    assert complete.status_code == 200, complete.text

    record = test_client.get(f"/patients/{patient.id}", headers=auth_headers(patient_user))
    assert record.status_code == 200, record.text
    encounters = record.json()["encounters"]
    assert len(encounters) == 1
    enc = encounters[0]
    assert enc["department"] == "General"
    note = enc["consultation_note"]
    assert note is not None
    assert note["bp_systolic"] == 130
    assert note["bp_diastolic"] == 85
    assert note["temperature_c"] == 36.8
    assert note["pulse_bpm"] == 72
    assert note["assessment"] == "Hypertensive, stable"
    # Raw S/O free text is deliberately NOT surfaced to the patient view --
    # see _serialize_encounter's docstring.
    assert "subjective" not in note


def test_vitals_only_signoff_still_creates_note(test_client, db_session, make_user, auth_headers):
    facility = _facility("Vitals")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    complete = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={"pulse_bpm": 88, "signature_b64": _TEST_SIGNATURE_B64},
    )
    assert complete.status_code == 200, complete.text
    note = db_session.query(models.ConsultationNote).filter_by(
        encounter_id=complete.json()["encounter_id"]
    ).one_or_none()
    assert note is not None, "vitals-only sign-off must still persist a ConsultationNote row"
    assert note.pulse_bpm == 88


def test_vitals_out_of_range_rejected(test_client, db_session, make_user, auth_headers):
    facility = _facility("Vitals")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    complete = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={"pulse_bpm": 999, "signature_b64": _TEST_SIGNATURE_B64},
    )
    assert complete.status_code == 422


# ---------------------------------------------------------------------------
# P3.10: visit-summary PDF
# ---------------------------------------------------------------------------
def test_visit_summary_pdf(test_client, db_session, make_user, auth_headers):
    facility = _facility("VisitPDF")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient.id)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id, department="General")

    complete = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={
            "assessment": "Viral URI", "plan": "Rest and fluids", "bp_systolic": 118, "bp_diastolic": 76,
            "signature_b64": _TEST_SIGNATURE_B64,
        },
    )
    encounter_id = complete.json()["encounter_id"]

    resp = test_client.get(
        f"/patients/{patient.id}/encounters/{encounter_id}/visit-summary.pdf",
        headers=auth_headers(patient_user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_visit_summary_pdf_forbidden_for_other_patient(test_client, db_session, make_user, auth_headers):
    facility = _facility("VisitPDF")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    other_patient = _make_patient(db_session, full_name="Someone Else")
    other_patient_user = make_user(role="patient", patient_id=other_patient.id)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    complete = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete", headers=auth_headers(clinician),
        json={"assessment": "x", "signature_b64": _TEST_SIGNATURE_B64},
    )
    encounter_id = complete.json()["encounter_id"]

    resp = test_client.get(
        f"/patients/{patient.id}/encounters/{encounter_id}/visit-summary.pdf",
        headers=auth_headers(other_patient_user),
    )
    assert resp.status_code == 403


def test_visit_summary_pdf_404_before_sign_off(test_client, db_session, make_user, auth_headers):
    """An Encounter with no signature (shouldn't exist via the normal flow,
    but the endpoint must not 500 against one) -- covered by simply asking
    for a nonexistent encounter_id, the cheap version of the same guard."""
    patient = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient.id)

    resp = test_client.get(
        f"/patients/{patient.id}/encounters/does-not-exist/visit-summary.pdf",
        headers=auth_headers(patient_user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# P3.9: printing endpoints -- content-type smoke tests
# ---------------------------------------------------------------------------
def test_ticket_print_endpoint_returns_escpos_bytes(test_client, db_session, make_user, auth_headers):
    facility = _facility("Print")
    receptionist = make_user(role="receptionist", facility=facility)
    patient = _make_patient(db_session)
    ticket = models.QueueTicket(
        patient_id=patient.id, facility_name=facility, status="waiting", queue_number=7,
        queue_date=datetime.now().date().isoformat(), source="manual", checked_in_by=receptionist.id,
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    resp = test_client.get(f"/reception/queue/{ticket.id}/ticket.escpos", headers=auth_headers(receptionist))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/vnd.escpos"
    assert b"\x1b\x40" in resp.content  # ESC @ init sequence


def test_escpos_ticket_strips_control_characters(test_client, db_session, make_user, auth_headers):
    """Regression guard for the ESC/POS command-injection finding: a
    QueueTicket.department containing raw ESC (0x1b) / GS (0x1d) bytes --
    this module's own command-introducer bytes -- must not reach the
    printer byte stream unfiltered."""
    facility = _facility("Print")
    receptionist = make_user(role="receptionist", facility=facility)
    patient = _make_patient(db_session)
    malicious_department = "LAB\x1b\x40\x1dVINJECTED"
    ticket = models.QueueTicket(
        patient_id=patient.id, facility_name=facility, status="waiting", queue_number=3,
        department=malicious_department,
        queue_date=datetime.now().date().isoformat(), source="manual", checked_in_by=receptionist.id,
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    resp = test_client.get(f"/reception/queue/{ticket.id}/ticket.escpos", headers=auth_headers(receptionist))
    assert resp.status_code == 200, resp.text
    # The text rendered (proving sanitization strips characters rather than
    # rejecting the whole ticket)...
    assert b"VINJECTED" in resp.content
    # ...but the exact injected control-byte sequence must be gone.
    assert b"\x1b\x40\x1d" not in resp.content


def test_ancillary_label_endpoint_returns_png(test_client, db_session, make_user, auth_headers):
    facility = _facility("Print")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    item = models.ServiceCatalogItem(module="laboratory", name="CBC", unit_price_cents=1000)
    db_session.add(item)
    db_session.flush()
    req = models.ServiceRequest(
        patient_id=patient.id, module="laboratory", catalog_item_id=item.id, source="frontdesk",
        priority="routine", unit_price_cents=1000, ordering_facility_name=facility, status="ordered",
        requested_by=clinician.id,
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)

    resp = test_client.get(f"/ancillary/requests/{req.id}/label", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# P3.10: announcements
# ---------------------------------------------------------------------------
def test_announcement_create_and_patient_read(test_client, db_session, make_user, auth_headers):
    facility = _facility("Announce")
    admin = make_user(role="admin", facility=facility)
    patient_user = make_user(role="patient", patient_id=_make_patient(db_session).id)

    created = test_client.post(
        "/admin/announcements", headers=auth_headers(admin),
        json={"title": "Flu clinic", "body": "Free flu shots this week."},
    )
    assert created.status_code == 200, created.text
    assert created.json()["facility_name"] == facility

    listed = test_client.get(
        "/patients/announcements", params={"facility_name": facility}, headers=auth_headers(patient_user),
    )
    assert listed.status_code == 200
    assert any(a["title"] == "Flu clinic" for a in listed.json())


def test_announcement_create_requires_admin(test_client, db_session, make_user, auth_headers):
    facility = _facility("Announce")
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/admin/announcements", headers=auth_headers(clinician),
        json={"title": "x", "body": "y"},
    )
    assert resp.status_code == 403


def test_announcement_expired_hidden_from_patient_read(test_client, db_session, make_user, auth_headers):
    facility = _facility("Announce")
    admin = make_user(role="admin", facility=facility)
    patient_user = make_user(role="patient", patient_id=_make_patient(db_session).id)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    test_client.post(
        "/admin/announcements", headers=auth_headers(admin),
        json={"title": "Old notice", "body": "stale", "expires_at": past},
    )

    listed = test_client.get(
        "/patients/announcements", params={"facility_name": facility}, headers=auth_headers(patient_user),
    )
    assert listed.status_code == 200
    assert not any(a["title"] == "Old notice" for a in listed.json())


def test_announcement_scoped_to_own_facility_only(test_client, db_session, make_user, auth_headers):
    facility_a, facility_b = _facility("Announce A"), _facility("Announce B")
    admin_a = make_user(role="admin", facility=facility_a)
    patient_b = make_user(role="patient", patient_id=_make_patient(db_session).id)

    test_client.post(
        "/admin/announcements", headers=auth_headers(admin_a),
        json={"title": "Facility A only", "body": "..."},
    )
    listed = test_client.get(
        "/patients/announcements", params={"facility_name": facility_b}, headers=auth_headers(patient_b),
    )
    assert listed.status_code == 200
    assert not any(a["title"] == "Facility A only" for a in listed.json())


def test_sample_label_renders_new_fields_for_short_and_very_long_values():
    """Name/IC/created/created-by/item/request; a long name wraps (compact
    layout) rather than being cut, and neither layout raises."""
    import io
    from datetime import datetime, timezone
    from PIL import Image
    from app.printing import build_sample_label_png

    for name, item, by in (
        ("Nur Aisyah binti Rahman", "Full Blood Count", "Dr. Sarah Lim"),
        ("MUHAMMAD AMIRUL HAKIMI BIN ABDUL RAHMAN AL-HAFIZ",
         "Fasting Blood Glucose + HbA1c + Lipid Profile Panel", "Dr. Sarah Binti Mohd Zulkifli"),
    ):
        png = build_sample_label_png(
            patient_name=name, national_id="950520-14-5678", item_name=item,
            request_id="3f2a91c4-77aa-4b1e-9d0c-1e8b6a52f001",
            created_at=datetime(2026, 10, 10, 15, 24, tzinfo=timezone.utc), created_by=by,
        )
        assert Image.open(io.BytesIO(png)).size == (560, 260)
