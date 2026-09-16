"""Security Audit finding H1 — emergency card endpoints previously bypassed
the role/page-permission model entirely (any authenticated staff role,
including pharmacist/receptionist, could issue/revoke/view any patient's
emergency card, with no facility scoping). Covers the fix in
app/routers/emergency.py: require_page_access("patients") on
issue/revoke/current-status/list_nfc, plus a facility-presence check for
staff callers (_require_patient_present_for_staff).

Deliberately does NOT touch POST /emergency/scan or /emergency/nfc/scan --
those stay intentionally public/unauthenticated (the life-safety
break-glass design), out of scope for H1.
"""
from app import models


def _make_patient(db_session, **overrides):
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Test Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _make_ward(db_session, facility_name: str):
    ward = models.Ward(facility_name=facility_name, ward_name="General", total_beds=10)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    return ward


def _admit(db_session, patient, facility_name: str, ward, bed_number: int = 1):
    admission = models.Admission(
        facility_name=facility_name, patient_id=patient.id, ward_id=ward.id, bed_number=bed_number,
    )
    db_session.add(admission)
    db_session.commit()
    return admission


def test_pharmacist_blocked_from_issuing_card(test_client, make_user, auth_headers, db_session):
    """Pharmacist's default page set is ["pharmacy"] only -- require_page_access("patients") must block."""
    pharmacist = make_user(role="pharmacist", facility="Main Hospital")
    patient = _make_patient(db_session)
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(pharmacist), json={"patient_id": patient.id}
    )
    assert resp.status_code == 403


def test_receptionist_blocked_from_viewing_card_status(test_client, make_user, auth_headers, db_session):
    receptionist = make_user(role="receptionist", facility="Main Hospital")
    patient = _make_patient(db_session)
    resp = test_client.get(f"/emergency/current/{patient.id}", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_receptionist_blocked_from_listing_nfc_cards(test_client, make_user, auth_headers, db_session):
    receptionist = make_user(role="receptionist", facility="Main Hospital")
    patient = _make_patient(db_session)
    resp = test_client.get(f"/emergency/nfc/{patient.id}", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_clinician_blocked_when_patient_not_present_at_own_facility(test_client, make_user, auth_headers, db_session):
    """Facility scoping: a clinician with patients-page access is still
    blocked if the patient isn't currently checked in at THEIR facility --
    no admission, no open queue ticket."""
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    )
    assert resp.status_code == 403
    assert "not currently checked in" in resp.json()["detail"]


def test_admin_also_blocked_when_patient_not_present_no_override(test_client, make_user, auth_headers, db_session):
    """No admin override -- matches _guard_cross_facility_amend's own
    precedent in patients.py (need-to-know, not role seniority)."""
    admin = make_user(role="admin", facility="Facility A")
    patient = _make_patient(db_session)
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(admin), json={"patient_id": patient.id}
    )
    assert resp.status_code == 403


def test_clinician_allowed_when_patient_present_at_own_facility(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    ward = _make_ward(db_session, "Facility A")
    _admit(db_session, patient, "Facility A", ward)

    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["card_reference"]


def test_patient_self_service_unaffected_by_facility_check(test_client, make_user, auth_headers, db_session):
    """A patient issuing their OWN card is unaffected by facility presence
    -- this is meant to work from home via the mobile app, not just
    while checked in somewhere."""
    patient_row = _make_patient(db_session)
    patient_user = make_user(role="patient", patient_id=patient_row.id)
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(patient_user), json={"patient_id": patient_row.id}
    )
    assert resp.status_code == 200, resp.text


def test_patient_cannot_issue_for_another_patient(test_client, make_user, auth_headers, db_session):
    patient_row = _make_patient(db_session)
    other_patient_row = _make_patient(db_session, full_name="Other Patient")
    patient_user = make_user(role="patient", patient_id=patient_row.id)
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(patient_user), json={"patient_id": other_patient_row.id}
    )
    assert resp.status_code == 403


def test_revoke_and_status_also_facility_scoped(test_client, make_user, auth_headers, db_session):
    """Issue while present, then simulate the patient having left (no more
    admission) -- revoke and status-check must now be blocked for staff."""
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    ward = _make_ward(db_session, "Facility A")
    admission = _admit(db_session, patient, "Facility A", ward)

    issued = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    )
    assert issued.status_code == 200
    card_reference = issued.json()["card_reference"]

    # Patient discharged -- no longer "present" at Facility A.
    from datetime import datetime, timezone
    db_session.query(models.Admission).filter_by(id=admission.id).update({"discharged_at": datetime.now(timezone.utc).replace(tzinfo=None)})
    db_session.commit()

    status_resp = test_client.get(f"/emergency/current/{patient.id}", headers=auth_headers(clinician))
    assert status_resp.status_code == 403

    revoke_resp = test_client.post(
        f"/emergency/revoke/{card_reference}", headers=auth_headers(clinician)
    )
    assert revoke_resp.status_code == 403
