"""Code-review follow-up 2026-09-07 -- GET /patients/{id}/appointments previously accepted
ANY authenticated non-patient token: unscoped, and with no cross-facility
distinction in the audit log. A pharmacist / receptionist could read any
patient's appointment reason / precaution_notes / fasting instructions at any
facility.

Covers the fix:
  * app/main.py mounts appointments.router under
    require_page_access("patients") -- a pharmacist/receptionist without that
    page is blocked at router level.
  * list_appointments restricts staff to admin / clinician / records_officer
    (the same set that can create/modify an appointment); the patient may
    still read their OWN record.
  * a staff read whose facility has no relationship to the patient is logged
    as `view_appointments_cross_facility`, not plain `view_appointments`.
"""
from datetime import datetime, timedelta

from app import models


def _make_patient(db_session, **overrides):
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Appt Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _make_creator(db_session):
    """An author for the Appointment.created_by NOT NULL column -- who
    created it is irrelevant to what these tests check (who can READ it)."""
    from app import auth as auth_module

    user = models.User(
        email=f"appt-creator-{datetime.utcnow().timestamp()}@example.com",
        hashed_password=auth_module.hash_password("TestPass123!"),
        full_name="Appt Creator",
        role="clinician",
        facility="Facility A",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_appointment(db_session, patient, facility="Facility A"):
    appt = models.Appointment(
        patient_id=patient.id,
        facility_name=facility,
        scheduled_at=datetime.utcnow() + timedelta(days=3),
        reason="Cardiology follow-up",
        created_by=_make_creator(db_session).id,
    )
    db_session.add(appt)
    db_session.commit()
    db_session.refresh(appt)
    return appt


def _latest_action(db_session, patient_id):
    row = (
        db_session.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id)
        .order_by(models.AuditLog.id.desc())
        .first()
    )
    return row.action if row else None


def test_pharmacist_blocked_by_page_gate(test_client, make_user, auth_headers, db_session):
    pharmacist = make_user(role="pharmacist", facility="Facility A")
    patient = _make_patient(db_session)
    _make_appointment(db_session, patient)
    resp = test_client.get(
        f"/patients/{patient.id}/appointments", headers=auth_headers(pharmacist)
    )
    assert resp.status_code == 403


def test_receptionist_blocked(test_client, make_user, auth_headers, db_session):
    """Receptionist may hold the `patients` page for check-in, but is still
    excluded from the clinical appointment detail by the role check in
    list_appointments."""
    receptionist = make_user(role="receptionist", facility="Facility A")
    # Grant the receptionist the patients page so the router gate passes and
    # we're testing the endpoint's own role check, not require_page_access.
    db_session.add(models.RolePagePermission(
        facility_name="Facility A", role="receptionist", allowed_pages=["patients", "reception"],
    ))
    db_session.commit()
    patient = _make_patient(db_session)
    _make_appointment(db_session, patient)
    resp = test_client.get(
        f"/patients/{patient.id}/appointments", headers=auth_headers(receptionist)
    )
    assert resp.status_code == 403


def test_clinician_can_read(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    _make_appointment(db_session, patient, facility="Facility A")
    resp = test_client.get(
        f"/patients/{patient.id}/appointments", headers=auth_headers(clinician)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["reason"] == "Cardiology follow-up"


def test_patient_can_read_own_appointments(test_client, make_user, auth_headers, db_session):
    patient_row = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient_row.id)
    _make_appointment(db_session, patient_row)
    resp = test_client.get(
        f"/patients/{patient_row.id}/appointments", headers=auth_headers(patient_user)
    )
    assert resp.status_code == 200, resp.text


def test_patient_cannot_read_another_patients_appointments(test_client, make_user, auth_headers, db_session):
    patient_row = _make_patient(db_session)
    other = _make_patient(db_session, full_name="Other")
    patient_user = make_user(role="patient", patient_id=patient_row.id)
    resp = test_client.get(
        f"/patients/{other.id}/appointments", headers=auth_headers(patient_user)
    )
    assert resp.status_code == 403


def test_cross_facility_read_is_audited_distinctly(test_client, make_user, auth_headers, db_session):
    """A records_officer at Facility B reading a patient known only to
    Facility A gets logged as view_appointments_cross_facility."""
    officer = make_user(role="records_officer", facility="Facility B")
    patient = _make_patient(db_session)
    _make_appointment(db_session, patient, facility="Facility A")

    resp = test_client.get(
        f"/patients/{patient.id}/appointments", headers=auth_headers(officer)
    )
    assert resp.status_code == 200, resp.text
    assert _latest_action(db_session, patient.id) == "view_appointments_cross_facility"


def test_same_facility_read_is_plain_audit_action(test_client, make_user, auth_headers, db_session):
    officer = make_user(role="records_officer", facility="Facility A")
    patient = _make_patient(db_session)
    _make_appointment(db_session, patient, facility="Facility A")

    resp = test_client.get(
        f"/patients/{patient.id}/appointments", headers=auth_headers(officer)
    )
    assert resp.status_code == 200, resp.text
    assert _latest_action(db_session, patient.id) == "view_appointments"
