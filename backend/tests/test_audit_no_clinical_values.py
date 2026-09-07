"""Security Audit M8 -- clinical data must not be written into
`audit_logs.detail`.

`patients.py`'s add_condition / add_medication / add_allergy / add_encounter
used to log the diagnosis name / drug name / allergen substance / a payload
free-text field verbatim into the audit `detail` column, turning the audit
store into a second, less-controlled copy of clinical data. They now log the
new row's id instead -- same as the update_* endpoints already did.
"""
from app import models


def _make_patient(db_session, **overrides):
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Audit M8 Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _audit_details(db_session, patient_id, action):
    return [
        row.detail
        for row in db_session.query(models.AuditLog)
        .filter_by(patient_id=patient_id, action=action)
        .all()
    ]


def test_add_condition_logs_row_id_not_diagnosis(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/patients/{patient.id}/conditions",
        headers=auth_headers(clinician),
        json={"name": "Carcinoma of the left breast"},
    )
    assert resp.status_code == 200, resp.text

    condition = db_session.query(models.Condition).filter_by(patient_id=patient.id).first()
    details = _audit_details(db_session, patient.id, "add_condition")
    assert details == [condition.id]
    assert "Carcinoma of the left breast" not in details


def test_add_medication_logs_row_id_not_drug_name(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/patients/{patient.id}/medications",
        headers=auth_headers(clinician),
        json={"drug_name": "Methadone 40mg"},
    )
    assert resp.status_code == 200, resp.text

    med = db_session.query(models.MedicationStatement).filter_by(patient_id=patient.id).first()
    details = _audit_details(db_session, patient.id, "add_medication")
    assert details == [med.id]
    assert "Methadone 40mg" not in details


def test_add_allergy_logs_row_id_not_substance(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/patients/{patient.id}/allergies",
        headers=auth_headers(clinician),
        json={"substance": "Penicillin", "severity": "severe"},
    )
    assert resp.status_code == 200, resp.text

    allergy = db_session.query(models.AllergyIntolerance).filter_by(patient_id=patient.id).first()
    details = _audit_details(db_session, patient.id, "add_allergy")
    assert details == [allergy.id]
    assert "Penicillin" not in details


def test_add_encounter_logs_row_id(test_client, db_session, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/patients/{patient.id}/encounters",
        headers=auth_headers(clinician),
        json={"facility_name": "Facility A", "encounter_type": "inpatient"},
    )
    assert resp.status_code == 200, resp.text

    encounter = db_session.query(models.Encounter).filter_by(patient_id=patient.id).first()
    details = _audit_details(db_session, patient.id, "add_encounter")
    assert details == [encounter.id]


def test_no_clinical_string_anywhere_in_audit_detail(test_client, db_session, make_user, auth_headers):
    """Belt-and-braces: after exercising every add_* path, none of the
    clinical values appear in ANY audit_logs.detail row for the patient."""
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    h = auth_headers(clinician)

    secrets = {
        "conditions": ("name", "Paranoid schizophrenia"),
        "medications": ("drug_name", "Clozapine 100mg"),
        "allergies": ("substance", "Sulfa drugs"),
    }
    for path, (field, value) in secrets.items():
        body = {field: value}
        if path == "allergies":
            body["severity"] = "moderate"
        assert test_client.post(
            f"/patients/{patient.id}/{path}", headers=h, json=body
        ).status_code == 200

    all_details = " || ".join(
        row.detail or ""
        for row in db_session.query(models.AuditLog).filter_by(patient_id=patient.id).all()
    )
    for _field, value in secrets.values():
        assert value not in all_details
