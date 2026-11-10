"""R1-R15 from docs/stress-and-security-test-protocol.md section C.

N identical requests are released together by a threading.Barrier through the
shared in-process TestClient; every assertion is on DB state, never on status
codes alone. Run on MariaDB too (SQLite serialises all writers, which hides
some races):  DATABASE_URL=mysql+pymysql://... pytest tests/test_races.py
Scenarios with no matching endpoint are skipped with the reason, not invented.
"""
import json
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func

from app import models, payment_providers as providers
from app.database import engine
from app.rate_limit import limiter
from conftest import _facility, _make_patient
from test_payments import World
from test_booking_v2 import Env as BookingEnv, _day
from test_tag_crypto_offline_reads import _chain

IS_SQLITE = engine.dialect.name == "sqlite"
needs_row_locks = pytest.mark.skipif(
    IS_SQLITE, reason="SQLite serialises every writer (no row locks); run with DATABASE_URL=mysql+pymysql://... on MariaDB")


def fire(n, fn):
    """Call fn(i) from n threads released at the same instant. Exceptions (e.g. a
    server-side 500 re-raised by TestClient) are returned, not raised."""
    gate, out = threading.Barrier(n), [None] * n

    def run(i):
        gate.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:  # noqa: BLE001
            out[i] = exc

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def codes(results):
    return [r.status_code if hasattr(r, "status_code") else "EXC" for r in results]


@pytest.fixture
def w(test_client, make_user, auth_headers, db_session):
    return World(test_client, make_user, auth_headers, db_session)


def online_payments(w, bill_id=None):
    return [p for p in w.staff_bill(bill_id)["payments"] if p["method"] == "online" and not p.get("voided_at")]


# R1 -------------------------------------------------------------------------
def test_r1_parallel_webhooks_one_payment(w):
    i = w.intent().json()
    body = json.dumps({"provider_ref": i["provider_ref"], "status": "succeeded",
                       "amount_cents": i["amount_cents"]}).encode()
    sig = providers.sign(body)
    res = fire(20, lambda _: w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}))
    assert "EXC" not in codes(res)
    w.db.expire_all()
    assert w.db.query(models.Payment).filter_by(bill_id=w.bill["id"]).count() == 1
    assert w.staff_bill()["paid_cents"] == 5000


# R2 -------------------------------------------------------------------------
@needs_row_locks
def test_r2_parallel_pay_never_exceeds_bill(w):
    def pay(i):
        r = w.intent(amount=2500, key=f"race-key-{uuid.uuid4().hex}")
        if r.status_code in (200, 201):
            return w.simulate(r.json()["id"])
        return r
    res = fire(12, pay)
    assert "EXC" not in codes(res)
    bill = w.staff_bill()
    assert bill["paid_cents"] <= 5000 and bill["amount_due_cents"] >= 0
    w.db.expire_all()
    paid = w.db.query(func.coalesce(func.sum(models.Payment.amount_cents), 0)).filter_by(bill_id=w.bill["id"]).scalar()
    assert paid <= 5000


# R3 -------------------------------------------------------------------------
def test_r3_refund_two_admins_and_requester(w):
    p = w.pay_online()
    rid = w.c.post(f"/billing/payments/{p['payment_id']}/refunds", headers=w.h(w.admin),
                   json={"amount_cents": 5000, "reason": "race"}).json()["id"]
    approvers = [w.admin, w.admin2]  # w.admin is the requester
    res = fire(8, lambda i: w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(approvers[i % 2])))
    assert "EXC" not in codes(res)
    w.db.expire_all()
    ref = w.db.query(models.Refund).filter_by(id=rid).one()
    assert ref.status == "approved" and ref.decided_by == w.admin2.id  # requester never decided
    assert w.db.query(models.Refund).filter_by(payment_id=p["payment_id"], status="approved").count() == 1


# R4 -------------------------------------------------------------------------
def test_r4_double_booking_clinician_slot(test_client, make_user, auth_headers, db_session):
    facility = _facility("R4")
    clinician = make_user(role="clinician", facility=facility)
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    cid, users = clinician.id, []
    for _ in range(10):
        p = _make_patient(db_session)
        u = make_user(role="patient", patient_id=p.id)
        users.append((p.id, auth_headers(u)))
    slots = test_client.get("/patients/appointment-slots", headers=users[0][1],
                            params={"facility_name": facility, "date": day, "clinician_id": cid}).json()
    assert slots
    at = slots[0]["scheduled_at"]
    res = fire(10, lambda i: test_client.post(
        f"/patients/{users[i][0]}/appointments/self-book", headers=users[i][1],
        json={"facility_name": facility, "clinician_id": cid, "scheduled_at": at}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    n = db_session.query(models.Appointment).filter_by(clinician_id=cid, status="scheduled").count()
    assert n == 1 and codes(res).count(200) == 1


def test_r4b_booking_capacity_not_exceeded(test_client, make_user, auth_headers, db_session):
    e = BookingEnv(test_client, db_session, make_user, auth_headers)  # default capacity 2
    patients = [e.patient() for _ in range(8)]
    start = e.slots(patients[0][1], _day(2))[0]["start"]
    res = fire(8, lambda i: e.book(patients[i][1], start))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    booked = db_session.query(models.Appointment).filter(
        models.Appointment.facility_name == e.facility, models.Appointment.status == "scheduled").count()
    assert booked == 2


# R5 -------------------------------------------------------------------------
def test_r5_room_claim_single_holder(test_client, make_user, auth_headers, db_session):
    fac = _facility("R5")
    room = models.ConsultationRoom(facility_name=fac, room_name="Bilik R5", active=True)
    db_session.add(room)
    docs = [make_user(role="admin", facility=fac) for _ in range(6)]
    for d in docs:
        db_session.add(models.StaffClockEvent(user_id=d.id, facility_name=fac))
    db_session.commit()
    hs, rid = [auth_headers(d) for d in docs], room.id
    res = fire(6, lambda i: test_client.post(f"/reception/rooms/{rid}/claim", headers=hs[i]))
    assert "EXC" not in codes(res), codes(res)
    db_session.expire_all()
    assert db_session.query(models.RoomClaim).filter_by(room_id=rid, released_at=None).count() == 1, (codes(res), [r.json() for r in res][:2])


# R6 -------------------------------------------------------------------------
def test_r6_po_line_received_once(test_client, make_user, auth_headers, db_session):
    fac = _facility("R6")
    admin = make_user(role="admin", facility=fac)
    h = auth_headers(admin)
    item = models.MedicineInventoryItem(facility_name=fac, drug_name="Paracetamol", quantity_on_hand=0, unit_cost=1.0)
    db_session.add(item)
    db_session.commit()
    sup = test_client.post("/purchasing/suppliers", headers=h, json={"code": "S" + secrets.token_hex(3), "name": "Sup"}).json()
    po = test_client.post("/purchasing/orders", headers=h, json={
        "supplier_id": sup["id"], "lines": [{"item_id": item.id, "quantity": 100}]}).json()
    assert test_client.post(f"/purchasing/orders/{po['id']}/place", headers=h).status_code == 200
    line = po["lines"][0]["id"]
    res = fire(8, lambda _: test_client.post(f"/purchasing/orders/{po['id']}/receive", headers=h,
                                             json={"lines": [{"line_id": line, "quantity": 100}]}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    assert db_session.query(models.MedicineInventoryItem.quantity_on_hand).filter_by(id=item.id).scalar() == 100
    assert db_session.query(models.PurchaseOrderLine.received_quantity).filter_by(id=line).scalar() == 100


# R7 -------------------------------------------------------------------------
def test_r7_dispense_never_oversells(test_client, make_user, auth_headers, db_session):
    fac = _facility("R7")
    pharms = [make_user(role="pharmacist", facility=fac) for _ in range(15)]  # the 10 s duplicate guard is per user
    hs = [auth_headers(p) for p in pharms]
    patient = _make_patient(db_session)
    db_session.add(models.Encounter(patient_id=patient.id, facility_name=fac, encounter_type="outpatient"))
    item = models.MedicineInventoryItem(facility_name=fac, drug_name="Amox", quantity_on_hand=10, unit="caps", unit_cost=1.0)
    db_session.add(item)
    db_session.commit()
    pid, iid = patient.id, item.id
    res = fire(15, lambda i: test_client.post("/pharmacy/dispense", headers=hs[i], json={
        "patient_id": pid, "medicine_inventory_item_id": iid, "quantity": 1}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    assert db_session.query(models.MedicineInventoryItem.quantity_on_hand).filter_by(id=iid).scalar() == 0
    assert db_session.query(models.MedicineStockEvent).filter_by(item_id=iid, kind="consume").count() == 10
    assert codes(res).count(200) == 10


# R8 -------------------------------------------------------------------------
def test_r8_refresh_rotation_single_winner(test_client, make_user, db_session):
    u = make_user(role="clinician", facility="Main Hospital")
    uid = u.id
    tok = test_client.post("/auth/login", data={"username": u.email, "password": u.plaintext_password}).json()["refresh_token"]
    test_client.cookies.clear()
    res = fire(5, lambda _: test_client.post("/auth/refresh", json={"refresh_token": tok}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    live_heads = db_session.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == uid, models.RefreshToken.revoked_at.is_(None)).count()
    assert codes(res).count(200) == 1 and live_heads == 1


# R9 -------------------------------------------------------------------------
def test_r9_lockout_cannot_be_bypassed_by_parallelism(test_client, make_user, db_session, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)  # per-IP limit would mask the per-account lockout
    u = make_user(role="clinician", facility="Main Hospital")
    uid, email, pw = u.id, u.email, u.plaintext_password
    res = fire(30, lambda _: test_client.post("/auth/login", data={"username": email, "password": "wrong-password-1"}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    row = db_session.query(models.User).filter_by(id=uid).one()
    assert row.login_locked_until is not None, (codes(res), row.login_failed_count)
    ok = test_client.post("/auth/login", data={"username": email, "password": pw})
    assert ok.status_code == 429


def test_r9b_failed_counter_is_atomic(test_client, make_user, db_session, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    u = make_user(role="clinician", facility="Main Hospital")
    uid, email = u.id, u.email
    res = fire(4, lambda _: test_client.post("/auth/login", data={"username": email, "password": "wrong-password-1"}))
    db_session.expire_all()
    assert db_session.query(models.User.login_failed_count).filter_by(id=uid).scalar() == codes(res).count(401)


# R10 ------------------------------------------------------------------------
def test_r10_rate_limit_holds_under_burst(test_client):
    res = fire(60, lambda i: test_client.post("/auth/login", data={"username": f"nobody{i}@x.test", "password": "x"}))
    assert "EXC" not in codes(res)
    assert codes(res).count(429) >= 60 - 20 - 2  # limit 20/min, +-2 documented tolerance


# R11 ------------------------------------------------------------------------
def test_r11_same_nric_one_patient(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility=_facility("R11"))
    h = auth_headers(clin)
    nric = f"900101-14-{secrets.randbelow(10000):04d}"
    res = fire(12, lambda _: test_client.post("/patients", headers=h, json={"full_name": "Dup Nric", "national_id": nric}))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    assert db_session.query(models.Patient).filter_by(national_id=nric).count() == 1


# R12-R14: no endpoint to exercise -------------------------------------------
@pytest.mark.skip(reason="R12: no optimistic version/If-Match on any editable clinical entity (ClinicalForm.version is append-only); gap, not a test")
def test_r12_concurrent_clinical_edit_no_lost_update():
    ...


@pytest.mark.skip(reason="R13: no patient delete/merge endpoint exists (FK ondelete uniformity is deferred until one is built)")
def test_r13_signoff_during_merge_or_delete():
    ...


@pytest.mark.skip(reason="R14: needs two federated nodes + an updating origin; covered by test_mpi_federation (unit) and the live suite, not in-process")
def test_r14_federation_fetch_while_origin_updates():
    ...


# R15 ------------------------------------------------------------------------
def test_r15_offline_log_upload_twice_concurrently(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    uid = secrets.token_hex(7).upper()
    body = {"device_id": "dev-" + secrets.token_hex(4), "entries": _chain(5, uid=uid)}
    res = fire(6, lambda _: test_client.post("/emergency/offline-reads", headers=h, json=body))
    assert "EXC" not in codes(res)
    db_session.expire_all()
    rows = db_session.query(models.OfflineTagRead).filter_by(user_id=clin.id, device_id=body["device_id"]).all()
    assert sorted(r.seq for r in rows) == [0, 1, 2, 3, 4] and all(r.chain_ok for r in rows)
