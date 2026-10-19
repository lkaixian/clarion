"""HIS dataset features: coded demographics, sponsors, dependants, bed movement history, CPOE
orders, purchasing, clinical forms."""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import models
from conftest import _facility, _make_patient


class Env:
    """One facility with an admin, clinician, pharmacist, receptionist and a patient the
    facility has dealt with (an encounter), plus a second facility's admin and clinician."""

    def __init__(self, test_client, make_user, auth_headers, db):
        self.c, self.db, self._auth, self._h = test_client, db, auth_headers, {}
        self.fac = _facility("His")
        self.other = _facility("HisOther")
        self.admin = make_user(role="admin", facility=self.fac, full_name="Admin A")
        self.doc = make_user(role="clinician", facility=self.fac, full_name="Doc A")
        self.doc2 = make_user(role="clinician", facility=self.fac, full_name="Doc B")
        self.pharm = make_user(role="pharmacist", facility=self.fac, full_name="Pharm A")
        self.recep = make_user(role="receptionist", facility=self.fac, full_name="Recep A")
        self.o_admin = make_user(role="admin", facility=self.other, full_name="Admin B")
        self.o_doc = make_user(role="clinician", facility=self.other, full_name="Doc Other")
        self.patient = self.known_patient("Pat One")
        self.pat_user = make_user(role="patient", patient_id=self.patient.id, facility=None)

    def known_patient(self, name):
        p = _make_patient(self.db, full_name=name)
        self.db.add(models.Encounter(patient_id=p.id, facility_name=self.fac, encounter_type="outpatient"))
        self.db.commit()
        return p

    def h(self, user):
        if user.id not in self._h:
            self._h[user.id] = self._auth(user)
        return self._h[user.id]


@pytest.fixture
def env(test_client, make_user, auth_headers, db_session):
    return Env(test_client, make_user, auth_headers, db_session)


def first_code(db, kind):
    return db.query(models.ReferenceCode).filter_by(kind=kind).order_by(models.ReferenceCode.code).first().code


# ---------------------------------------------------------------- demographics

def test_create_patient_accepts_valid_codes_and_fills_city_and_state_from_postcode(env):
    r = env.c.post("/patients", headers=env.h(env.admin), json={
        "full_name": "Coded Person", "date_of_birth": "1985-02-03", "religion_code": "1", "race_code": first_code(env.db, "races"),
        "marital_code": "2", "postcode": "83020", "address_line": "1 Jalan Satu"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["religion_code"] == "1" and body["postcode"] == "83020"
    assert body["city"] == "Batu Pahat" and body["state_code"] == "johor"


def test_unknown_codes_are_refused_with_the_field_named(env):
    r = env.c.post("/patients", headers=env.h(env.admin), json={
        "full_name": "Bad Code", "date_of_birth": "1985-02-03", "religion_code": "no-such"})
    assert r.status_code == 422 and "religion" in r.json()["detail"]
    r = env.c.post("/patients", headers=env.h(env.admin), json={
        "full_name": "Bad Sponsor", "date_of_birth": "1985-02-03", "sponsor_code": "NOPE"})
    assert r.status_code == 422 and "sponsor" in r.json()["detail"]


def test_demographics_edit_is_facility_scoped_audited_and_never_touches_identity(env):
    url = f"/patients/{env.patient.id}/demographics"
    r = env.c.patch(url, headers=env.h(env.recep), json={"nation_code": "MYS", "city": "Johor Bahru"})
    assert r.status_code == 200 and r.json()["nation_code"] == "MYS" and r.json()["city"] == "Johor Bahru"
    # a facility that never dealt with the patient gets a 404
    assert env.c.patch(url, headers=env.h(env.o_doc), json={"city": "X"}).status_code == 404
    # identity fields are not part of this endpoint
    assert env.c.patch(url, headers=env.h(env.admin), json={"full_name": "Renamed"}).status_code == 422
    # a patient cannot use the staff endpoint
    assert env.c.patch(url, headers=env.h(env.pat_user), json={"city": "X"}).status_code == 403
    # clearing a field works
    r = env.c.patch(url, headers=env.h(env.admin), json={"city": ""})
    assert r.json()["city"] is None
    log = env.db.query(models.AuditLog).filter_by(patient_id=env.patient.id, action="update_demographics").all()
    assert log and all("Johor" not in str(a.detail) for a in log)
    assert env.db.get(models.Patient, env.patient.id).full_name == "Pat One"


def test_full_record_carries_demographics(env):
    env.c.patch(f"/patients/{env.patient.id}/demographics", headers=env.h(env.admin), json={"marital_code": "1"})
    rec = env.c.get(f"/patients/{env.patient.id}", headers=env.h(env.doc)).json()
    assert rec["demographics"]["marital_code"] == "1"


# ---------------------------------------------------------------- sponsors, dependants

def test_sponsors_admin_writes_staff_reads_patient_blocked(env):
    body = {"code": f"SP{uuid.uuid4().hex[:6]}", "name": "Acme Health Plan", "entitlement_code": "A"}
    assert env.c.post("/sponsors", headers=env.h(env.doc), json=body).status_code == 403
    r = env.c.post("/sponsors", headers=env.h(env.admin), json=body)
    assert r.status_code == 201, r.text
    assert env.c.post("/sponsors", headers=env.h(env.admin), json=body).status_code == 409
    assert env.c.post("/sponsors", headers=env.h(env.admin),
                      json={**body, "code": "X1", "entitlement_code": "ZZZ"}).status_code == 422
    assert body["code"] in [s["code"] for s in env.c.get("/sponsors", headers=env.h(env.recep)).json()]
    assert env.c.get("/sponsors", headers=env.h(env.pat_user)).status_code == 403
    # a patient can be put under that sponsor, and an inactive one is refused afterwards
    ok = env.c.patch(f"/patients/{env.patient.id}/demographics", headers=env.h(env.admin),
                     json={"sponsor_code": body["code"], "sponsor_member_no": "M-77"})
    assert ok.status_code == 200 and ok.json()["sponsor_code"] == body["code"]
    env.c.patch(f"/sponsors/{r.json()['id']}", headers=env.h(env.admin), json={"active": False})
    assert env.c.patch(f"/patients/{env.patient.id}/demographics", headers=env.h(env.admin),
                       json={"sponsor_code": body["code"]}).status_code == 422


def test_dependants_link_list_unlink_with_guards(env):
    kid = env.known_patient("Kid One")
    stranger = _make_patient(env.db, full_name="Not Ours")
    base = f"/patients/{env.patient.id}/dependants"
    r = env.c.post(base, headers=env.h(env.recep), json={"dependant_id": kid.id, "relation_code": "1"})
    assert r.status_code == 201, r.text
    assert env.c.post(base, headers=env.h(env.recep), json={"dependant_id": kid.id}).status_code == 409
    assert env.c.post(base, headers=env.h(env.recep), json={"dependant_id": env.patient.id}).status_code == 400
    assert env.c.post(base, headers=env.h(env.recep), json={"dependant_id": stranger.id}).status_code == 404
    assert env.c.post(base, headers=env.h(env.recep),
                      json={"dependant_id": kid.id, "relation_code": "zz"}).status_code == 422
    rows = env.c.get(base, headers=env.h(env.doc)).json()
    assert [(x["dependant_name"], x["relation"]) for x in rows] == [("Kid One", "Child")]
    assert env.c.get(base, headers=env.h(env.o_doc)).status_code == 404
    assert env.c.delete(f"{base}/{rows[0]['id']}", headers=env.h(env.recep)).status_code == 204
    assert env.c.get(base, headers=env.h(env.doc)).json() == []


# ---------------------------------------------------------------- bed movements

def test_admission_records_bed_history(env):
    ward = models.Ward(facility_name=env.fac, ward_name="Ward 7", ward_type="general", total_beds=4)
    env.db.add(ward)
    env.db.commit()
    r = env.c.post("/reception/admissions", headers=env.h(env.recep),
                   json={"patient_id": env.patient.id, "ward_id": ward.id, "bed_number": 1})
    assert r.status_code == 200, r.text
    adm = r.json()["id"]
    assert env.c.patch(f"/reception/admissions/{adm}", headers=env.h(env.recep), json={"bed_number": 3}).status_code == 200
    env.c.patch(f"/reception/admissions/{adm}", headers=env.h(env.recep), json={"notes": "just a note"})
    moves = env.c.get(f"/reception/admissions/{adm}/movements", headers=env.h(env.recep)).json()
    assert [(m["from_bed_number"], m["to_bed_number"]) for m in moves] == [(None, 1), (1, 3)]
    assert moves[0]["to_ward_name"] == "Ward 7"
    assert env.c.get(f"/reception/admissions/{adm}/movements", headers=env.h(env.o_doc)).status_code in (403, 404)


# ---------------------------------------------------------------- CPOE orders

def _drug_order(env, **over):
    body = {"order_type": "drug", "description": "Paracetamol 500mg", "quantity": 20, "dosage": "1 tab",
            "route_code": first_code(env.db, "drug_routes"), **over}
    return env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc), json=body)


def test_order_creation_validates_and_defaults_from_product(env):
    prod = env.db.query(models.Product).first()
    r = env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc),
                   json={"order_type": "investigation", "product_code": prod.product_code,
                         "urgency_code": first_code(env.db, "urgencies")})
    assert r.status_code == 201, r.text
    assert r.json()["description"] == prod.product_name and r.json()["status"] == "ordered"
    bad = [
        {"order_type": "wizardry", "description": "x"},
        {"order_type": "drug"},
        {"order_type": "drug", "description": "x", "product_code": "NOPE-CODE"},
        {"order_type": "drug", "description": "x", "route_code": "nope"},
        {"order_type": "drug", "description": "x", "encounter_id": str(uuid.uuid4())},
        {"order_type": "drug", "description": "x", "quantity": 0},
    ]
    for body in bad:
        assert env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc), json=body).status_code == 422, body
    # only ordering roles
    assert env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.pharm),
                      json={"order_type": "drug", "description": "x"}).status_code == 403
    assert env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.pat_user),
                      json={"order_type": "drug", "description": "x"}).status_code == 403


def test_drug_order_lifecycle_and_who_may_complete(env):
    oid = _drug_order(env).json()["id"]
    assert env.c.post(f"/orders/{oid}/complete", headers=env.h(env.doc), json={}).status_code == 403
    done = env.c.post(f"/orders/{oid}/complete", headers=env.h(env.pharm), json={"note": "dispensed"})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert done.json()["completed_by_name"] == "Pharm A"
    # second completion and a cancel after completion both lose
    assert env.c.post(f"/orders/{oid}/complete", headers=env.h(env.pharm), json={}).status_code == 409
    assert env.c.post(f"/orders/{oid}/cancel", headers=env.h(env.doc), json={"reason": "x"}).status_code == 409


def test_cancel_is_for_the_orderer_or_admin_and_needs_a_reason(env):
    oid = _drug_order(env).json()["id"]
    assert env.c.post(f"/orders/{oid}/cancel", headers=env.h(env.doc2), json={"reason": "mine now"}).status_code == 403
    assert env.c.post(f"/orders/{oid}/cancel", headers=env.h(env.doc), json={"reason": ""}).status_code == 422
    r = env.c.post(f"/orders/{oid}/cancel", headers=env.h(env.doc), json={"reason": "wrong patient"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "wrong patient"
    assert env.c.post(f"/orders/{oid}/complete", headers=env.h(env.pharm), json={}).status_code == 409
    oid2 = _drug_order(env).json()["id"]
    assert env.c.post(f"/orders/{oid2}/cancel", headers=env.h(env.admin), json={"reason": "audit"}).status_code == 200


def test_orders_are_facility_local_and_pharmacists_see_drugs_only(env):
    drug = _drug_order(env).json()["id"]
    inv = env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc),
                     json={"order_type": "investigation", "description": "FBC"}).json()["id"]
    # the other facility sees nothing and cannot act
    assert env.c.get("/orders", headers=env.h(env.o_doc)).json() == []
    assert env.c.post(f"/orders/{drug}/cancel", headers=env.h(env.o_admin), json={"reason": "x"}).status_code == 404
    assert env.c.get(f"/patients/{env.patient.id}/orders", headers=env.h(env.o_doc)).json() == []
    mine = {o["id"] for o in env.c.get("/orders", headers=env.h(env.doc)).json()}
    assert {drug, inv} <= mine
    pharm = {o["id"] for o in env.c.get("/orders", headers=env.h(env.pharm)).json()}
    assert drug in pharm and inv not in pharm
    assert env.c.post(f"/orders/{inv}/complete", headers=env.h(env.pharm), json={}).status_code == 403
    assert env.c.post(f"/orders/{inv}/complete", headers=env.h(env.doc), json={"note": "done"}).status_code == 200
    assert env.c.get("/orders", headers=env.h(env.pat_user)).status_code == 403


def test_stat_orders_come_first_in_the_worklist(env):
    a = _drug_order(env, description="routine one").json()["id"]
    b = _drug_order(env, description="urgent one", is_stat=True).json()["id"]
    ids = [o["id"] for o in env.c.get("/orders", headers=env.h(env.pharm)).json()]
    assert ids.index(b) < ids.index(a)


# ---------------------------------------------------------------- purchasing

def _item(env, name="Amoxicillin 250mg", qty=10, cost=0.5):
    it = models.MedicineInventoryItem(facility_name=env.fac, drug_name=name, quantity_on_hand=qty, unit="caps",
                                      unit_cost=cost)
    env.db.add(it)
    env.db.commit()
    return it


def _supplier(env):
    r = env.c.post("/purchasing/suppliers", headers=env.h(env.admin),
                   json={"code": f"S{uuid.uuid4().hex[:5]}", "name": "MedSupply Sdn Bhd"})
    assert r.status_code == 201, r.text
    return r.json()


def _po(env, item, qty=100, cost=0.4, user=None):
    sup = _supplier(env)
    r = env.c.post("/purchasing/orders", headers=env.h(user or env.pharm), json={
        "supplier_id": sup["id"], "lines": [{"item_id": item.id, "quantity": qty, "unit_cost": cost}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_purchase_flow_pharmacist_drafts_admin_places_goods_restock_once(env):
    item = _item(env)
    po = _po(env, item)
    assert po["status"] == "draft" and po["total_cost"] == 40.0 and po["po_number"].startswith("PO-")
    line = po["lines"][0]["id"]
    recv = lambda qty, **kw: env.c.post(f"/purchasing/orders/{po['id']}/receive", headers=env.h(env.pharm),  # noqa: E731
                                        json={"lines": [{"line_id": line, "quantity": qty, **kw}]})
    # not placed yet: nothing can be received, and a pharmacist cannot place it
    assert recv(10).status_code == 409
    assert env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.pharm)).status_code == 403
    assert env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.admin)).json()["status"] == "ordered"
    assert env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.admin)).status_code == 409

    assert recv(101).status_code == 422                      # more than ordered
    assert recv(10, expiry_date="31/12/2027").status_code == 422
    r = recv(60, batch_number="B-1", expiry_date="2027-12-31")
    assert r.status_code == 200 and r.json()["status"] == "partially_received"
    env.db.expire_all()
    assert env.db.get(models.MedicineInventoryItem, item.id).quantity_on_hand == 70
    assert recv(41).status_code == 422                       # only 40 left
    r = recv(40)
    assert r.json()["status"] == "received" and r.json()["closed_at"]
    env.db.expire_all()
    assert env.db.get(models.MedicineInventoryItem, item.id).quantity_on_hand == 110
    assert recv(1).status_code == 409
    budget = env.db.query(models.MedicineBudget).filter_by(facility_name=env.fac).first()
    assert round(budget.procurement_spend, 2) == 40.0
    events = env.db.query(models.MedicineStockEvent).filter_by(item_id=item.id, kind="restock").count()
    assert events == 2


def test_cancel_rules_and_facility_isolation(env):
    item = _item(env, "Cetirizine")
    po = _po(env, item)
    assert env.c.get(f"/purchasing/orders/{po['id']}", headers=env.h(env.o_admin)).status_code == 404
    assert env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.o_admin)).status_code == 404
    assert env.c.post(f"/purchasing/orders/{po['id']}/cancel", headers=env.h(env.pharm)).status_code == 403
    env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.admin))
    line = po["lines"][0]["id"]
    env.c.post(f"/purchasing/orders/{po['id']}/receive", headers=env.h(env.pharm),
               json={"lines": [{"line_id": line, "quantity": 1}]})
    assert env.c.post(f"/purchasing/orders/{po['id']}/cancel", headers=env.h(env.admin)).status_code == 409
    po2 = _po(env, item)
    assert env.c.post(f"/purchasing/orders/{po2['id']}/cancel", headers=env.h(env.admin)).json()["status"] == "cancelled"
    assert env.c.post(f"/purchasing/orders/{po2['id']}/place", headers=env.h(env.admin)).status_code == 409


def test_po_rejects_foreign_items_and_inactive_suppliers(env):
    foreign = models.MedicineInventoryItem(facility_name=env.other, drug_name="Theirs", quantity_on_hand=1, unit="u")
    env.db.add(foreign)
    env.db.commit()
    sup = _supplier(env)
    r = env.c.post("/purchasing/orders", headers=env.h(env.pharm),
                   json={"supplier_id": sup["id"], "lines": [{"item_id": foreign.id, "quantity": 1}]})
    assert r.status_code == 422
    env.c.patch(f"/purchasing/suppliers/{sup['id']}", headers=env.h(env.admin), json={"active": False})
    mine = _item(env, "Mine")
    r = env.c.post("/purchasing/orders", headers=env.h(env.pharm),
                   json={"supplier_id": sup["id"], "lines": [{"item_id": mine.id, "quantity": 1}]})
    assert r.status_code == 422
    assert env.c.post("/purchasing/suppliers", headers=env.h(env.pharm),
                      json={"code": "Z", "name": "z"}).status_code == 403
    assert env.c.get("/purchasing/suppliers", headers=env.h(env.doc)).status_code == 403


# ---------------------------------------------------------------- forms

_FORM = {"code": "pain-score", "name": "Pain assessment", "fields": [
    {"key": "score", "label": "Pain score", "type": "number", "required": True},
    {"key": "site", "label": "Site", "type": "select", "options": ["head", "chest", "limb"]},
    {"key": "radiating", "label": "Radiating", "type": "boolean"},
    {"key": "since", "label": "Since", "type": "date"},
    {"key": "comment", "label": "Comment", "type": "text"},
]}


def _form(env, **over):
    r = env.c.post("/forms", headers=env.h(env.admin), json={**_FORM, "code": f"f{uuid.uuid4().hex[:6]}", **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_form_definition_is_validated_and_admin_only(env):
    assert env.c.post("/forms", headers=env.h(env.doc), json=_FORM).status_code == 403
    for fields in (
        [{"key": "Bad Key", "label": "x", "type": "text"}],
        [{"key": "a", "label": "x", "type": "hologram"}],
        [{"key": "a", "label": "x", "type": "select"}],
        [{"key": "a", "label": "x", "type": "text"}, {"key": "a", "label": "y", "type": "text"}],
    ):
        r = env.c.post("/forms", headers=env.h(env.admin), json={"code": "bad", "name": "Bad", "fields": fields})
        assert r.status_code == 422, fields


def test_new_version_retires_the_old_but_keeps_its_responses(env):
    f1 = _form(env)
    ok = env.c.post(f"/patients/{env.patient.id}/forms/{f1['id']}/responses", headers=env.h(env.doc),
                    json={"values": {"score": 7, "site": "head"}})
    assert ok.status_code == 201, ok.text
    f2 = env.c.post("/forms", headers=env.h(env.admin), json={
        "code": f1["code"], "name": "Pain v2", "fields": [{"key": "score", "label": "Score", "type": "number"}]}).json()
    assert f2["version"] == 2
    assert [f["version"] for f in env.c.get("/forms", headers=env.h(env.doc)).json() if f["code"] == f1["code"]] == [2]
    assert env.c.post(f"/patients/{env.patient.id}/forms/{f1['id']}/responses", headers=env.h(env.doc),
                      json={"values": {"score": 1}}).status_code == 404
    rows = env.c.get(f"/patients/{env.patient.id}/form-responses", headers=env.h(env.doc)).json()
    assert rows[0]["form_version"] == 1 and rows[0]["values"] == {"score": 7, "site": "head"}
    assert rows[0]["fields"][0]["key"] == "score"


def test_response_validation(env):
    f = _form(env)
    url = f"/patients/{env.patient.id}/forms/{f['id']}/responses"
    for values in (
        {},                                  # required missing
        {"score": "high"},                   # wrong type
        {"score": True},                     # bool is not a number
        {"score": 3, "site": "elbow"},       # not an option
        {"score": 3, "radiating": "yes"},
        {"score": 3, "since": "yesterday"},
        {"score": 3, "extra": 1},            # unknown key
    ):
        assert env.c.post(url, headers=env.h(env.doc), json={"values": values}).status_code == 422, values
    good = env.c.post(url, headers=env.h(env.doc), json={
        "values": {"score": 4.5, "site": "chest", "radiating": False, "since": "2026-10-01", "comment": "  dull  "}})
    assert good.status_code == 201 and good.json()["values"]["comment"] == "dull"


def test_forms_and_responses_are_facility_local(env):
    f = _form(env)
    assert env.c.get("/forms", headers=env.h(env.o_doc)).json() == []
    assert env.c.post(f"/patients/{env.patient.id}/forms/{f['id']}/responses", headers=env.h(env.o_doc),
                      json={"values": {"score": 1}}).status_code == 404
    env.c.post(f"/patients/{env.patient.id}/forms/{f['id']}/responses", headers=env.h(env.doc),
               json={"values": {"score": 2}})
    assert env.c.get(f"/patients/{env.patient.id}/form-responses", headers=env.h(env.o_doc)).json() == []
    assert env.c.get("/forms", headers=env.h(env.pat_user)).status_code == 403


# ---------------------------------------------------------------- races

def _blast(n, fn):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, range(n)))


def test_parallel_goods_receipts_book_a_delivery_once(env):
    item = _item(env, "Race Drug", qty=0)
    po = _po(env, item, qty=100)
    env.c.post(f"/purchasing/orders/{po['id']}/place", headers=env.h(env.admin))
    line = po["lines"][0]["id"]
    h = env.h(env.pharm)
    codes = _blast(6, lambda _: env.c.post(f"/purchasing/orders/{po['id']}/receive", headers=h,
                                           json={"lines": [{"line_id": line, "quantity": 60}]}).status_code)
    assert codes.count(200) == 1 and set(codes) <= {200, 409, 422}
    env.db.expire_all()
    assert env.db.get(models.MedicineInventoryItem, item.id).quantity_on_hand == 60


def test_parallel_completion_of_one_order_succeeds_once(env):
    oid = _drug_order(env).json()["id"]
    h = env.h(env.pharm)
    codes = _blast(6, lambda _: env.c.post(f"/orders/{oid}/complete", headers=h, json={}).status_code)
    assert codes.count(200) == 1 and set(codes) <= {200, 409}


# ---------------------------------------------------------------- security review regressions

def test_ordering_for_a_foreign_patient_does_not_unlock_their_record(env):
    stranger = _make_patient(env.db, full_name="Other Hospital Patient")
    h = env.h(env.o_doc)
    # env.o_doc's facility has never dealt with this patient
    assert env.c.post(f"/patients/{stranger.id}/orders", headers=h,
                      json={"order_type": "other", "description": "x"}).status_code == 404
    form = _form(env)
    assert env.c.post(f"/patients/{stranger.id}/forms/{form['id']}/responses", headers=env.h(env.doc),
                      json={"values": {"score": 1}}).status_code == 404
    assert env.c.patch(f"/patients/{stranger.id}/demographics", headers=env.h(env.o_admin),
                       json={"address_line": "x"}).status_code == 404


def test_a_clinician_cannot_route_a_drug_around_the_pharmacist(env):
    r = env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc),
                   json={"order_type": "procedure", "description": "x", "dosage": "5mg"})
    assert r.status_code == 422
    oid = env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.admin),
                     json={"order_type": "drug", "description": "Own order"}).json()["id"]
    assert env.c.post(f"/orders/{oid}/complete", headers=env.h(env.admin), json={}).status_code == 403
    assert env.c.post(f"/orders/{oid}/complete", headers=env.h(env.pharm), json={}).status_code == 200


def test_pharmacist_sees_only_drug_orders_on_the_patient_list(env):
    _drug_order(env)
    env.c.post(f"/patients/{env.patient.id}/orders", headers=env.h(env.doc),
               json={"order_type": "investigation", "description": "FBC"})
    kinds = {o["order_type"] for o in env.c.get(f"/patients/{env.patient.id}/orders", headers=env.h(env.pharm)).json()}
    assert kinds == {"drug"}


def test_dependant_links_made_elsewhere_stay_invisible(env):
    kid = env.known_patient("Kid Two")           # known to env.fac only
    env.c.post(f"/patients/{env.patient.id}/dependants", headers=env.h(env.recep), json={"dependant_id": kid.id})
    # the other facility comes to know the guardian only
    env.db.add(models.Encounter(patient_id=env.patient.id, facility_name=env.other, encounter_type="outpatient"))
    env.db.commit()
    assert env.c.get(f"/patients/{env.patient.id}/dependants", headers=env.h(env.o_doc)).json() == []
    link = env.c.get(f"/patients/{env.patient.id}/dependants", headers=env.h(env.doc)).json()[0]["id"]
    assert env.c.delete(f"/patients/{env.patient.id}/dependants/{link}", headers=env.h(env.o_admin)).status_code == 404


def test_sponsors_belong_to_one_facility(env):
    code = f"SP{uuid.uuid4().hex[:5]}"
    r = env.c.post("/sponsors", headers=env.h(env.admin), json={"code": code, "name": "Ours"})
    assert r.status_code == 201
    assert env.c.get("/sponsors", headers=env.h(env.o_doc)).json() == []
    assert env.c.patch(f"/sponsors/{r.json()['id']}", headers=env.h(env.o_admin), json={"active": False}).status_code == 404
    # same code is free at the other facility
    assert env.c.post("/sponsors", headers=env.h(env.o_admin), json={"code": code, "name": "Theirs"}).status_code == 201
    # null on a required field is ignored, not a 500
    assert env.c.patch(f"/sponsors/{r.json()['id']}", headers=env.h(env.admin), json={"name": None}).json()["name"] == "Ours"


def test_non_finite_numbers_are_refused(env):
    item = _item(env, "Inf Drug")
    sup = _supplier(env)
    body = ('{"supplier_id": "%s", "lines": [{"item_id": "%s", "quantity": 1, "unit_cost": 1e999}]}'
            % (sup["id"], item.id))
    r = env.c.post("/purchasing/orders", headers={**env.h(env.pharm), "content-type": "application/json"},
                   content=body)
    assert r.status_code == 422
    f = _form(env)
    r = env.c.post(f"/patients/{env.patient.id}/forms/{f['id']}/responses",
                   headers={**env.h(env.doc), "content-type": "application/json"}, content='{"values": {"score": 1e999}}')
    assert r.status_code == 422


def test_restock_and_dispense_through_the_pharmacy_path_still_balance(env):
    """_apply_restock now uses SQL arithmetic; the older pharmacist adjust path shares it."""
    item = _item(env, "Adjust Drug", qty=10, cost=2.0)
    item.auto_approved = True
    env.db.commit()
    url = f"/pharmacy/inventory/{item.id}/adjust"
    r = env.c.post(url, headers=env.h(env.pharm), json={"delta": 5})
    assert r.status_code == 200 and r.json()["quantity_on_hand"] == 15, r.text
    r = env.c.post(url, headers=env.h(env.pharm), json={"delta": -3})
    assert r.status_code == 200 and r.json()["quantity_on_hand"] == 12
    budget = env.db.query(models.MedicineBudget).filter_by(facility_name=env.fac).first()
    env.db.refresh(budget)
    assert round(budget.procurement_spend, 2) == 10.0
