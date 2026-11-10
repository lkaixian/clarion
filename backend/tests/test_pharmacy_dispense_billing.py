"""POST /pharmacy/dispense: stock down + priced + on the patient's open bill, one transaction."""
import pytest

from app import models
from conftest import _facility, _make_patient


class Env:
    pass


@pytest.fixture
def env(test_client, db_session, make_user, auth_headers):
    e = Env()
    e.c, e.db = test_client, db_session
    e.fac, e.other = _facility("Disp"), _facility("DispOther")
    e.pharm = make_user(role="pharmacist", facility=e.fac)
    e.h = auth_headers(e.pharm)
    e.patient = _make_patient(db_session)
    db_session.add(models.Encounter(patient_id=e.patient.id, facility_name=e.fac, encounter_type="outpatient"))
    db_session.commit()

    def item(qty=50, cost=12.5, fac=None, name="Amoxicillin"):
        it = models.MedicineInventoryItem(
            facility_name=fac or e.fac, drug_name=name, quantity_on_hand=qty, unit="caps", unit_cost=cost)
        db_session.add(it)
        db_session.commit()
        return it

    e.item = item
    e.user = make_user
    e.headers = auth_headers

    def post(it, qty=2, headers=None, patient=None, **extra):
        body = {"patient_id": (patient or e.patient).id, "medicine_inventory_item_id": it.id, "quantity": qty, **extra}
        return e.c.post("/pharmacy/dispense", json=body, headers=headers or e.h)

    e.post = post
    return e


def _qty(env, it):
    env.db.expire_all()
    return env.db.query(models.MedicineInventoryItem).filter_by(id=it.id).one().quantity_on_hand


def _bills(env):
    env.db.expire_all()
    return env.db.query(models.Bill).filter_by(patient_id=env.patient.id, facility_name=env.fac).all()


def test_happy_path_creates_bill_item_and_audit(env):
    it = env.item(qty=50, cost=12.345)  # 1234.5 cents -> half-up 1235
    r = env.post(it, qty=3)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quantity_on_hand"] == 47 and body["amount_cents"] == 3 * 1235
    assert _qty(env, it) == 47
    bills = _bills(env)
    assert len(bills) == 1 and bills[0].status == "open" and bills[0].created_by == env.pharm.id
    items = env.db.query(models.BillItem).filter_by(bill_id=bills[0].id).all()
    assert len(items) == 1 and items[0].id == body["bill_item_id"] and body["bill_id"] == bills[0].id
    assert (items[0].source_type, items[0].quantity, items[0].unit_price_cents) == ("pharmacy_item", 3, 1235)
    ev = env.db.query(models.MedicineStockEvent).filter_by(item_id=it.id, kind="consume").one()
    assert ev.delta == -3
    assert env.db.query(models.AuditLog).filter_by(patient_id=env.patient.id, action="pharmacy_dispense_billed").count() == 1


def test_adds_to_existing_open_bill(env):
    it = env.item()
    first = env.post(it, qty=1).json()
    second = env.post(env.item(name="Other"), qty=2).json()
    assert second["bill_id"] == first["bill_id"]
    assert len(_bills(env)) == 1


def test_finalized_bill_not_reused(env):
    it = env.item()
    old = models.Bill(patient_id=env.patient.id, facility_name=env.fac, status="finalized")
    env.db.add(old)
    env.db.commit()
    r = env.post(it, qty=1)
    assert r.status_code == 200
    assert r.json()["bill_id"] != old.id
    env.db.expire_all()
    assert env.db.query(models.BillItem).filter_by(bill_id=old.id).count() == 0


def test_insufficient_stock_writes_nothing(env):
    it = env.item(qty=2)
    r = env.post(it, qty=3)
    assert r.status_code == 400
    assert _qty(env, it) == 2 and _bills(env) == []
    assert env.db.query(models.MedicineStockEvent).filter_by(item_id=it.id).count() == 0


def test_no_price_400(env):
    it = env.item(cost=None)
    r = env.post(it)
    assert r.status_code == 400 and "no price" in r.json()["detail"]
    assert _qty(env, it) == 50 and _bills(env) == []


def test_other_facility_item_404(env):
    it = env.item(fac=env.other)
    assert env.post(it).status_code == 404
    assert _qty(env, it) == 50


def test_unknown_patient_404(env):
    it = env.item()
    stranger = _make_patient(env.db)
    r = env.post(it, patient=stranger)
    assert r.status_code == 404
    assert _qty(env, it) == 50


def test_statement_must_be_active_and_patients(env):
    it = env.item()
    other = _make_patient(env.db)
    ms = models.MedicationStatement(patient_id=other.id, drug_name="X", active=True)
    off = models.MedicationStatement(patient_id=env.patient.id, drug_name="X", active=False)
    ok = models.MedicationStatement(patient_id=env.patient.id, drug_name="X", active=True)
    env.db.add_all([ms, off, ok])
    env.db.commit()
    assert env.post(it, medication_statement_id=ms.id).status_code == 400
    assert env.post(it, medication_statement_id=off.id).status_code == 400
    assert env.post(it, medication_statement_id=ok.id).status_code == 200


@pytest.mark.parametrize("role", ["receptionist", "clinician"])
def test_other_roles_403(env, role):
    it = env.item()
    u = env.user(role=role, facility=env.fac)
    assert env.post(it, headers=env.headers(u)).status_code == 403
    assert _qty(env, it) == 50


def test_duplicate_within_10s_409(env):
    it = env.item()
    assert env.post(it, qty=2).status_code == 200
    assert env.post(it, qty=2).status_code == 409
    assert _qty(env, it) == 48
    assert env.post(it, qty=1).status_code == 200  # different quantity is not a duplicate
