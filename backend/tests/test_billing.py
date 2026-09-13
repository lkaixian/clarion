"""P3.3 billing module (routers/billing.py) — RBAC, cross-facility scoping,
pricing snapshots, copay arithmetic, and bill/claim lifecycles.
"""
from app import models
from conftest import _facility, _make_patient


def _make_charge_master(db_session, category="consultation", facility_name=None, **overrides):
    item = models.ChargeMasterItem(
        category=category,
        name=overrides.pop("name", "Standard Consultation"),
        unit_price_cents=overrides.pop("unit_price_cents", 5000),
        facility_name=facility_name,
        **overrides,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _make_service_request(db_session, patient_id, facility_name, status="signed_off", **overrides):
    cat = models.ServiceCatalogItem(module="laboratory", name="Blood Test", unit_price_cents=10000)
    db_session.add(cat)
    db_session.commit()

    req = models.ServiceRequest(
        patient_id=patient_id,
        module="laboratory",
        catalog_item_id=cat.id,
        source="frontdesk",
        status=status,
        unit_price_cents=cat.unit_price_cents,
        ordering_facility_name=facility_name,
        **overrides,
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)
    return req


def _make_pharmacy_item(db_session, facility_name, **overrides):
    item = models.MedicineInventoryItem(
        facility_name=facility_name,
        drug_name=overrides.pop("drug_name", "Paracetamol"),
        quantity_on_hand=100,
        unit="units",
        unit_cost=overrides.pop("unit_cost", 1.50),
        **overrides
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _create_bill_body(patient_id, encounter_id=None):
    body = {"patient_id": patient_id}
    if encounter_id:
        body["encounter_id"] = encounter_id
    return body


# ---------------------------------------------------------------------------
# Charge Master
# ---------------------------------------------------------------------------
def test_charge_master_global_vs_facility_visibility(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    _make_charge_master(db_session, name="Global Consult", facility_name=None)
    _make_charge_master(db_session, name="Facility A Consult", facility_name=facility_a)

    user_a = make_user(role="receptionist", facility=facility_a)
    user_b = make_user(role="receptionist", facility=facility_b)

    resp_a = test_client.get("/billing/charge-master", headers=auth_headers(user_a))
    assert resp_a.status_code == 200
    names_a = {i["name"] for i in resp_a.json()}
    assert "Global Consult" in names_a
    assert "Facility A Consult" in names_a

    resp_b = test_client.get("/billing/charge-master", headers=auth_headers(user_b))
    assert resp_b.status_code == 200
    names_b = {i["name"] for i in resp_b.json()}
    assert "Global Consult" in names_b
    assert "Facility A Consult" not in names_b


def test_charge_master_create_rbac(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    admin = make_user(role="admin", facility=facility)
    records = make_user(role="records_officer", facility=facility)
    receptionist = make_user(role="receptionist", facility=facility)
    clinician = make_user(role="clinician", facility=facility)
    pharmacist = make_user(role="pharmacist", facility=facility)

    body = {"category": "consultation", "name": "New Consult", "unit_price_cents": 2000, "facility_name": "Other"}

    resp = test_client.post("/billing/charge-master", json=body, headers=auth_headers(records))
    assert resp.status_code == 201
    assert resp.json()["facility_name"] == facility

    for user in (receptionist, clinician, pharmacist):
        assert test_client.post("/billing/charge-master", json=body, headers=auth_headers(user)).status_code == 403

    resp = test_client.post("/billing/charge-master", json={**body, "facility_name": None}, headers=auth_headers(admin))
    assert resp.status_code == 201
    assert resp.json()["facility_name"] is None

    assert test_client.post("/billing/charge-master", json={**body, "facility_name": _facility("B")}, headers=auth_headers(admin)).status_code == 403


def test_charge_master_patch_ownership(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    item_a = _make_charge_master(db_session, facility_name=facility_a)
    global_item = _make_charge_master(db_session, facility_name=None, name="Global")

    admin_a = make_user(role="admin", facility=facility_a)
    admin_b = make_user(role="admin", facility=facility_b)

    resp = test_client.patch(f"/billing/charge-master/{item_a.id}", json={"unit_price_cents": 100}, headers=auth_headers(admin_b))
    assert resp.status_code == 404

    resp = test_client.patch(f"/billing/charge-master/{item_a.id}", json={"unit_price_cents": 100}, headers=auth_headers(admin_a))
    assert resp.status_code == 200
    assert resp.json()["unit_price_cents"] == 100

    assert test_client.patch(f"/billing/charge-master/{global_item.id}", json={"unit_price_cents": 150}, headers=auth_headers(admin_a)).status_code == 200


# ---------------------------------------------------------------------------
# Bills & Items
# ---------------------------------------------------------------------------
def test_create_bill_rbac(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    
    for role in ("admin", "records_officer", "receptionist"):
        user = make_user(role=role, facility=facility)
        resp = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(user))
        assert resp.status_code == 201, role
        
    for role in ("clinician", "pharmacist"):
        user = make_user(role=role, facility=facility)
        resp = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(user))
        assert resp.status_code == 403, role


def test_create_bill_validates_encounter_patient(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient1 = _make_patient(db_session)
    patient2 = _make_patient(db_session, full_name="Someone Else")
    receptionist = make_user(role="receptionist", facility=facility)

    encounter = models.Encounter(patient_id=patient2.id, facility_name=facility, encounter_type="outpatient")
    db_session.add(encounter)
    db_session.commit()

    resp = test_client.post("/billing/bills", json=_create_bill_body(patient1.id, encounter.id), headers=auth_headers(receptionist))
    assert resp.status_code == 404


def test_list_bills_facility_scoped(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    receptionist_a = make_user(role="receptionist", facility=facility_a)
    receptionist_b = make_user(role="receptionist", facility=facility_b)

    test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist_a))

    resp_a = test_client.get("/billing/bills", headers=auth_headers(receptionist_a))
    assert len(resp_a.json()) == 1

    resp_b = test_client.get("/billing/bills", headers=auth_headers(receptionist_b))
    assert len(resp_b.json()) == 0


def test_add_bill_items_charge_master_price_snapshot(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=3000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()

    payload = {"source_type": "charge_master", "charge_master_item_id": cm_item.id, "quantity": 2}
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json=payload, headers=auth_headers(receptionist))
    assert resp.status_code == 201
    
    b_items = resp.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["unit_price_cents"] == 3000
    assert b_items[0]["amount_cents"] == 6000

    cm_item.unit_price_cents = 4000
    db_session.commit()

    resp = test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(receptionist))
    assert resp.json()["items"][0]["unit_price_cents"] == 3000


def test_add_bill_items_service_request_price_snapshot(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    req = _make_service_request(db_session, patient.id, facility, status="signed_off")

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()

    payload = {"source_type": "service_request", "service_request_id": req.id, "quantity": 1}
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json=payload, headers=auth_headers(receptionist))
    assert resp.status_code == 201
    
    b_items = resp.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["unit_price_cents"] == req.unit_price_cents


def test_add_bill_items_service_request_guards(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    receptionist_a = make_user(role="receptionist", facility=facility_a)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist_a)).json()

    req_ordered = _make_service_request(db_session, patient.id, facility_a, status="ordered")
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "service_request", "service_request_id": req_ordered.id}, headers=auth_headers(receptionist_a))
    assert resp.status_code == 400

    req_other_fac = _make_service_request(db_session, patient.id, facility_b, status="signed_off")
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "service_request", "service_request_id": req_other_fac.id}, headers=auth_headers(receptionist_a))
    assert resp.status_code == 404

    req_good = _make_service_request(db_session, patient.id, facility_a, status="signed_off")
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "service_request", "service_request_id": req_good.id}, headers=auth_headers(receptionist_a))
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "service_request", "service_request_id": req_good.id}, headers=auth_headers(receptionist_a))
    assert resp.status_code == 409


def test_add_bill_items_pharmacy_item_price_snapshot(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    inv = _make_pharmacy_item(db_session, facility, unit_cost=12.50)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()

    payload = {"source_type": "pharmacy_item", "medicine_inventory_item_id": inv.id, "quantity": 1}
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json=payload, headers=auth_headers(receptionist))
    assert resp.status_code == 201
    
    b_items = resp.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["unit_price_cents"] == 1250


def test_add_bill_items_pharmacy_item_null_cost_rejected(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    inv = _make_pharmacy_item(db_session, facility, unit_cost=None)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()

    payload = {"source_type": "pharmacy_item", "medicine_inventory_item_id": inv.id, "quantity": 1}
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json=payload, headers=auth_headers(receptionist))
    assert resp.status_code == 400


def test_add_bill_item_to_finalized_bill_rejected(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(receptionist))
    test_client.post(f"/billing/bills/{bill['id']}/finalize", headers=auth_headers(receptionist))

    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(receptionist))
    assert resp.status_code == 400


def test_void_bill_item(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()
    resp = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(receptionist))
    item_id = resp.json()["items"][0]["id"]

    resp = test_client.post(f"/billing/bills/{bill['id']}/items/{item_id}/void", json={"reason": "mistake"}, headers=auth_headers(receptionist))
    assert resp.status_code == 200
    assert resp.json()["items"][0]["voided_at"] is not None


# ---------------------------------------------------------------------------
# Bill lifecycle
# ---------------------------------------------------------------------------
def test_finalize_bill_happy_path(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(receptionist))

    resp = test_client.post(f"/billing/bills/{bill['id']}/finalize", headers=auth_headers(receptionist))
    assert resp.status_code == 200
    assert resp.json()["status"] == "finalized"


def test_finalize_bill_zero_items_rejected(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()

    resp = test_client.post(f"/billing/bills/{bill['id']}/finalize", headers=auth_headers(receptionist))
    assert resp.status_code == 400


def test_void_bill(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()
    resp = test_client.post(f"/billing/bills/{bill['id']}/void", json={"reason": "abandoned"}, headers=auth_headers(receptionist))
    assert resp.status_code == 200
    assert resp.json()["status"] == "voided"

    resp = test_client.post(f"/billing/bills/{bill['id']}/void", json={"reason": "abandoned"}, headers=auth_headers(receptionist))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def test_record_payment_updates_amount_due(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    receptionist = make_user(role="receptionist", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(receptionist)).json()
    bill = test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(receptionist)).json()
    assert bill["amount_due_cents"] == 5000
    assert bill["patient_due_cents"] == 5000

    bill = test_client.post(f"/billing/bills/{bill['id']}/payments", json={"amount_cents": 2000, "method": "cash"}, headers=auth_headers(receptionist)).json()
    assert bill["paid_cents"] == 2000
    assert bill["amount_due_cents"] == 3000
    assert bill["patient_due_cents"] == 3000


def test_record_payment_with_claim_requires_insurance_panel(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 5000}, headers=auth_headers(records)).json()
    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))

    resp = test_client.post(f"/billing/bills/{bill['id']}/payments", json={"amount_cents": 5000, "method": "cash", "claim_id": claim['id']}, headers=auth_headers(records))
    assert resp.status_code == 422


def test_void_payment_reverts_amount_due_and_claim_status(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 5000}, headers=auth_headers(records)).json()
    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))
    test_client.post(f"/billing/claims/{claim['id']}/approve", headers=auth_headers(records))
    
    bill = test_client.post(f"/billing/bills/{bill['id']}/payments", json={"amount_cents": 5000, "method": "insurance", "claim_id": claim['id']}, headers=auth_headers(records)).json()
    assert bill["amount_due_cents"] == 0
    assert bill["claims"][0]["status"] == "paid"

    payment_id = bill["payments"][0]["id"]
    bill = test_client.post(f"/billing/payments/{payment_id}/void", json={"reason": "bounced"}, headers=auth_headers(records)).json()
    
    assert bill["amount_due_cents"] == 5000
    assert bill["claims"][0]["status"] == "approved"


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
def test_create_claim_rbac(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    receptionist = make_user(role="receptionist", facility=facility)
    clinician = make_user(role="clinician", facility=facility)
    pharmacist = make_user(role="pharmacist", facility=facility)
    
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)
    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))

    resp = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 1000}, headers=auth_headers(records))
    assert resp.status_code == 201

    for user in (receptionist, clinician, pharmacist):
        assert test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 1000}, headers=auth_headers(user)).status_code == 403


def test_create_claim_cannot_exceed_amount_due(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))

    resp = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 6000}, headers=auth_headers(records))
    assert resp.status_code == 400


def test_claim_patch_blocked_on_voided_bill(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 1000}, headers=auth_headers(records)).json()

    test_client.post(f"/billing/bills/{bill['id']}/void", json={"reason": "abandoned"}, headers=auth_headers(records))

    resp = test_client.patch(f"/billing/claims/{claim['id']}", json={"claim_amount_cents": 2000}, headers=auth_headers(records))
    assert resp.status_code == 400


def test_claim_patch_allowed_only_in_draft(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 1000}, headers=auth_headers(records)).json()

    resp = test_client.patch(f"/billing/claims/{claim['id']}", json={"claim_amount_cents": 2000}, headers=auth_headers(records))
    assert resp.status_code == 200
    assert resp.json()["claim_amount_cents"] == 2000

    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))
    
    resp = test_client.patch(f"/billing/claims/{claim['id']}", json={"claim_amount_cents": 3000}, headers=auth_headers(records))
    assert resp.status_code == 400


def test_claim_copay_arithmetic_draft_and_submitted(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))

    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 3000}, headers=auth_headers(records)).json()
    
    bill = test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(records)).json()
    assert bill["amount_due_cents"] == 5000
    assert bill["claimed_pending_cents"] == 0
    assert bill["patient_due_cents"] == 5000

    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))
    
    bill = test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(records)).json()
    assert bill["amount_due_cents"] == 5000
    assert bill["claimed_pending_cents"] == 3000
    assert bill["patient_due_cents"] == 2000


def test_claim_copay_arithmetic_rejected_and_voided(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 3000}, headers=auth_headers(records)).json()
    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))
    
    test_client.post(f"/billing/claims/{claim['id']}/reject", json={"reason": "policy lapsed"}, headers=auth_headers(records))

    bill = test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(records)).json()
    assert bill["amount_due_cents"] == 5000
    assert bill["claimed_pending_cents"] == 0
    assert bill["patient_due_cents"] == 5000


def test_claim_cannot_double_claim_full_amount_once_first_is_submitted(test_client, make_user, auth_headers, db_session):
    """Security-review regression: the claim-amount cap must net out
    already-submitted/approved claims (patient_due_cents), not just raw
    amount_due_cents -- otherwise a second insurer could be claimed the
    full bill value even though a first claim already covers it."""
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))

    claim1 = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 5000}, headers=auth_headers(records)).json()
    test_client.post(f"/billing/claims/{claim1['id']}/submit", headers=auth_headers(records))

    resp = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "Prudential", "claim_amount_cents": 5000}, headers=auth_headers(records))
    assert resp.status_code == 400

    resp = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "Prudential", "claim_amount_cents": 1}, headers=auth_headers(records))
    assert resp.status_code == 400


def test_multiple_partial_claims_sum_correctly(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=10000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))

    c1 = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 3000}, headers=auth_headers(records)).json()
    c2 = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "Prudential", "claim_amount_cents": 4000}, headers=auth_headers(records)).json()
    
    test_client.post(f"/billing/claims/{c1['id']}/submit", headers=auth_headers(records))
    test_client.post(f"/billing/claims/{c2['id']}/submit", headers=auth_headers(records))

    bill = test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(records)).json()
    assert bill["claimed_pending_cents"] == 7000
    assert bill["patient_due_cents"] == 3000


def test_claim_status_transition_guards(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    patient = _make_patient(db_session)
    records = make_user(role="records_officer", facility=facility)
    cm_item = _make_charge_master(db_session, facility_name=facility, unit_price_cents=5000)

    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records))
    claim = test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 1000}, headers=auth_headers(records)).json()

    assert test_client.post(f"/billing/claims/{claim['id']}/reject", json={"reason": "x"}, headers=auth_headers(records)).status_code == 400
    
    assert test_client.post(f"/billing/claims/{claim['id']}/approve", headers=auth_headers(records)).status_code == 400

    test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records))
    
    assert test_client.post(f"/billing/claims/{claim['id']}/submit", headers=auth_headers(records)).status_code == 400
    
    test_client.post(f"/billing/claims/{claim['id']}/approve", headers=auth_headers(records))
    # "paid" is only reachable via a linked, amount-matched Payment now --
    # there is no standalone mark-paid status flip (security/quality-review
    # fix: that flip let a claim be "paid" with no money actually recorded,
    # so patient_due_cents would snap back up on the very next read).
    resp = test_client.post(f"/billing/bills/{bill['id']}/payments", json={"amount_cents": 1000, "method": "insurance", "claim_id": claim["id"]}, headers=auth_headers(records))
    assert resp.json()["claims"][0]["status"] == "paid"

    assert test_client.post(f"/billing/claims/{claim['id']}/void", json={"reason": "x"}, headers=auth_headers(records)).status_code == 400


# ---------------------------------------------------------------------------
# Cross-facility isolation
# ---------------------------------------------------------------------------
def test_cross_facility_bill_read_write_denied_with_404(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("Facility A"), _facility("Facility B")
    patient = _make_patient(db_session)
    records_a = make_user(role="records_officer", facility=facility_a)
    records_b = make_user(role="records_officer", facility=facility_b)

    cm_item = _make_charge_master(db_session, facility_name=facility_a, unit_price_cents=5000)
    bill = test_client.post("/billing/bills", json=_create_bill_body(patient.id), headers=auth_headers(records_a)).json()
    test_client.post(f"/billing/bills/{bill['id']}/items", json={"source_type": "charge_master", "charge_master_item_id": cm_item.id}, headers=auth_headers(records_a))

    assert test_client.get(f"/billing/bills/{bill['id']}", headers=auth_headers(records_b)).status_code == 404
    
    assert test_client.post(f"/billing/bills/{bill['id']}/finalize", headers=auth_headers(records_b)).status_code == 404
    assert test_client.post(f"/billing/bills/{bill['id']}/payments", json={"amount_cents": 5000, "method": "cash"}, headers=auth_headers(records_b)).status_code == 404
    assert test_client.post(f"/billing/bills/{bill['id']}/claims", json={"payer_name": "AIA", "claim_amount_cents": 5000}, headers=auth_headers(records_b)).status_code == 404


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def test_billing_stats_rbac_and_shape(test_client, make_user, auth_headers, db_session):
    facility = _facility("Facility A")
    receptionist = make_user(role="receptionist", facility=facility)
    resp = test_client.get("/billing/stats", headers=auth_headers(receptionist))
    assert resp.status_code == 200
    
    data = resp.json()
    assert "total_billed_cents" in data
    assert "bills_by_status" in data
    assert "open" in data["bills_by_status"]
