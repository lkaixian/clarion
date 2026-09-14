"""P4.2 — FHIR façade test suite.

Tests the read-only FHIR R4 façade router (app/routers/fhir.py) mounted under
/fhir and gated on require_page_access("patients").

Covers:
  1. GET /fhir/{ResourceType}/{id} as a clinician user for all 8 supported
     resource types (Patient, Condition, MedicationStatement,
     AllergyIntolerance, Encounter, ServiceRequest, DiagnosticReport,
     DocumentReference) returning 200 with the matching resourceType and id.
  2. GET /fhir/{ResourceType}?patient={patient_id} for all 7 search-capable
     resources returning 200 with a searchset Bundle containing the row id.
  3. Patient-role denial: GET /fhir/Patient/{own_id} with the patient's own
     token returns 404 (the façade denies patient-role self-service by design).
  4. Nonexistent patient ID: GET /fhir/Patient/{random_uuid} returns 404.
  5. CapabilityStatement: GET /fhir/metadata is page-gated (401/403 without a
     valid clinician token) and returns 200 CapabilityStatement with Patient
     listed when called by an authorized clinician.
"""
import uuid

from app import models
from conftest import _facility, _make_patient


# ---------------------------------------------------------------------------
# 1. CapabilityStatement / Page-access gating (GET /fhir/metadata)
# ---------------------------------------------------------------------------
def test_fhir_metadata_access_and_capability_statement(test_client, make_user, auth_headers):
    # Unauthenticated request is rejected (401 from get_current_user)
    resp_unauth = test_client.get("/fhir/metadata")
    assert resp_unauth.status_code in (401, 403)

    # Receptionist without the `patients` page access gets 403
    receptionist = make_user(role="receptionist", facility=_facility("Facility A"))
    resp_receptionist = test_client.get("/fhir/metadata", headers=auth_headers(receptionist))
    assert resp_receptionist.status_code == 403

    # Clinician with the `patients` page access gets 200 CapabilityStatement
    clinician = make_user(role="clinician", facility=_facility("Facility A"))
    resp = test_client.get("/fhir/metadata", headers=auth_headers(clinician))
    assert resp.status_code == 200

    data = resp.json()
    assert data["resourceType"] == "CapabilityStatement"
    assert data["status"] == "active"
    assert data["kind"] == "instance"
    assert data["fhirVersion"] == "4.0.1"

    rest = data.get("rest", [])
    assert len(rest) > 0
    resources = rest[0].get("resource", [])
    resource_types = [r["type"] for r in resources]
    assert "Patient" in resource_types

    expected_all = [
        "Patient", "Condition", "MedicationStatement", "AllergyIntolerance",
        "Encounter", "ServiceRequest", "DiagnosticReport", "DocumentReference",
    ]
    for rt in expected_all:
        assert rt in resource_types


# ---------------------------------------------------------------------------
# 2. Patient read & access control (GET /fhir/Patient/{id})
# ---------------------------------------------------------------------------
def test_fhir_patient_read_and_access_control(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session, full_name="Ahmad bin Abdullah", date_of_birth="1980-05-15", gender="Male")

    # Clinician gets 200 with resourceType Patient and matching id
    resp = test_client.get(f"/fhir/Patient/{patient.id}", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["resourceType"] == "Patient"
    assert data["id"] == patient.id
    assert data["name"][0]["text"] == "Ahmad bin Abdullah"
    assert data["birthDate"] == "1980-05-15"

    # Patient role own token gets 404 (facade denies patient role entirely by design)
    patient_user = make_user(role="patient", patient_id=patient.id)
    resp_patient = test_client.get(f"/fhir/Patient/{patient.id}", headers=auth_headers(patient_user))
    assert resp_patient.status_code == 404

    # Nonexistent patient UUID as a clinician returns 404
    nonexistent_id = str(uuid.uuid4())
    resp_nonexistent = test_client.get(f"/fhir/Patient/{nonexistent_id}", headers=auth_headers(clinician))
    assert resp_nonexistent.status_code == 404


# ---------------------------------------------------------------------------
# 3. Condition (GET /fhir/Condition/{id} and GET /fhir/Condition?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_condition_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    condition = models.Condition(
        patient_id=patient.id,
        name="Essential Hypertension",
        status="active",
        authored_by_facility=facility,
    )
    db_session.add(condition)
    db_session.commit()
    db_session.refresh(condition)

    # 1. Read
    resp_read = test_client.get(f"/fhir/Condition/{condition.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "Condition"
    assert read_data["id"] == condition.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/Condition?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert condition.id in entry_ids


# ---------------------------------------------------------------------------
# 4. MedicationStatement (GET /fhir/MedicationStatement/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_medication_statement_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    med = models.MedicationStatement(
        patient_id=patient.id,
        drug_name="Metformin 500mg",
        dosage="500mg",
        frequency="BD",
        prescribed_by_facility=facility,
        recorded_by_facility=facility,
        active=True,
    )
    db_session.add(med)
    db_session.commit()
    db_session.refresh(med)

    # 1. Read
    resp_read = test_client.get(f"/fhir/MedicationStatement/{med.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "MedicationStatement"
    assert read_data["id"] == med.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/MedicationStatement?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert med.id in entry_ids


# ---------------------------------------------------------------------------
# 5. AllergyIntolerance (GET /fhir/AllergyIntolerance/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_allergy_intolerance_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    allergy = models.AllergyIntolerance(
        patient_id=patient.id,
        substance="Amoxicillin",
        reaction="Maculopapular rash",
        severity="mild",
        authored_by_facility=facility,
    )
    db_session.add(allergy)
    db_session.commit()
    db_session.refresh(allergy)

    # 1. Read
    resp_read = test_client.get(f"/fhir/AllergyIntolerance/{allergy.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "AllergyIntolerance"
    assert read_data["id"] == allergy.id
    assert read_data["patient"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/AllergyIntolerance?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert allergy.id in entry_ids


# ---------------------------------------------------------------------------
# 6. Encounter (GET /fhir/Encounter/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_encounter_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    encounter = models.Encounter(
        patient_id=patient.id,
        facility_name=facility,
        encounter_type="outpatient",
        reason="Follow-up consultation",
    )
    db_session.add(encounter)
    db_session.commit()
    db_session.refresh(encounter)

    # 1. Read
    resp_read = test_client.get(f"/fhir/Encounter/{encounter.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "Encounter"
    assert read_data["id"] == encounter.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/Encounter?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert encounter.id in entry_ids


# ---------------------------------------------------------------------------
# 7. ServiceRequest (GET /fhir/ServiceRequest/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_service_request_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    catalog_item = models.ServiceCatalogItem(
        module="laboratory",
        name="Full Blood Count",
        unit_price_cents=4500,
        facility_name=facility,
    )
    db_session.add(catalog_item)
    db_session.commit()
    db_session.refresh(catalog_item)

    service_request = models.ServiceRequest(
        patient_id=patient.id,
        module="laboratory",
        catalog_item_id=catalog_item.id,
        source="physician_order",
        priority="routine",
        status="ordered",
        ordering_facility_name=facility,
    )
    db_session.add(service_request)
    db_session.commit()
    db_session.refresh(service_request)

    # 1. Read
    resp_read = test_client.get(f"/fhir/ServiceRequest/{service_request.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "ServiceRequest"
    assert read_data["id"] == service_request.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/ServiceRequest?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert service_request.id in entry_ids


# ---------------------------------------------------------------------------
# 8. DiagnosticReport (GET /fhir/DiagnosticReport/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_diagnostic_report_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    catalog_item = models.ServiceCatalogItem(
        module="laboratory",
        name="Lipid Profile",
        unit_price_cents=6000,
        facility_name=facility,
    )
    db_session.add(catalog_item)
    db_session.commit()
    db_session.refresh(catalog_item)

    service_request = models.ServiceRequest(
        patient_id=patient.id,
        module="laboratory",
        catalog_item_id=catalog_item.id,
        source="physician_order",
        priority="routine",
        status="ordered",
        ordering_facility_name=facility,
    )
    db_session.add(service_request)
    db_session.commit()
    db_session.refresh(service_request)

    service_result = models.ServiceResult(
        service_request_id=service_request.id,
        patient_id=patient.id,
        result_text="Total Cholesterol: 4.8 mmol/L (Normal)",
        facility_name=facility,
    )
    db_session.add(service_result)
    db_session.commit()
    db_session.refresh(service_result)

    # 1. Read
    resp_read = test_client.get(f"/fhir/DiagnosticReport/{service_result.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "DiagnosticReport"
    assert read_data["id"] == service_result.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/DiagnosticReport?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert service_result.id in entry_ids


# ---------------------------------------------------------------------------
# 9. DocumentReference (GET /fhir/DocumentReference/{id} and ?patient={id})
# ---------------------------------------------------------------------------
def test_fhir_document_reference_read_and_search(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)

    doc = models.ClinicalDocument(
        patient_id=patient.id,
        doc_type="discharge_summary",
        original_filename="discharge_summary_20260914.pdf",
        uploaded_by_facility=facility,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # 1. Read
    resp_read = test_client.get(f"/fhir/DocumentReference/{doc.id}", headers=auth_headers(clinician))
    assert resp_read.status_code == 200, resp_read.text
    read_data = resp_read.json()
    assert read_data["resourceType"] == "DocumentReference"
    assert read_data["id"] == doc.id
    assert read_data["subject"]["reference"] == f"Patient/{patient.id}"

    # 2. Search by patient
    resp_search = test_client.get(f"/fhir/DocumentReference?patient={patient.id}", headers=auth_headers(clinician))
    assert resp_search.status_code == 200, resp_search.text
    bundle = resp_search.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    entry_ids = [e["resource"]["id"] for e in bundle.get("entry", [])]
    assert doc.id in entry_ids
