"""P3.5: generated Digital Medical Certificate / Referral Letter / Timeslip
documents (routers/patients.py::generate_document, app/document_generation.py)."""
from app import models
from conftest import _facility, _make_patient, _TEST_SIGNATURE_B64


def _generate(test_client, patient_id, headers, **body):
    return test_client.post(
        f"/patients/{patient_id}/documents/generate",
        json={"signature_b64": _TEST_SIGNATURE_B64, **body},
        headers=headers,
    )


def test_generate_medical_certificate(test_client, db_session, make_user, auth_headers):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(clinician),
        doc_type="medical_certificate", diagnosis="Viral fever",
        rest_from="2026-09-14", rest_to="2026-09-16",
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]

    doc = db_session.query(models.ClinicalDocument).filter_by(id=doc_id).one()
    assert doc.doc_type == "medical_certificate"
    assert doc.signed_by == clinician.id
    assert doc.signed_by_name == clinician.full_name
    assert doc.signed_at is not None
    assert doc.uploaded_by_facility == facility
    assert "Viral fever" in doc.raw_text
    assert doc.file_object_key

    got = test_client.get(f"/patients/{patient.id}/documents/{doc_id}/file", headers=auth_headers(clinician))
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/pdf"
    assert got.content.startswith(b"%PDF")


def test_generate_referral_letter(test_client, db_session, make_user, auth_headers):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(clinician),
        doc_type="referral_letter", referred_to="University Specialist Clinic",
        reason_for_referral="Suspected fracture, needs X-ray follow-up",
    )
    assert resp.status_code == 200, resp.text
    doc = db_session.query(models.ClinicalDocument).filter_by(id=resp.json()["document_id"]).one()
    assert doc.doc_type == "referral_letter"
    assert "University Specialist Clinic" in doc.raw_text


def test_generate_timeslip(test_client, db_session, make_user, auth_headers):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(clinician),
        doc_type="timeslip", visit_date="2026-09-13", time_in="09:00", time_out="11:30",
    )
    assert resp.status_code == 200, resp.text
    doc = db_session.query(models.ClinicalDocument).filter_by(id=resp.json()["document_id"]).one()
    assert doc.doc_type == "timeslip"
    # Exact "09:00 to 11:30" (no seconds) -- catches datetime.time's default
    # str() giving "09:00:00" if the render path ever stops using strftime.
    assert "from 09:00 to 11:30" in doc.raw_text


def test_generate_requires_signature(test_client, make_user, auth_headers, db_session):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/patients/{patient.id}/documents/generate",
        json={"doc_type": "timeslip", "visit_date": "2026-09-13", "time_in": "09:00", "time_out": "10:00"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 409


def test_generate_missing_required_field_is_422(test_client, make_user, auth_headers, db_session):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    # medical_certificate with no diagnosis/rest_from/rest_to at all
    resp = _generate(test_client, patient.id, auth_headers(clinician), doc_type="medical_certificate")
    assert resp.status_code == 422


def test_generate_whitespace_only_required_field_is_422(test_client, make_user, auth_headers, db_session):
    """str_strip_whitespace on GenerateDocumentRequest -- a whitespace-only
    'diagnosis' must not pass the required-field check as truthy."""
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(clinician),
        doc_type="medical_certificate", diagnosis="   ",
        rest_from="2026-09-14", rest_to="2026-09-16",
    )
    assert resp.status_code == 422


def test_generate_rest_to_before_rest_from_is_422(test_client, make_user, auth_headers, db_session):
    facility = _facility("Clinic")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(clinician),
        doc_type="medical_certificate", diagnosis="x",
        rest_from="2026-09-20", rest_to="2026-09-10",
    )
    assert resp.status_code == 422


def test_generate_receptionist_forbidden(test_client, make_user, auth_headers, db_session):
    """generate_document is scoped to admin/records_officer/clinician, same
    role set as every other clinical-document write here -- a receptionist
    (front-desk role) must not be able to issue a signed medical document."""
    facility = _facility("Clinic")
    receptionist = make_user(role="receptionist", facility=facility)
    patient = _make_patient(db_session)

    resp = _generate(
        test_client, patient.id, auth_headers(receptionist),
        doc_type="timeslip", visit_date="2026-09-13", time_in="09:00", time_out="10:00",
    )
    assert resp.status_code == 403
