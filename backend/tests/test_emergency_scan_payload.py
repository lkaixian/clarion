"""Security Audit M7b -- the unauthenticated emergency scan returns the
patient's AGE, not their full date of birth. Age covers the clinical need
(dose/weight banding, "is this a child") without handing an anonymous
caller an exact birthdate.
"""
from datetime import date

from app import models
from app.routers.emergency import _age_from_dob


def _patient(db_session, dob):
    p = models.Patient(full_name="M7b Patient", date_of_birth=dob)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _present(db_session, patient):
    ward = models.Ward(facility_name="P1", ward_name="W", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(
        facility_name="P1", patient_id=patient.id, ward_id=ward.id, bed_number=1,
    ))
    db_session.commit()


def test_age_from_dob_math():
    ref = date(2026, 6, 15)  # fixed "today" -> deterministic boundaries
    assert _age_from_dob("1996-06-14", today=ref) == 30  # birthday was yesterday
    assert _age_from_dob("1996-06-15", today=ref) == 30  # birthday is today
    assert _age_from_dob("1996-06-16", today=ref) == 29  # birthday is tomorrow -> not yet
    assert _age_from_dob("2004-02-29", today=date(2026, 2, 28)) == 21  # leap DOB, day before
    assert _age_from_dob("2004-02-29", today=date(2026, 3, 1)) == 22
    assert _age_from_dob(None) is None
    assert _age_from_dob("") is None
    assert _age_from_dob("not-a-date") is None
    assert _age_from_dob("1990-05-14T00:00:00", today=ref) == _age_from_dob("1990-05-14", today=ref)
    assert _age_from_dob("2031-01-01", today=ref) is None  # future DOB -> no negative age
    assert _age_from_dob("1850-01-01", today=ref) is None  # garbage -> not 176


def test_scan_returns_age_not_dob(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="P1")
    patient = _patient(db_session, "1975-06-01")
    _present(db_session, patient)

    issued = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    )
    assert issued.status_code == 200, issued.text
    card_ref = issued.json()["card_reference"]

    body = test_client.post("/emergency/scan", json={"card_reference": card_ref}).json()
    assert "date_of_birth" not in body
    assert "age" in body
    assert body["age"] == _age_from_dob("1975-06-01")
    assert body["full_name"] == "M7b Patient"  # name kept for on-scene identity


def test_scan_age_null_for_missing_dob(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="P1")
    patient = _patient(db_session, "")  # older record, no DOB on file
    _present(db_session, patient)
    card_ref = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    ).json()["card_reference"]

    body = test_client.post("/emergency/scan", json={"card_reference": card_ref}).json()
    assert body["age"] is None
