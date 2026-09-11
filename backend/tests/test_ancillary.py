"""P3.1 ancillary engine (routers/ancillary.py) — RBAC (ORDER_ROLES vs
SIGNOFF_ROLES), cross-facility scoping/immutability, and the
order -> result -> sign-off -> document lifecycle. Page-level gating
(main.py's require_page_access("ancillary")) is exercised incidentally
here (every test user gets a real facility, so the lazy-created
RolePagePermission row picks up app/permissions.py's real defaults) but is
not this file's focus -- see test_auth_rbac_immutability.py for that.
"""
import uuid

from app import models
from app.routers.patients import _ANNOTATION_MODEL

# RolePagePermission is unique per (facility_name, role) and gets
# lazily-created as a side effect of any authenticated request through a
# page-gated router (see app/permissions.py::get_or_create_role_permission).
# This file's DB is session-scoped and shared with every OTHER test module
# (conftest.py::db_session has no per-test rollback), so a literal facility
# name like "Facility A" reused for the same role across files/tests risks
# a stale accumulated row -- or, worse, a UNIQUE-constraint collision with
# another test file that inserts its own row for that exact (facility,
# role) pair unconditionally. Every facility name in this file is therefore
# manufactured fresh per test via this helper.
def _facility(label="Facility"):
    return f"{label} {uuid.uuid4().hex[:8]}"

# A genuine 4x4 white PNG (Pillow-decodable) -- required by
# save_signature_from_b64 -> _persist_signature_bytes -> _validate_png_bytes
# on the FIRST sign-off call from a user with no saved signature yet.
_TEST_SIGNATURE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGP8//8/AwwwwVl4"
    "OQCWbgMF7ZjH1AAAAABJRU5ErkJggg=="
)


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


def _make_catalog_item(db_session, module="laboratory", **overrides):
    item = models.ServiceCatalogItem(
        module=module,
        name=overrides.pop("name", "Full Blood Count"),
        unit_price_cents=overrides.pop("unit_price_cents", 4500),
        **overrides,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _order_body(patient_id, catalog_item_id, module="laboratory", **overrides):
    body = {
        "patient_id": patient_id,
        "module": module,
        "catalog_item_id": catalog_item_id,
        "source": "frontdesk",
        "priority": "routine",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def test_catalog_global_item_visible_everywhere_facility_item_scoped(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    _make_catalog_item(db_session, name="Global FBC", facility_name=None)
    _make_catalog_item(db_session, name="Facility A Only", facility_name=facility_a)

    user_a = make_user(role="clinician", facility=facility_a)
    user_b = make_user(role="clinician", facility=facility_b)

    resp_a = test_client.get("/ancillary/catalog", headers=auth_headers(user_a))
    names_a = {i["name"] for i in resp_a.json()}
    assert "Global FBC" in names_a
    assert "Facility A Only" in names_a

    resp_b = test_client.get("/ancillary/catalog", headers=auth_headers(user_b))
    names_b = {i["name"] for i in resp_b.json()}
    assert "Global FBC" in names_b
    assert "Facility A Only" not in names_b


def test_catalog_create_rbac_and_facility_scoping(test_client, make_user, auth_headers):
    facility_a = _facility("Facility A")
    admin = make_user(role="admin", facility=facility_a)
    records = make_user(role="records_officer", facility=facility_a)
    clinician = make_user(role="clinician", facility=facility_a)
    receptionist = make_user(role="receptionist", facility=facility_a)

    body = {"module": "laboratory", "name": "Urine FEME", "unit_price_cents": 2000, "facility_name": "Someone Else"}

    resp = test_client.post("/ancillary/catalog", json=body, headers=auth_headers(records))
    assert resp.status_code == 201, resp.text
    # A non-admin's item is scoped to THEIR OWN facility regardless of what
    # facility_name they sent.
    assert resp.json()["facility_name"] == facility_a

    assert test_client.post("/ancillary/catalog", json=body, headers=auth_headers(admin)).status_code == 201
    assert test_client.post("/ancillary/catalog", json=body, headers=auth_headers(clinician)).status_code == 403
    assert test_client.post("/ancillary/catalog", json=body, headers=auth_headers(receptionist)).status_code == 403


def test_catalog_patch_ownership_not_forbidden_convention(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    item_a = _make_catalog_item(db_session, facility_name=facility_a)
    global_item = _make_catalog_item(db_session, facility_name=None, name="Global Item")

    records_b = make_user(role="records_officer", facility=facility_b)
    records_a = make_user(role="records_officer", facility=facility_a)
    admin = make_user(role="admin", facility=facility_a)

    # Wrong facility -> 404, not 403 (same non-leaking convention as the
    # rest of the app).
    resp = test_client.patch(f"/ancillary/catalog/{item_a.id}", json={"active": False}, headers=auth_headers(records_b))
    assert resp.status_code == 404

    resp = test_client.patch(f"/ancillary/catalog/{item_a.id}", json={"active": False}, headers=auth_headers(records_a))
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    resp = test_client.patch(f"/ancillary/catalog/{global_item.id}", json={"active": False}, headers=auth_headers(admin))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------
def test_create_request_rbac(test_client, make_user, auth_headers, db_session):
    facility_a = _facility("Facility A")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)

    for role in ("admin", "records_officer", "clinician", "receptionist"):
        user = make_user(role=role, facility=facility_a)
        resp = test_client.post(
            "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(user),
        )
        assert resp.status_code == 201, (role, resp.text)

    pharmacist = make_user(role="pharmacist", facility=facility_a)
    resp = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(pharmacist),
    )
    assert resp.status_code == 403


def test_create_request_validation(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    other_patient = _make_patient(db_session, full_name="Someone Else")
    lab_item = _make_catalog_item(db_session, module="laboratory", facility_name=None)
    inactive_item = _make_catalog_item(db_session, module="laboratory", facility_name=None, active=False, name="Inactive Test")
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    # module mismatch
    resp = test_client.post(
        "/ancillary/requests",
        json=_order_body(patient.id, lab_item.id, module="xray"),
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 400

    # inactive catalog item
    resp = test_client.post(
        "/ancillary/requests",
        json=_order_body(patient.id, inactive_item.id, module="laboratory"),
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 400

    # physician_order with no source_encounter_id -> 422 (pydantic)
    resp = test_client.post(
        "/ancillary/requests",
        json=_order_body(patient.id, lab_item.id, source="physician_order"),
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 422

    # physician_order with an encounter that belongs to a DIFFERENT patient -> 404
    encounter = models.Encounter(patient_id=other_patient.id, facility_name="Facility A", encounter_type="outpatient")
    db_session.add(encounter)
    db_session.commit()
    resp = test_client.post(
        "/ancillary/requests",
        json=_order_body(patient.id, lab_item.id, source="physician_order", source_encounter_id=encounter.id),
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 404


def test_create_request_happy_path_snapshots_price_and_facility(test_client, make_user, auth_headers, db_session):
    facility_a = _facility("Facility A")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None, unit_price_cents=8000)
    clinician = make_user(role="clinician", facility=facility_a)

    resp = test_client.post("/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ordering_facility_name"] == facility_a
    assert body["unit_price_cents"] == 8000
    assert body["status"] == "ordered"
    assert body["catalog_item_name"] == item.name


# ---------------------------------------------------------------------------
# Listing / scoping
# ---------------------------------------------------------------------------
def test_list_requests_scoped_to_own_facility_by_default(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    test_client.post("/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a))

    resp_a = test_client.get("/ancillary/requests", params={"module": "laboratory"}, headers=auth_headers(clinician_a))
    assert len(resp_a.json()) == 1

    resp_b = test_client.get("/ancillary/requests", params={"module": "laboratory"}, headers=auth_headers(clinician_b))
    assert resp_b.json() == []


def test_list_requests_by_patient_cross_facility_denied_for_receptionist(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))
    receptionist = make_user(role="receptionist", facility=_facility("Facility B"))

    test_client.post("/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician))

    resp = test_client.get("/ancillary/requests", params={"patient_id": patient.id}, headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = test_client.get("/ancillary/requests", params={"patient_id": patient.id}, headers=auth_headers(receptionist))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
def test_cancel_request(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=_facility("Facility A"))
    clinician_b = make_user(role="clinician", facility=_facility("Facility B"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()
    request_id = created["id"]

    # a different facility cannot cancel -> 404
    resp = test_client.post(f"/ancillary/requests/{request_id}/cancel", json={}, headers=auth_headers(clinician_b))
    assert resp.status_code == 404

    resp = test_client.post(f"/ancillary/requests/{request_id}/cancel", json={"reason": "no longer needed"}, headers=auth_headers(clinician_a))
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # already cancelled -> 400
    resp = test_client.post(f"/ancillary/requests/{request_id}/cancel", json={}, headers=auth_headers(clinician_a))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Sign-off
# ---------------------------------------------------------------------------
def test_signoff_rbac(test_client, make_user, auth_headers, db_session):
    facility_a = _facility("Facility A")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=facility_a)
    receptionist = make_user(role="receptionist", facility=facility_a)

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "n/a", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(receptionist),
    )
    assert resp.status_code == 403


def test_signoff_confined_to_ordering_facility(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=_facility("Facility A"))
    clinician_b = make_user(role="clinician", facility=_facility("Facility B"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "not yours", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician_b),
    )
    assert resp.status_code == 404

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "all normal", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician_a),
    )
    assert resp.status_code == 200, resp.text


def test_signoff_signature_requirement_and_reuse(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    request_1 = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()

    # No saved signature, no signature_b64 -> 409.
    resp = test_client.post(
        f"/ancillary/requests/{request_1['id']}/result", json={"result_text": "x"}, headers=auth_headers(clinician),
    )
    assert resp.status_code == 409

    resp = test_client.post(
        f"/ancillary/requests/{request_1['id']}/result",
        json={"result_text": "x", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text

    # The signature was written via a DIFFERENT session (the endpoint's own
    # `get_db`-provided one) -- db_session's identity map still holds the
    # pre-sign-off `clinician` object, so a plain re-query returns the same
    # cached instance unless explicitly refreshed.
    db_session.refresh(clinician)
    assert clinician.signature_object_key

    # A second sign-off on a NEW request by the now-signed clinician needs
    # no signature_b64 at all.
    request_2 = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()
    resp = test_client.post(
        f"/ancillary/requests/{request_2['id']}/result", json={"result_text": "y"}, headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text


def test_signoff_happy_path_and_immutability(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "Hb 13.0", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "signed_off"
    assert body["result"]["signed_by_name"] == clinician.full_name
    assert body["result"]["performed_by_name"] == clinician.full_name
    assert body["result"]["has_document"] is False

    # Already signed off -- no re-sign endpoint, immutable.
    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "changed my mind"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Result document
# ---------------------------------------------------------------------------
def test_result_document_round_trip(test_client, make_user, auth_headers, db_session):
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()

    # Uploading before sign-off -> 400.
    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("report.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 400

    test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "see attached", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("report.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["has_document"] is True

    resp = test_client.get(f"/ancillary/requests/{created['id']}/result/document", headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert b"fake pdf bytes" in resp.content


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def test_stats_rbac_and_shape(test_client, make_user, auth_headers):
    receptionist = make_user(role="receptionist", facility=_facility("Facility A"))
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    assert test_client.get("/ancillary/stats", headers=auth_headers(receptionist)).status_code == 403

    resp = test_client.get("/ancillary/stats", headers=auth_headers(clinician))
    assert resp.status_code == 200
    body = resp.json()
    for module in ("procedure", "laboratory", "xray", "physiotherapy"):
        assert module in body["open_by_module"]
        assert module in body["signed_off_last_30d_by_module"]


# ---------------------------------------------------------------------------
# Correction via the existing annotation mechanism
# ---------------------------------------------------------------------------
def test_service_result_registered_as_annotation_target(test_client, make_user, auth_headers, db_session):
    assert _ANNOTATION_MODEL.get("service_result") is models.ServiceResult

    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()
    signed = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "initial", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    ).json()
    result_id = signed["result"]["id"]

    resp = test_client.post(
        f"/patients/{patient.id}/annotations",
        json={"target_type": "service_result", "target_id": result_id, "kind": "correction", "note": "typo fixed"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
