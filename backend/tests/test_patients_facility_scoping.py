"""Security Audit finding H2 — GET /patients (list) had zero scoping
(db.query(Patient).all(), no facility filter, no pagination) and
GET /patients/{id} (detail) gave any staff full history for any patient
with no accountability trail. Covers the P2.2 fix in
app/routers/patients.py:
  - list_patients defaults to this user's facility's known patients,
    paginated, with an explicit + audited break_glass_reason override.
  - get_patient_full_record stays fully open (continuity-of-care /
    emergency-first design is not blocked) but now logs a DISTINCT,
    reviewable audit action when the caller's facility has no
    relationship to the patient.
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


def _give_encounter_at(db_session, patient, facility_name: str):
    encounter = models.Encounter(
        patient_id=patient.id, facility_name=facility_name, encounter_type="outpatient",
    )
    db_session.add(encounter)
    db_session.commit()
    return encounter


def test_list_patients_scoped_to_own_facility_by_default(test_client, make_user, auth_headers, db_session):
    clinician_a = make_user(role="clinician", facility="Facility A")
    known_patient = _make_patient(db_session, full_name="Known To A")
    _give_encounter_at(db_session, known_patient, "Facility A")
    unknown_patient = _make_patient(db_session, full_name="Only At B")
    _give_encounter_at(db_session, unknown_patient, "Facility B")

    resp = test_client.get("/patients", headers=auth_headers(clinician_a))
    assert resp.status_code == 200
    names = {p["full_name"] for p in resp.json()}
    assert "Known To A" in names
    assert "Only At B" not in names


def test_list_patients_empty_when_facility_has_no_known_patients(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Facility With Nobody")
    _make_patient(db_session)  # exists, but no relationship to this facility
    resp = test_client.get("/patients", headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_patients_pagination(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Facility Busy")
    for i in range(3):
        p = _make_patient(db_session, full_name=f"Patient {i}")
        _give_encounter_at(db_session, p, "Facility Busy")

    page1 = test_client.get("/patients?limit=2&skip=0", headers=auth_headers(clinician))
    assert page1.status_code == 200
    assert len(page1.json()) == 2

    page2 = test_client.get("/patients?limit=2&skip=2", headers=auth_headers(clinician))
    assert page2.status_code == 200
    assert len(page2.json()) == 1


def test_list_patients_break_glass_reason_unlocks_full_list_and_is_logged(
    test_client, make_user, auth_headers, db_session
):
    records_officer = make_user(role="records_officer", facility="Facility A")
    other_facility_patient = _make_patient(db_session, full_name="Elsewhere Patient")
    _give_encounter_at(db_session, other_facility_patient, "Facility B")

    scoped = test_client.get("/patients", headers=auth_headers(records_officer))
    assert "Elsewhere Patient" not in {p["full_name"] for p in scoped.json()}

    override = test_client.get(
        "/patients?break_glass_reason=Tracking+down+a+transferred+patient%27s+chart",
        headers=auth_headers(records_officer),
    )
    assert override.status_code == 200
    assert "Elsewhere Patient" in {p["full_name"] for p in override.json()}

    entry = (
        db_session.query(models.AuditLog)
        .filter_by(action="list_patients_break_glass")
        .order_by(models.AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.actor == records_officer.id
    assert "transferred patient" in entry.detail


def test_list_patients_blank_break_glass_reason_does_not_unlock(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Facility A")
    other_patient = _make_patient(db_session, full_name="Elsewhere Patient 2")
    _give_encounter_at(db_session, other_patient, "Facility B")

    resp = test_client.get("/patients?break_glass_reason=%20%20", headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert "Elsewhere Patient 2" not in {p["full_name"] for p in resp.json()}


def test_detail_view_stays_open_for_cross_facility_patient_but_is_logged_distinctly(
    test_client, make_user, auth_headers, db_session
):
    """Continuity-of-care / emergency-first: a walk-in patient's record
    must remain reachable even with no local relationship -- not blocked,
    but the audit trail must clearly flag it as cross-facility."""
    clinician_a = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session, full_name="Cross Facility Patient")
    _give_encounter_at(db_session, patient, "Facility B")

    resp = test_client.get(f"/patients/{patient.id}", headers=auth_headers(clinician_a))
    assert resp.status_code == 200, resp.text  # NOT blocked

    entry = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient.id, action="view_full_record_cross_facility")
        .first()
    )
    assert entry is not None
    assert entry.actor_facility == "Facility A"


def test_detail_view_logged_as_plain_local_view_when_known_to_facility(
    test_client, make_user, auth_headers, db_session
):
    clinician_a = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session, full_name="Local Patient")
    _give_encounter_at(db_session, patient, "Facility A")

    resp = test_client.get(f"/patients/{patient.id}", headers=auth_headers(clinician_a))
    assert resp.status_code == 200

    plain_entry = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient.id, action="view_full_record")
        .first()
    )
    assert plain_entry is not None
    cross_entry = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient.id, action="view_full_record_cross_facility")
        .first()
    )
    assert cross_entry is None


def test_patient_viewing_own_record_never_flagged_cross_facility(test_client, make_user, auth_headers, db_session):
    patient_row = _make_patient(db_session, full_name="Self Viewer")
    _give_encounter_at(db_session, patient_row, "Some Other Facility")  # patient has no .facility of their own
    patient_user = make_user(role="patient", patient_id=patient_row.id)

    resp = test_client.get(f"/patients/{patient_row.id}", headers=auth_headers(patient_user))
    assert resp.status_code == 200

    cross_entry = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient_row.id, action="view_full_record_cross_facility")
        .first()
    )
    assert cross_entry is None
