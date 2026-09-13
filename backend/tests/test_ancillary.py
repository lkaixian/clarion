"""P3.1 ancillary engine (routers/ancillary.py) — RBAC (ORDER_ROLES vs
SIGNOFF_ROLES), cross-facility scoping/immutability, and the
order -> result -> sign-off -> document lifecycle. Page-level gating
(main.py's require_page_access("ancillary")) is exercised incidentally
here (every test user gets a real facility, so the lazy-created
RolePagePermission row picks up app/permissions.py's real defaults) but is
not this file's focus -- see test_auth_rbac_immutability.py for that.
"""
import time

from app import models
from app.routers.patients import _ANNOTATION_MODEL
from conftest import _facility, _make_patient, _TEST_SIGNATURE_B64


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

    # An admin may NOT plant an item under an arbitrary OTHER facility's
    # name either -- only their own facility or null (global).
    assert test_client.post("/ancillary/catalog", json=body, headers=auth_headers(admin)).status_code == 403

    resp = test_client.post(
        "/ancillary/catalog", json={**body, "facility_name": facility_a}, headers=auth_headers(admin)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["facility_name"] == facility_a

    resp = test_client.post(
        "/ancillary/catalog", json={**body, "facility_name": None}, headers=auth_headers(admin)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["facility_name"] is None

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

    # No admin override: an admin from a DIFFERENT facility than item_a's
    # owner is denied exactly like anyone else (fixed 2026-09-12,
    # /code-review -- this used to skip the ownership check for role=='admin').
    admin_b = make_user(role="admin", facility=facility_b)
    resp = test_client.patch(f"/ancillary/catalog/{item_a.id}", json={"active": True}, headers=auth_headers(admin_b))
    assert resp.status_code == 404


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


# ---------------------------------------------------------------------------
# Code-review follow-up (2026-09-12): admin has NO cross-facility override
# on write paths, receptionist gets no clinical result content, catalog
# visibility is enforced at order-TIME (not just at listing), records_shared_
# publicly is respected on cross-facility ancillary reads, and a genuine
# double sign-off raises a clean 409 instead of an unhandled 500.
# ---------------------------------------------------------------------------
def test_admin_has_no_cross_facility_write_override(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    admin_b = make_user(role="admin", facility=facility_b)

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()

    resp = test_client.post(f"/ancillary/requests/{created['id']}/cancel", json={}, headers=auth_headers(admin_b))
    assert resp.status_code == 404

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "forged", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(admin_b),
    )
    assert resp.status_code == 404


def test_catalog_item_facility_scoping_enforced_at_order_time(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    private_item = _make_catalog_item(db_session, facility_name=facility_a, name="Facility A Private Test")
    clinician_b = make_user(role="clinician", facility=facility_b)

    resp = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, private_item.id), headers=auth_headers(clinician_b),
    )
    assert resp.status_code == 404


def test_receptionist_never_sees_clinical_result_content(test_client, make_user, auth_headers, db_session):
    facility_a = _facility("Facility A")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=facility_a)
    receptionist = make_user(role="receptionist", facility=facility_a)

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()
    test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "Hb 13.0 -- sensitive", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )

    # Own-facility default worklist -- result must be stripped.
    resp = test_client.get("/ancillary/requests", params={"module": "laboratory"}, headers=auth_headers(receptionist))
    assert resp.status_code == 200
    rows = [r for r in resp.json() if r["id"] == created["id"]]
    assert len(rows) == 1
    assert rows[0]["result"] is None

    # Single-request detail -- same stripping.
    resp = test_client.get(f"/ancillary/requests/{created['id']}", headers=auth_headers(receptionist))
    assert resp.status_code == 200
    assert resp.json()["result"] is None

    # The document endpoint itself is SIGNOFF_ROLES-only now, not
    # ORDER_ROLES -- a receptionist can't fetch a result attachment even
    # by guessing/knowing the request_id.
    resp = test_client.get(f"/ancillary/requests/{created['id']}/result/document", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_cross_facility_document_upload_denied(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()
    test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "x", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician_a),
    )

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("report.pdf", b"%PDF-1.4 not yours", "application/pdf")},
        headers=auth_headers(clinician_b),
    )
    assert resp.status_code == 404


def test_records_shared_publicly_hides_cross_facility_ancillary_reads(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    db_session.add(models.HospitalSetting(facility_name=facility_a, records_shared_publicly=False))
    db_session.commit()

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()

    # A facility-B clinician's cross-facility patient-history view no
    # longer includes facility A's opted-out request.
    resp = test_client.get(
        "/ancillary/requests", params={"patient_id": patient.id}, headers=auth_headers(clinician_b)
    )
    assert resp.status_code == 200
    assert all(r["id"] != created["id"] for r in resp.json())

    resp = test_client.get(f"/ancillary/requests/{created['id']}", headers=auth_headers(clinician_b))
    assert resp.status_code == 404

    # Facility A's own staff are never hidden from their own data.
    resp = test_client.get(f"/ancillary/requests/{created['id']}", headers=auth_headers(clinician_a))
    assert resp.status_code == 200


def test_signoff_double_insert_race_returns_409_not_500(test_client, make_user, auth_headers, db_session):
    """Simulates the race sign_off_service_request's IntegrityError handler
    guards against: a ServiceResult already exists for this request (as a
    concurrent second sign-off would produce) while the request's own
    status column hasn't been updated yet. Constructed directly via
    db_session rather than real threads/concurrency."""
    facility_a = _facility("Facility A")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=facility_a)

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()

    db_session.add(models.ServiceResult(service_request_id=created["id"], patient_id=patient.id))
    db_session.commit()

    resp = test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "racing", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# P3.1 follow-up fixes (2026-09-12): re-upload guard, filename round-trip,
# cross-facility pagination-before-filter, NULL-facility guard, catalog
# audit logging, service_result annotation facility-hiding.
# ---------------------------------------------------------------------------
def test_result_document_reupload_guard(test_client, make_user, auth_headers, db_session):
    """upload_result_document must refuse a second upload rather than
    silently replacing the object-store pointer (which would orphan the
    first file and violate the 'signed result is immutable' framing)."""
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()
    test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "see attached", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )

    resp1 = test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("report1.pdf", b"%PDF-1.4 first attempt", "application/pdf")},
        headers=auth_headers(clinician),
    )
    assert resp1.status_code == 200

    result_row = db_session.query(models.ServiceResult).filter_by(service_request_id=created["id"]).first()
    original_key = result_row.file_object_key
    assert original_key is not None

    resp2 = test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("report2.pdf", b"%PDF-1.4 second attempt", "application/pdf")},
        headers=auth_headers(clinician),
    )
    assert resp2.status_code == 409

    db_session.refresh(result_row)
    assert result_row.file_object_key == original_key


def test_result_document_filename_round_trip(test_client, make_user, auth_headers, db_session):
    """The downloaded Content-Disposition filename must survive an original
    filename that itself contains underscores -- the object key's
    id/filename separator is '/', not '_'."""
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician = make_user(role="clinician", facility=_facility("Facility A"))

    created = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician)
    ).json()
    test_client.post(
        f"/ancillary/requests/{created['id']}/result",
        json={"result_text": "see attached", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )
    test_client.post(
        f"/ancillary/requests/{created['id']}/result/document",
        files={"file": ("blood_test_results.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
        headers=auth_headers(clinician),
    )

    resp = test_client.get(f"/ancillary/requests/{created['id']}/result/document", headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert 'filename="blood_test_results.pdf"' in resp.headers.get("Content-Disposition", "")


def test_cross_facility_pagination_boundary(test_client, make_user, auth_headers, db_session):
    """A page must contain exactly `limit` VISIBLE rows, not `limit` raw
    rows minus whatever got stripped out after the fact -- the
    records_shared_publicly exclusion has to run in SQL before
    offset/limit, not in Python after."""
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    db_session.add(models.HospitalSetting(facility_name=facility_b, records_shared_publicly=False))
    db_session.commit()

    # Interleaved so order by created_at desc is A, B, A, B, A.
    for fac_user in (clinician_a, clinician_b, clinician_a, clinician_b, clinician_a):
        test_client.post(
            "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(fac_user)
        )
        time.sleep(0.01)  # distinct created_at for a stable sort order

    # Facility B's rows fall inside the naive first-3-rows window. If the
    # hidden-facility filter ran AFTER limit/offset (the bug this fixes),
    # this would come back with only 2 (of the 3 real) visible rows.
    resp = test_client.get(
        "/ancillary/requests", params={"patient_id": patient.id, "limit": 3}, headers=auth_headers(clinician_a)
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert all(r["ordering_facility_name"] == facility_a for r in rows)


def test_null_facility_guard(test_client, make_user, auth_headers, db_session):
    """A NULL ordering_facility_name row must be immutable to EVERYONE,
    including a facility-less (platform/bootstrap) admin -- `None != None`
    must not silently bypass the same-facility write guard."""
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)

    req = models.ServiceRequest(
        patient_id=patient.id,
        module="laboratory",
        catalog_item_id=item.id,
        source="frontdesk",
        priority="routine",
        unit_price_cents=1000,
        ordering_facility_name=None,
    )
    db_session.add(req)
    db_session.commit()

    admin = make_user(role="admin", facility=None)

    resp = test_client.post(
        f"/ancillary/requests/{req.id}/cancel", json={"reason": "test"}, headers=auth_headers(admin)
    )
    assert resp.status_code == 404

    resp = test_client.post(
        f"/ancillary/requests/{req.id}/result",
        json={"result_text": "x", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404


def test_catalog_audit_logging(test_client, make_user, auth_headers, db_session):
    """Catalog create/update are billing-relevant (unit_price_cents feeds
    P3.3) and must leave an audit trail like every other write in this
    router."""
    facility_a = _facility("Facility A")
    admin = make_user(role="admin", facility=facility_a)

    body = {"module": "laboratory", "name": "Audit Test Item", "unit_price_cents": 1000, "facility_name": facility_a}
    resp = test_client.post("/ancillary/catalog", json=body, headers=auth_headers(admin))
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    created_row = (
        db_session.query(models.AuditLog)
        .filter_by(action="ancillary_catalog_item_created", actor=admin.id)
        .order_by(models.AuditLog.id.desc())
        .first()
    )
    assert created_row is not None
    assert item_id in created_row.detail

    resp = test_client.patch(f"/ancillary/catalog/{item_id}", json={"active": False}, headers=auth_headers(admin))
    assert resp.status_code == 200

    updated_row = (
        db_session.query(models.AuditLog)
        .filter_by(action="ancillary_catalog_item_updated", actor=admin.id)
        .order_by(models.AuditLog.id.desc())
        .first()
    )
    assert updated_row is not None
    assert item_id in updated_row.detail


def test_service_result_annotation_facility_hiding(test_client, make_user, auth_headers, db_session):
    """A 'correction' annotation on a ServiceResult from a facility that has
    opted out of cross-facility sharing must be hidden from other
    facilities' annotation reads, same as the result itself already is
    through the ancillary endpoints -- but never hidden from the
    authoring facility's own view."""
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    req_a = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician_a)
    ).json()
    res_a = test_client.post(
        f"/ancillary/requests/{req_a['id']}/result",
        json={"result_text": "res a", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician_a),
    ).json()

    resp = test_client.post(
        f"/patients/{patient.id}/annotations",
        json={"target_type": "service_result", "target_id": res_a["result"]["id"], "kind": "correction", "note": "oops"},
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
