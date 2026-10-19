"""Payments: patient online payment (mock gateway), refunds, deposits,
reconciliation and ageing (routers/payments.py)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import models, payment_providers as providers
from conftest import _facility, _make_patient


class World:
    """One facility with staff, one patient (+ patient login) and a finalized RM 50.00 bill."""

    def __init__(self, test_client, make_user, auth_headers, db_session, price=5000):
        self.c, self.db, self.make_user, self.auth_headers = test_client, db_session, make_user, auth_headers
        self._headers = {}
        self.facility = _facility("Pay")
        self.recep = make_user(role="receptionist", facility=self.facility, full_name="Cashier One")
        self.admin = make_user(role="admin", facility=self.facility, full_name="Admin One")
        self.admin2 = make_user(role="admin", facility=self.facility, full_name="Admin Two")
        self.patient = _make_patient(db_session, full_name="Pat Ient")
        self.pat_user = make_user(role="patient", patient_id=self.patient.id, facility=None)
        item = models.ChargeMasterItem(category="consultation", name="Consult", unit_price_cents=price,
                                       facility_name=self.facility)
        db_session.add(item)
        db_session.commit()
        self.item_id = item.id
        for u in (self.recep, self.admin, self.admin2, self.pat_user):
            self.h(u)
        self.bill = self.new_bill(self.patient)

    def h(self, user):
        # Cached: the fixture's DB session is not thread-safe, and the concurrency
        # tests call this from worker threads (so every user is warmed in __init__).
        if user.id not in self._headers:
            self._headers[user.id] = self.auth_headers(user)
        return self._headers[user.id]

    def new_bill(self, patient, finalize=True, qty=1):
        r = self.c.post("/billing/bills", json={"patient_id": patient.id}, headers=self.h(self.recep))
        assert r.status_code == 201, r.text
        bill = r.json()
        r = self.c.post(f"/billing/bills/{bill['id']}/items", headers=self.h(self.recep),
                        json={"source_type": "charge_master", "charge_master_item_id": self.item_id, "quantity": qty})
        assert r.status_code == 201, r.text
        if finalize:
            r = self.c.post(f"/billing/bills/{bill['id']}/finalize", headers=self.h(self.recep))
            assert r.status_code == 200, r.text
        return bill

    def staff_bill(self, bill_id=None):
        r = self.c.get(f"/billing/bills/{bill_id or self.bill['id']}", headers=self.h(self.recep))
        assert r.status_code == 200, r.text
        return r.json()

    def intent(self, amount=None, key=None, bill_id=None, user=None):
        body = {}
        if amount is not None:
            body["amount_cents"] = amount
        if key:
            body["idempotency_key"] = key
        return self.c.post(f"/payments/bills/{bill_id or self.bill['id']}/intents", json=body,
                           headers=self.h(user or self.pat_user))

    def simulate(self, intent_id, outcome="succeeded", user=None):
        return self.c.post(f"/payments/intents/{intent_id}/simulate", json={"outcome": outcome},
                           headers=self.h(user or self.pat_user))

    def pay_online(self, amount=None):
        i = self.intent(amount).json()
        r = self.simulate(i["id"])
        assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text
        return r.json()

    def signed(self, ref, status, amount):
        body = json.dumps({"provider_ref": ref, "status": status, "amount_cents": amount}).encode()
        return body, providers.sign(body)


@pytest.fixture
def w(test_client, make_user, auth_headers, db_session):
    return World(test_client, make_user, auth_headers, db_session)


# ---------------------------------------------------------------------------
# Patient side
# ---------------------------------------------------------------------------
def test_patient_sees_only_own_finalized_bills(w):
    draft = w.new_bill(w.patient, finalize=False)
    other = _make_patient(w.db, full_name="Someone Else")
    w.new_bill(other)
    rows = w.c.get("/payments/my-bills", headers=w.h(w.pat_user)).json()
    ids = {b["id"] for b in rows}
    assert w.bill["id"] in ids and draft["id"] not in ids and len(ids) == 1
    b = rows[0]
    assert b["total_cents"] == 5000 and b["patient_due_cents"] == 5000 and b["pending_intent"] is None
    assert b["items"][0]["description"] == "Consult"


def test_full_online_payment_settles_into_the_bill(w):
    i = w.intent()
    assert i.status_code == 201
    i = i.json()
    assert i["status"] == "pending" and i["amount_cents"] == 5000 and i["simulated"] is True
    done = w.simulate(i["id"]).json()
    assert done["status"] == "succeeded" and done["payment_id"]
    bill = w.staff_bill()
    assert bill["paid_cents"] == 5000 and bill["amount_due_cents"] == 0
    pay = bill["payments"][0]
    assert pay["method"] == "online" and pay["reference_no"] == i["provider_ref"]
    # settling again (a duplicate event) must not double-credit
    assert w.simulate(i["id"]).json()["status"] == "succeeded"
    assert len(w.staff_bill()["payments"]) == 1
    # nothing left to pay
    assert w.intent().status_code == 400


def test_receipt_visible_to_owner_and_billing_staff_only(w, make_user):
    p = w.pay_online()
    rc = w.c.get(f"/payments/receipts/{p['payment_id']}", headers=w.h(w.pat_user))
    assert rc.status_code == 200
    r = rc.json()
    assert r["amount_cents"] == 5000 and r["bill_balance_after_cents"] == 0 and r["patient_full_name"] == "Pat Ient"
    assert w.c.get(f"/payments/receipts/{p['payment_id']}", headers=w.h(w.recep)).status_code == 200
    stranger_p = _make_patient(w.db)
    stranger = make_user(role="patient", patient_id=stranger_p.id)
    assert w.c.get(f"/payments/receipts/{p['payment_id']}", headers=w.h(stranger)).status_code == 404
    outsider = make_user(role="receptionist", facility=_facility("Other"))
    assert w.c.get(f"/payments/receipts/{p['payment_id']}", headers=w.h(outsider)).status_code == 404
    assert w.c.get("/payments/receipts/nope", headers=w.h(w.pat_user)).status_code == 404


def test_failed_payment_leaves_bill_unpaid_and_can_retry(w):
    i = w.intent().json()
    failed = w.simulate(i["id"], "failed").json()
    assert failed["status"] == "failed" and failed["failure_reason"]
    assert w.staff_bill()["paid_cents"] == 0
    again = w.intent()
    assert again.status_code == 201 and again.json()["id"] != i["id"]


def test_amount_rules(w):
    assert w.intent(amount=5001).status_code == 400  # more than due
    assert w.intent(amount=0).status_code == 422
    part = w.intent(amount=2000)
    assert part.status_code == 201
    assert w.simulate(part.json()["id"]).json()["status"] == "succeeded"
    assert w.staff_bill()["amount_due_cents"] == 3000
    assert w.intent(amount=3001).status_code == 400
    assert w.pay_online(amount=3000)["status"] == "succeeded"
    assert w.staff_bill()["amount_due_cents"] == 0


def test_cannot_pay_open_voided_or_foreign_bills(w):
    draft = w.new_bill(w.patient, finalize=False)
    assert w.intent(bill_id=draft["id"]).status_code == 400
    other_bill = w.new_bill(_make_patient(w.db))
    assert w.intent(bill_id=other_bill["id"]).status_code == 404
    voided = w.new_bill(w.patient)
    assert w.c.post(f"/billing/bills/{voided['id']}/void", json={"reason": "wrong patient"},
                    headers=w.h(w.recep)).status_code == 200
    assert w.intent(bill_id=voided["id"]).status_code == 400
    assert w.intent(bill_id="missing").status_code == 404


def test_insurance_pending_amount_is_not_payable_online(w):
    claim = w.c.post(f"/billing/bills/{w.bill['id']}/claims", headers=w.h(w.admin),
                     json={"claim_amount_cents": 4000, "payer_name": "AIA"}).json()
    assert w.c.post(f"/billing/claims/{claim['id']}/submit", headers=w.h(w.admin)).status_code == 200
    assert w.intent(amount=1001).status_code == 400
    assert w.intent(amount=1000).status_code == 201


def test_idempotency_key_and_open_intent_handling(w):
    first = w.intent(key="key-abcdef01").json()
    assert w.intent(key="key-abcdef01").json()["id"] == first["id"]
    assert w.intent(amount=1000, key="key-abcdef01").status_code == 409  # same key, different payment
    # same amount without a key returns the open attempt; a different amount conflicts
    assert w.intent().json()["id"] == first["id"]
    assert w.intent(amount=1000).status_code == 409
    cancelled = w.c.post(f"/payments/intents/{first['id']}/cancel", headers=w.h(w.pat_user))
    assert cancelled.json()["status"] == "cancelled"
    assert w.c.post(f"/payments/intents/{first['id']}/cancel", headers=w.h(w.pat_user)).status_code == 409
    assert w.intent(amount=1000).status_code == 201


def test_expired_intent_is_replaced(w):
    first = w.intent().json()
    row = w.db.query(models.PaymentIntent).filter_by(id=first["id"]).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    w.db.commit()
    second = w.intent(amount=1000)
    assert second.status_code == 201 and second.json()["id"] != first["id"]
    w.db.expire_all()
    assert w.db.query(models.PaymentIntent).filter_by(id=first["id"]).one().status == "expired"


def test_intent_is_private_to_its_patient(w, make_user):
    i = w.intent().json()
    stranger = make_user(role="patient", patient_id=_make_patient(w.db).id)
    assert w.c.get(f"/payments/intents/{i['id']}", headers=w.h(stranger)).status_code == 404
    assert w.simulate(i["id"], user=stranger).status_code == 404
    assert w.c.post(f"/payments/intents/{i['id']}/cancel", headers=w.h(stranger)).status_code == 404


def test_roles_are_separated(w):
    assert w.c.get("/payments/my-bills", headers=w.h(w.recep)).status_code == 403
    assert w.intent(user=w.recep).status_code == 403
    assert w.c.get("/billing/reconciliation", headers=w.h(w.pat_user)).status_code == 403
    assert w.c.get("/billing/outstanding", headers=w.h(w.pat_user)).status_code == 403
    assert w.c.get("/payments/my-bills").status_code == 401


def test_my_history_lists_payments_and_hides_voided(w):
    w.pay_online(amount=2000)
    cash = w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                    json={"amount_cents": 1000, "method": "cash"}).json()
    hist = w.c.get("/payments/my-history", headers=w.h(w.pat_user)).json()
    assert sorted(h["amount_cents"] for h in hist) == [1000, 2000]
    pid = [p for p in cash["payments"] if p["method"] == "cash"][0]["id"]
    assert w.c.post(f"/billing/payments/{pid}/void", json={"reason": "typo"}, headers=w.h(w.recep)).status_code == 200
    assert [h["amount_cents"] for h in w.c.get("/payments/my-history", headers=w.h(w.pat_user)).json()] == [2000]


# ---------------------------------------------------------------------------
# Gateway webhook and environment gate
# ---------------------------------------------------------------------------
def test_webhook_requires_a_valid_signature(w):
    i = w.intent().json()
    body, sig = w.signed(i["provider_ref"], "succeeded", i["amount_cents"])
    assert w.c.post("/payments/webhook/mock", content=body).status_code == 401
    assert w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": "00" * 32}).status_code == 401
    assert w.staff_bill()["paid_cents"] == 0
    ok = w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig})
    assert ok.status_code == 200 and ok.json()["status"] == "succeeded"
    # replay
    assert w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}).status_code == 200
    assert len(w.staff_bill()["payments"]) == 1


def test_webhook_rejects_tampering_and_unknowns(w):
    i = w.intent().json()
    body, sig = w.signed(i["provider_ref"], "succeeded", i["amount_cents"])
    forged = body.replace(b"5000", b"1")  # signature no longer matches the body
    assert w.c.post("/payments/webhook/mock", content=forged, headers={"X-Signature": sig}).status_code == 401
    short, ssig = w.signed(i["provider_ref"], "succeeded", 1)
    assert w.c.post("/payments/webhook/mock", content=short, headers={"X-Signature": ssig}).status_code == 409
    ghost, gsig = w.signed("MOCK-NOPE", "succeeded", 5000)
    assert w.c.post("/payments/webhook/mock", content=ghost, headers={"X-Signature": gsig}).status_code == 404
    junk = b"not json"
    assert w.c.post("/payments/webhook/mock", content=junk,
                    headers={"X-Signature": providers.sign(junk)}).status_code == 400
    bad_status, bsig = w.signed(i["provider_ref"], "refunded", 5000)
    assert w.c.post("/payments/webhook/mock", content=bad_status, headers={"X-Signature": bsig}).status_code == 400
    assert w.c.post("/payments/webhook/stripe", content=body, headers={"X-Signature": sig}).status_code == 404
    assert w.staff_bill()["paid_cents"] == 0


def test_late_success_after_failure_is_still_booked(w):
    i = w.intent().json()
    w.simulate(i["id"], "failed")
    body, sig = w.signed(i["provider_ref"], "succeeded", i["amount_cents"])
    assert w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}).status_code == 200
    assert w.staff_bill()["paid_cents"] == 5000  # money moved, so it must be on the books


def test_mock_provider_refused_outside_demo(w, monkeypatch):
    for var in ("APP_ENV", "DEMO_MODE", "PAYMENTS_ALLOW_MOCK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert w.intent().status_code == 503
    body, sig = w.signed("MOCK-X", "succeeded", 5000)
    assert w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}).status_code == 404
    monkeypatch.setenv("PAYMENTS_ALLOW_MOCK", "1")
    assert w.intent().status_code == 201


def test_settlement_is_audited(w):
    w.pay_online()
    w.db.expire_all()
    actions = {a.action for a in w.db.query(models.AuditLog).filter_by(patient_id=w.patient.id)}
    assert {"payment_intent_created", "payment_online_settled"} <= actions


# ---------------------------------------------------------------------------
# Voiding vs refunding
# ---------------------------------------------------------------------------
def test_online_payment_cannot_be_voided(w):
    p = w.pay_online()
    r = w.c.post(f"/billing/payments/{p['payment_id']}/void", json={"reason": "oops"}, headers=w.h(w.recep))
    assert r.status_code == 400 and "refunded" in r.json()["detail"]
    assert w.staff_bill()["paid_cents"] == 5000


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
def _refund(w, payment_id, amount, user=None, reason="duplicate charge"):
    return w.c.post(f"/billing/payments/{payment_id}/refunds", json={"amount_cents": amount, "reason": reason},
                    headers=w.h(user or w.recep))


def test_refund_requires_a_different_admin_and_reduces_paid(w):
    p = w.pay_online()
    req = _refund(w, p["payment_id"], 2000)
    assert req.status_code == 201 and req.json()["status"] == "requested"
    rid = req.json()["id"]
    assert w.staff_bill()["paid_cents"] == 5000  # a request changes nothing yet
    assert w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(w.recep)).status_code == 403
    done = w.c.post(f"/billing/refunds/{rid}/approve", json={"note": "ok"}, headers=w.h(w.admin))
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert done.json()["provider_ref"].startswith("MOCKRF-")  # gateway was told
    bill = w.staff_bill()
    assert bill["paid_cents"] == 3000 and bill["refunded_cents"] == 2000 and bill["amount_due_cents"] == 2000
    assert w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(w.admin2)).status_code == 409
    # the patient can pay the freed balance again
    assert w.intent(amount=2000).status_code == 201


def test_admin_cannot_approve_own_request(w):
    p = w.pay_online()
    rid = _refund(w, p["payment_id"], 1000, user=w.admin).json()["id"]
    assert w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(w.admin)).status_code == 403
    assert w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(w.admin2)).status_code == 200


def test_refund_cap_counts_open_requests(w):
    p = w.pay_online(amount=3000)
    assert _refund(w, p["payment_id"], 3001).status_code == 400
    assert _refund(w, p["payment_id"], 2000).status_code == 201
    assert _refund(w, p["payment_id"], 1001).status_code == 400  # 2000 already requested
    assert _refund(w, p["payment_id"], 1000).status_code == 201


def test_rejected_refund_frees_the_amount(w):
    p = w.pay_online()
    rid = _refund(w, p["payment_id"], 5000).json()["id"]
    assert _refund(w, p["payment_id"], 1).status_code == 400
    rej = w.c.post(f"/billing/refunds/{rid}/reject", json={"note": "policy"}, headers=w.h(w.admin))
    assert rej.json()["status"] == "rejected"
    assert w.staff_bill()["paid_cents"] == 5000
    assert _refund(w, p["payment_id"], 5000).status_code == 201


def test_refund_rules_by_method_and_state(w):
    cash = w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                    json={"amount_cents": 1000, "method": "cash"}).json()["payments"][0]
    assert _refund(w, cash["id"], 500).status_code == 201  # counter payments are refundable too
    dep = w.c.post("/billing/deposits", headers=w.h(w.recep),
                   json={"patient_id": w.patient.id, "amount_cents": 1000, "method": "cash"}).json()
    paid = w.c.post(f"/billing/deposits/{dep['id']}/apply", headers=w.h(w.recep),
                    json={"bill_id": w.bill["id"], "amount_cents": 1000}).json()["bill"]
    dep_pay = [p for p in paid["payments"] if p["method"] == "deposit"][0]
    assert _refund(w, dep_pay["id"], 100).status_code == 400  # deposits are voided, not refunded
    assert w.c.post(f"/billing/payments/{cash['id']}/void", json={"reason": "x"}, headers=w.h(w.recep)).status_code == 200
    assert _refund(w, cash["id"], 100).status_code == 400  # voided payment
    assert _refund(w, "missing", 100).status_code == 404


def test_refund_is_facility_scoped_and_listed(w, make_user):
    p = w.pay_online()
    rid = _refund(w, p["payment_id"], 100).json()["id"]
    other_admin = make_user(role="admin", facility=_facility("Elsewhere"))
    assert w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(other_admin)).status_code == 404
    assert _refund(w, p["payment_id"], 100, user=other_admin).status_code == 404
    listed = w.c.get("/billing/refunds?status=requested", headers=w.h(w.recep)).json()
    assert [r["id"] for r in listed] == [rid]
    assert w.c.get("/billing/refunds", headers=w.h(other_admin)).json() == []
    assert w.c.get("/billing/refunds?status=bogus", headers=w.h(w.recep)).status_code == 422


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------
def _deposit(w, amount=10000, patient=None):
    r = w.c.post("/billing/deposits", headers=w.h(w.recep),
                 json={"patient_id": (patient or w.patient).id, "amount_cents": amount, "method": "cash",
                       "reference_no": "DEP-1"})
    assert r.status_code == 201, r.text
    return r.json()


def test_deposit_apply_void_and_refund_cycle(w):
    d = _deposit(w, 10000)
    assert d["balance_cents"] == 10000
    r = w.c.post(f"/billing/deposits/{d['id']}/apply", headers=w.h(w.recep),
                 json={"bill_id": w.bill["id"], "amount_cents": 5000})
    assert r.status_code == 200
    assert r.json()["deposit"]["balance_cents"] == 5000 and r.json()["bill"]["amount_due_cents"] == 0
    # over-applying: deposit balance is 5000 but the bill has nothing due
    assert w.c.post(f"/billing/deposits/{d['id']}/apply", headers=w.h(w.recep),
                    json={"bill_id": w.bill["id"], "amount_cents": 1}).status_code == 400
    # voiding the deposit payment returns the money to the deposit
    pid = r.json()["bill"]["payments"][0]["id"]
    assert w.c.post(f"/billing/payments/{pid}/void", json={"reason": "wrong bill"}, headers=w.h(w.recep)).status_code == 200
    back = w.c.get(f"/billing/deposits?patient_id={w.patient.id}", headers=w.h(w.recep)).json()[0]
    assert back["balance_cents"] == 10000
    assert w.staff_bill()["amount_due_cents"] == 5000
    # refund: admin only, never more than the balance
    assert w.c.post(f"/billing/deposits/{d['id']}/refund", json={}, headers=w.h(w.recep)).status_code == 403
    assert w.c.post(f"/billing/deposits/{d['id']}/refund", json={"amount_cents": 10001},
                    headers=w.h(w.admin)).status_code == 400
    full = w.c.post(f"/billing/deposits/{d['id']}/refund", json={}, headers=w.h(w.admin)).json()
    assert full["balance_cents"] == 0 and full["refunded_cents"] == 10000
    assert w.c.post(f"/billing/deposits/{d['id']}/refund", json={}, headers=w.h(w.admin)).status_code == 400


def test_deposit_validation_and_scoping(w, make_user):
    assert w.c.post("/billing/deposits", headers=w.h(w.recep),
                    json={"patient_id": w.patient.id, "amount_cents": 100, "method": "bitcoin"}).status_code == 422
    assert w.c.post("/billing/deposits", headers=w.h(w.recep),
                    json={"patient_id": "nope", "amount_cents": 100, "method": "cash"}).status_code == 404
    d = _deposit(w, 3000)
    stranger_bill = w.new_bill(_make_patient(w.db))
    assert w.c.post(f"/billing/deposits/{d['id']}/apply", headers=w.h(w.recep),
                    json={"bill_id": stranger_bill["id"], "amount_cents": 100}).status_code == 400
    assert w.c.post(f"/billing/deposits/{d['id']}/apply", headers=w.h(w.recep),
                    json={"bill_id": w.bill["id"], "amount_cents": 3001}).status_code == 400
    outsider = make_user(role="receptionist", facility=_facility("Far"))
    assert w.c.post(f"/billing/deposits/{d['id']}/apply", headers=w.h(outsider),
                    json={"bill_id": w.bill["id"], "amount_cents": 100}).status_code == 404
    assert w.c.get(f"/billing/deposits?patient_id={w.patient.id}", headers=w.h(outsider)).json() == []


# ---------------------------------------------------------------------------
# Reconciliation and ageing
# ---------------------------------------------------------------------------
def test_reconciliation_totals_by_method_cashier_refunds_and_scope(w, make_user):
    w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
             json={"amount_cents": 1000, "method": "cash"})
    w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
             json={"amount_cents": 500, "method": "card", "reference_no": "T-9"})
    voided = w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                      json={"amount_cents": 700, "method": "cash"}).json()["payments"][-1]
    w.c.post(f"/billing/payments/{voided['id']}/void", json={"reason": "typo"}, headers=w.h(w.recep))
    online = w.pay_online(amount=2000)
    rid = _refund(w, online["payment_id"], 400).json()["id"]
    w.c.post(f"/billing/refunds/{rid}/approve", json={}, headers=w.h(w.admin))
    dep = _deposit(w, 9000)
    w.c.post(f"/billing/deposits/{dep['id']}/apply", headers=w.h(w.recep),
             json={"bill_id": w.bill["id"], "amount_cents": 500})  # internal transfer, not new cash
    w.intent(amount=500)  # an attempt still waiting for the gateway

    rec = w.c.get("/billing/reconciliation", headers=w.h(w.recep)).json()
    assert rec["collected_cents"] == 3500
    assert rec["by_method"] == {"cash": {"count": 1, "total_cents": 1000},
                                "card": {"count": 1, "total_cents": 500},
                                "online": {"count": 1, "total_cents": 2000}}
    assert rec["voided"] == {"count": 1, "total_cents": 700}
    assert rec["refunds"] == {"count": 1, "total_cents": 400}
    assert rec["net_cents"] == 3500 + 9000 - 400  # collected + deposits received - refunds
    assert rec["deposits_received"] == {"count": 1, "total_cents": 9000}
    assert rec["applied_from_deposits"] == {"count": 1, "total_cents": 500}
    assert "deposit" not in rec["by_method"]
    assert rec["online_pending"] == {"count": 1, "total_cents": 500}
    names = {c["name"]: c["total_cents"] for c in rec["by_cashier"]}
    assert names == {"Cashier One": 1500, "Online payment": 2000}

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    empty = w.c.get(f"/billing/reconciliation?day={tomorrow}", headers=w.h(w.recep)).json()
    assert empty["collected_cents"] == 0 and empty["by_method"] == {}
    outsider = make_user(role="receptionist", facility=_facility("Other"))
    assert w.c.get("/billing/reconciliation", headers=w.h(outsider)).json()["collected_cents"] == 0
    assert w.c.get("/billing/reconciliation?tz_offset_minutes=9999", headers=w.h(w.recep)).status_code == 422


def test_outstanding_buckets_by_age(w):
    old = w.new_bill(w.patient)
    ancient = w.new_bill(w.patient)
    for bid, days in ((old["id"], 45), (ancient["id"], 200)):
        row = w.db.query(models.Bill).filter_by(id=bid).one()
        row.finalized_at = datetime.now(timezone.utc) - timedelta(days=days)
    w.db.commit()
    paid = w.new_bill(w.patient)
    w.c.post(f"/billing/bills/{paid['id']}/payments", headers=w.h(w.recep), json={"amount_cents": 5000, "method": "cash"})
    w.new_bill(w.patient, finalize=False)  # drafts are not receivables

    out = w.c.get("/billing/outstanding", headers=w.h(w.recep)).json()
    by = {b["label"]: b for b in out["buckets"]}
    assert (by["0-30"]["count"], by["31-60"]["count"], by["61-90"]["count"], by["90+"]["count"]) == (1, 1, 0, 1)
    assert out["total_cents"] == 15000 and len(out["bills"]) == 3
    assert [b["bucket"] for b in out["bills"]] == ["90+", "31-60", "0-30"]  # oldest first
    assert paid["id"] not in {b["bill_id"] for b in out["bills"]}


def test_staff_cannot_record_system_only_methods(w):
    for method in ("online", "deposit"):
        r = w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                     json={"amount_cents": 1000, "method": method, "reference_no": "forged"})
        assert r.status_code == 422, (method, r.text)
    assert w.staff_bill()["paid_cents"] == 0


def test_counter_payment_closes_the_open_online_attempt(w):
    i = w.intent().json()
    assert w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                    json={"amount_cents": 1000, "method": "cash"}).status_code == 201
    assert w.c.get(f"/payments/intents/{i['id']}", headers=w.h(w.pat_user)).json()["status"] == "cancelled"
    fresh = w.intent()
    assert fresh.status_code == 201 and fresh.json()["amount_cents"] == 4000  # the new amount due
    # money the gateway still takes for the old attempt is booked, never lost
    body, sig = w.signed(i["provider_ref"], "succeeded", i["amount_cents"])
    assert w.c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}).status_code == 200
    assert len([p for p in w.staff_bill()["payments"] if p["method"] == "online"]) == 1


def test_applying_a_deposit_closes_the_open_online_attempt(w):
    i = w.intent().json()
    dep = _deposit(w, 2000)
    w.c.post(f"/billing/deposits/{dep['id']}/apply", headers=w.h(w.recep),
             json={"bill_id": w.bill["id"], "amount_cents": 2000})
    assert w.c.get(f"/payments/intents/{i['id']}", headers=w.h(w.pat_user)).json()["status"] == "cancelled"


def test_deposit_refunds_are_netted_on_the_day_they_happen(w):
    dep = _deposit(w, 9000)
    w.c.post(f"/billing/deposits/{dep['id']}/refund", json={"amount_cents": 2000}, headers=w.h(w.admin))
    w.c.post(f"/billing/deposits/{dep['id']}/refund", json={"amount_cents": 500}, headers=w.h(w.admin))
    rec = w.c.get("/billing/reconciliation", headers=w.h(w.recep)).json()
    assert rec["deposits_received"]["total_cents"] == 9000
    assert rec["deposit_refunds"] == {"count": 2, "total_cents": 2500}
    assert rec["net_cents"] == 9000 - 2500


def test_close_over_a_range_and_as_pdf(w):
    from datetime import date, timedelta
    w.pay_online()
    today = date.today().isoformat()
    one = w.c.get("/billing/reconciliation", headers=w.h(w.recep)).json()
    assert one["days"] == 1 and one["from_day"] == one["day"]
    week = w.c.get("/billing/reconciliation?days=7", headers=w.h(w.recep)).json()
    assert week["days"] == 7 and week["collected_cents"] >= one["collected_cents"] > 0
    assert week["from_day"] == (date.fromisoformat(week["day"]) - timedelta(days=6)).isoformat()
    # a window that ends before today's payment does not include it
    past = (date.today() - timedelta(days=3)).isoformat()
    assert w.c.get(f"/billing/reconciliation?day={past}&days=2", headers=w.h(w.recep)).json()["collected_cents"] == 0
    for bad in ("days=0", "days=187"):
        assert w.c.get(f"/billing/reconciliation?{bad}", headers=w.h(w.recep)).status_code == 422
    pdf = w.c.get("/billing/reconciliation/pdf?days=30", headers=w.h(w.recep))
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert "_to_" in pdf.headers["content-disposition"]
    assert w.c.get("/billing/reconciliation/pdf", headers=w.h(w.pat_user)).status_code == 403
    assert today  # silence unused
