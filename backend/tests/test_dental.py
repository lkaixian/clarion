"""P3.2 dental module (routers/dental.py) -- RBAC, sign-off, cross-facility
scoping/immutability of the tooth chart. Everything else the clause asks for
(queue/appointments, X-ray referral, medication, diagnosis) reuses an
existing engine unchanged and is exercised by its own test file -- see
models.py's "Dental engine" section comment and routers/dental.py's module
docstring for the clause-by-clause mapping. This file only covers what's new.
"""
from app import models
from conftest import _facility, _make_patient, _TEST_SIGNATURE_B64


def _entry_body(patient_id, **overrides):
    body = {
        "patient_id": patient_id,
        "tooth_code": "11",
        "finding": "caries",
        "treatment": "filling",
        "notes": "Occlusal caries.",
        "signature_b64": _TEST_SIGNATURE_B64,
    }
    body.update(overrides)
    return body


def test_chart_options_lists_fdi_codes_and_vocab(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility=_facility("Facility A"))
    resp = test_client.get("/dental/chart-options", headers=auth_headers(clinician))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tooth_codes"]) == 32
    assert "11" in body["tooth_codes"] and "48" in body["tooth_codes"]
    assert "caries" in body["findings"]
    assert "filling" in body["treatments"]


def test_create_entry_rbac(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    facility = _facility("Facility A")

    for role in ("admin", "records_officer", "clinician"):
        user = make_user(role=role, facility=facility)
        resp = test_client.post(
            "/dental/chart", json=_entry_body(patient.id), headers=auth_headers(user)
        )
        assert resp.status_code == 201, (role, resp.text)

    for role in ("receptionist", "pharmacist"):
        user = make_user(role=role, facility=facility)
        resp = test_client.post(
            "/dental/chart", json=_entry_body(patient.id), headers=auth_headers(user)
        )
        assert resp.status_code == 403, role


def test_create_entry_requires_facility(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    admin = make_user(role="admin", facility=None)
    resp = test_client.post("/dental/chart", json=_entry_body(patient.id), headers=auth_headers(admin))
    assert resp.status_code == 400


def test_create_entry_requires_signature(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))
    body = _entry_body(patient.id)
    body.pop("signature_b64")
    resp = test_client.post("/dental/chart", json=body, headers=auth_headers(clinician))
    assert resp.status_code == 409


def test_invalid_tooth_code_finding_treatment_rejected(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    resp = test_client.post(
        "/dental/chart", json=_entry_body(patient.id, tooth_code="99"), headers=auth_headers(clinician)
    )
    assert resp.status_code == 422

    resp = test_client.post(
        "/dental/chart", json=_entry_body(patient.id, finding="not-a-real-finding"), headers=auth_headers(clinician)
    )
    assert resp.status_code == 422

    resp = test_client.post(
        "/dental/chart", json=_entry_body(patient.id, treatment="not-a-real-treatment"), headers=auth_headers(clinician)
    )
    assert resp.status_code == 422


def test_encounter_id_must_belong_to_patient(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    other_patient = _make_patient(db_session, full_name="Someone Else")
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    encounter = models.Encounter(
        patient_id=other_patient.id, facility_name=clinician.facility, encounter_type="outpatient",
    )
    db_session.add(encounter)
    db_session.commit()

    resp = test_client.post(
        "/dental/chart", json=_entry_body(patient.id, encounter_id=encounter.id), headers=auth_headers(clinician)
    )
    assert resp.status_code == 404


def test_encounter_id_happy_path_round_trips(test_client, make_user, auth_headers, db_session):
    """The success case for encounter_id, complementing
    test_encounter_id_must_belong_to_patient's rejection case above -- a
    valid encounter for the SAME patient is accepted and comes back on the
    created entry, since it's the field that lets an X-ray referral raised
    mid-visit (routers/ancillary.py) share source_encounter_id with the
    chart entry for that same encounter."""
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    encounter = models.Encounter(
        patient_id=patient.id, facility_name=clinician.facility, encounter_type="outpatient",
    )
    db_session.add(encounter)
    db_session.commit()

    resp = test_client.post(
        "/dental/chart", json=_entry_body(patient.id, encounter_id=encounter.id), headers=auth_headers(clinician)
    )
    assert resp.status_code == 201
    assert resp.json()["encounter_id"] == encounter.id


def test_chart_pagination_boundary_respects_records_shared_publicly(test_client, make_user, auth_headers, db_session):
    """Same pagination-before-filter discipline as
    ancillary.py::list_service_requests -- a page must contain exactly
    `limit` VISIBLE entries, not `limit` raw rows minus whatever got
    stripped out after the fact. Named explicitly in
    routers/dental.py::get_dental_chart's docstring as a lesson learned from
    a real P3.1 bug; this test is the regression guard for it here."""
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    db_session.add(models.HospitalSetting(facility_name=facility_b, records_shared_publicly=False))
    db_session.commit()

    # Interleaved so order by created_at desc is A, B, A, B, A.
    for fac_user, tooth in (
        (clinician_a, "11"), (clinician_b, "12"), (clinician_a, "13"),
        (clinician_b, "14"), (clinician_a, "15"),
    ):
        test_client.post(
            "/dental/chart", json=_entry_body(patient.id, tooth_code=tooth), headers=auth_headers(fac_user)
        )

    # Facility B's entries fall inside the naive first-3-rows window. If the
    # hidden-facility filter ran AFTER limit/offset, this would come back
    # with only 2 (of the 3 real) visible entries.
    resp = test_client.get(
        f"/dental/chart/{patient.id}", params={"limit": 3}, headers=auth_headers(clinician_a)
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 3
    assert all(e["facility_name"] == facility_a for e in entries)


def test_chart_is_immutable_no_patch_or_delete_route(test_client, make_user, auth_headers, db_session):
    """No PATCH/PUT/DELETE endpoint exists at all -- a correction is a new
    ClinicalRecordAnnotation, never an edit. Asserted via the OpenAPI schema
    rather than guessing at a URL, so this fails loudly if one is ever added
    without a matching immutability review."""
    admin = make_user(role="admin", facility=_facility("Facility A"))
    resp = test_client.get("/openapi.json", headers=auth_headers(admin))
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    dental_paths = {p: methods for p, methods in paths.items() if p.startswith("/dental/")}
    for methods in dental_paths.values():
        assert "patch" not in methods
        assert "put" not in methods
        assert "delete" not in methods


def test_cross_facility_read_respects_records_shared_publicly(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    created = test_client.post(
        "/dental/chart", json=_entry_body(patient.id), headers=auth_headers(clinician_a)
    ).json()

    # Facility B can see it before any opt-out.
    resp = test_client.get(f"/dental/chart/{patient.id}", headers=auth_headers(clinician_b))
    assert resp.status_code == 200
    assert any(e["id"] == created["id"] for e in resp.json())

    db_session.add(models.HospitalSetting(facility_name=facility_a, records_shared_publicly=False))
    db_session.commit()

    # Now hidden from facility B...
    resp = test_client.get(f"/dental/chart/{patient.id}", headers=auth_headers(clinician_b))
    assert resp.status_code == 200
    assert all(e["id"] != created["id"] for e in resp.json())

    # ...but never hidden from facility A's own staff.
    resp = test_client.get(f"/dental/chart/{patient.id}", headers=auth_headers(clinician_a))
    assert resp.status_code == 200
    assert any(e["id"] == created["id"] for e in resp.json())


def test_receptionist_cannot_read_chart(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=_facility("Facility A"))
    resp = test_client.get(f"/dental/chart/{patient.id}", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_correction_via_annotation_hidden_when_facility_opted_out(test_client, make_user, auth_headers, db_session):
    """A dental_chart_entry-targeted annotation respects the same
    records_shared_publicly opt-out as the underlying chart entry itself --
    same protection wired in for service_result annotations in the P3.1
    follow-up wave, extended here at the point dental_chart_entry was added
    as a second _ANNOTATION_MODEL target."""
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    created = test_client.post(
        "/dental/chart", json=_entry_body(patient.id), headers=auth_headers(clinician_a)
    ).json()

    resp = test_client.post(
        f"/patients/{patient.id}/annotations",
        json={"target_type": "dental_chart_entry", "target_id": created["id"], "kind": "correction", "note": "typo"},
        headers=auth_headers(clinician_a),
    )
    assert resp.status_code == 200

    db_session.add(models.HospitalSetting(facility_name=facility_a, records_shared_publicly=False))
    db_session.commit()

    resp_b = test_client.get(f"/patients/{patient.id}/annotations", headers=auth_headers(clinician_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []

    resp_a = test_client.get(f"/patients/{patient.id}/annotations", headers=auth_headers(clinician_a))
    assert resp_a.status_code == 200
    assert len(resp_a.json()) == 1


def test_xray_referral_reuses_ancillary_engine(test_client, make_user, auth_headers, db_session):
    """ (references to X-ray) is deliberately not a dental.py
    endpoint -- it's routers/ancillary.py's existing ServiceRequest, ordered
    with module='xray' and this encounter's id. This test just confirms
    that path actually works end-to-end from a dental context."""
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)

    encounter = models.Encounter(patient_id=patient.id, facility_name=facility, encounter_type="dental")
    db_session.add(encounter)
    db_session.commit()

    xray_item = models.ServiceCatalogItem(module="xray", name="Panoramic X-ray", unit_price_cents=9000)
    db_session.add(xray_item)
    db_session.commit()

    resp = test_client.post(
        "/ancillary/requests",
        json={
            "patient_id": patient.id, "module": "xray", "catalog_item_id": xray_item.id,
            "source": "physician_order", "source_encounter_id": encounter.id,
            "clinical_indication": "Dental referral for panoramic view", "priority": "routine",
        },
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 201
    assert resp.json()["source_encounter_id"] == encounter.id
