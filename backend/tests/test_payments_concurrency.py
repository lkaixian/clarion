"""Parallel requests against the payment flow. Found with a live server: a
read-then-write guard let 16 simultaneous webhooks credit one bill 4 times, two
devices open two attempts, one deposit pay two bills, and two refund requests
exceed their payment. Every money decision now serialises on a row (see
routers/payments.py::_lock and the compare-and-set in settle_intent)."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import payment_providers as providers
from test_payments import World


@pytest.fixture
def w(test_client, make_user, auth_headers, db_session):
    return World(test_client, make_user, auth_headers, db_session)


def blast(n, fn):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, range(n)))


def online_payments(w, bill_id=None):
    return [p for p in w.staff_bill(bill_id)["payments"] if p["method"] == "online" and not p.get("voided_at")]


def test_parallel_webhooks_credit_the_bill_once(w):
    i = w.intent().json()
    body = json.dumps({"provider_ref": i["provider_ref"], "status": "succeeded",
                       "amount_cents": i["amount_cents"]}).encode()
    sig = providers.sign(body)
    codes = blast(12, lambda _: w.c.post("/payments/webhook/mock", content=body,
                                         headers={"X-Signature": sig}).status_code)
    assert set(codes) == {200}
    assert len(online_payments(w)) == 1
    assert w.staff_bill()["paid_cents"] == 5000


def test_parallel_simulate_taps_credit_the_bill_once(w):
    i = w.intent().json()
    codes = blast(8, lambda _: w.simulate(i["id"]).status_code)
    assert set(codes) == {200}
    assert len(online_payments(w)) == 1


def test_parallel_pay_taps_open_a_single_attempt(w):
    resp = blast(8, lambda _: w.intent())
    ids = {r.json()["id"] for r in resp if r.status_code in (200, 201)}
    assert len(ids) == 1 and all(r.status_code in (200, 201) for r in resp)


def test_two_devices_with_different_keys_cannot_open_two_attempts(w):
    resp = blast(6, lambda _: w.intent(key=f"dev-{uuid.uuid4().hex}"))
    ids = {r.json()["id"] for r in resp if r.status_code in (200, 201)}
    assert len(ids) == 1
    assert {r.status_code for r in resp} <= {200, 201, 409}


def test_a_deposit_cannot_pay_two_bills(w):
    other = w.new_bill(w.patient)
    dep = w.c.post("/billing/deposits", headers=w.h(w.recep),
                   json={"patient_id": w.patient.id, "amount_cents": 5000, "method": "cash"}).json()

    def apply(i):
        bill = w.bill if i % 2 == 0 else other
        return w.c.post(f"/billing/deposits/{dep['id']}/apply", headers=w.h(w.recep),
                        json={"bill_id": bill["id"], "amount_cents": 5000}).status_code
    codes = blast(8, apply)
    assert codes.count(200) == 1 and set(codes) <= {200, 400}
    d = w.c.get(f"/billing/deposits?patient_id={w.patient.id}", headers=w.h(w.recep)).json()[0]
    assert d["applied_cents"] == 5000 and d["balance_cents"] == 0
    paid = [w.staff_bill(b["id"])["paid_cents"] for b in (w.bill, other)]
    assert sorted(paid) == [0, 5000]


def test_a_refund_is_approved_once(w):
    p = w.pay_online()
    rid = w.c.post(f"/billing/payments/{p['payment_id']}/refunds", headers=w.h(w.recep),
                   json={"amount_cents": 5000, "reason": "race"}).json()["id"]
    codes = blast(6, lambda _: w.c.post(f"/billing/refunds/{rid}/approve", json={},
                                        headers=w.h(w.admin)).status_code)
    assert codes.count(200) == 1 and set(codes) <= {200, 409}
    assert w.staff_bill()["refunded_cents"] == 5000


def test_parallel_refund_requests_respect_the_payment(w):
    p = w.pay_online()
    codes = blast(6, lambda _: w.c.post(f"/billing/payments/{p['payment_id']}/refunds", headers=w.h(w.recep),
                                        json={"amount_cents": 2501, "reason": "race"}).status_code)
    assert codes.count(201) == 1 and set(codes) <= {201, 400}
