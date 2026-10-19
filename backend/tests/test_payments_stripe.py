"""Stripe provider: hosted checkout, signed webhook settlement, refund call shape.
Stripe's HTTP API is replaced by httpx.MockTransport; the webhook signature uses
Stripe's published scheme (HMAC-SHA256 over "<t>.<body>")."""
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from app import models, payment_providers as providers
from test_payments import World

WHSEC = "whsec_test_secret"


@pytest.fixture
def stripe(monkeypatch):
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
    monkeypatch.setenv("PAYMENTS_RETURN_URL", "https://clinic.example.org")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        calls.append((request.method, request.url.path, form, dict(request.headers)))
        if request.url.path == "/v1/checkout/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": f"cs_test_{uuid.uuid4().hex[:12]}", "url": f"https://checkout.stripe.test/c/{len(calls)}"})
        if request.url.path.startswith("/v1/checkout/sessions/"):
            return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[1], "payment_intent": "pi_test_9"})
        if request.url.path == "/v1/refunds":
            return httpx.Response(200, json={"id": "re_test_1"})
        return httpx.Response(404, json={"error": {"message": "nope"}})

    monkeypatch.setattr(providers, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


@pytest.fixture
def w(test_client, make_user, auth_headers, db_session):
    return World(test_client, make_user, auth_headers, db_session)


def _event(kind, session_id, amount, payment_status="paid", currency="myr"):
    return json.dumps({"id": "evt_1", "type": kind, "data": {"object": {
        "id": session_id, "amount_total": amount, "currency": currency, "payment_status": payment_status}}}).encode()


def _post(w, body, secret=WHSEC, ts=None):
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return w.c.post("/payments/webhook/stripe", content=body, headers={"Stripe-Signature": f"t={ts},v1={sig}"})


def test_intent_creates_a_checkout_session_and_returns_its_url(w, stripe):
    r = w.intent()
    assert r.status_code == 201, r.text
    i = r.json()
    assert i["provider"] == "stripe" and i["simulated"] is False
    assert i["provider_ref"].startswith("cs_test_") and i["checkout_url"].startswith("https://checkout.stripe.test/")
    method, path, form, headers = stripe[0]
    assert (method, path) == ("POST", "/v1/checkout/sessions")
    assert form["line_items[0][price_data][unit_amount]"] == "5000"
    assert form["line_items[0][price_data][currency]"] == "myr"
    assert form["client_reference_id"] == i["id"]
    assert form["success_url"] == f"https://clinic.example.org/my-bills?paid={i['id']}"
    assert headers["authorization"] == "Bearer sk_test_123" and headers["idempotency-key"] == f"clarion-intent-{i['id']}"


def test_paid_webhook_settles_once_and_replay_is_harmless(w, stripe):
    i = w.intent().json()
    body = _event("checkout.session.completed", i["provider_ref"], 5000)
    assert _post(w, body).json() == {"status": "succeeded"}
    assert _post(w, body).json() == {"status": "succeeded"}   # replay: no second payment
    bill = w.staff_bill()
    assert bill["paid_cents"] == 5000 and len(bill["payments"]) == 1


def test_bad_stale_or_wrong_secret_signatures_are_refused(w, stripe):
    i = w.intent().json()
    body = _event("checkout.session.completed", i["provider_ref"], 5000)
    assert _post(w, body, secret="whsec_other").status_code == 400
    assert _post(w, body, ts=int(time.time()) - 3600).status_code == 400
    assert w.c.post("/payments/webhook/stripe", content=body).status_code == 400   # no header
    assert w.staff_bill()["paid_cents"] == 0


def test_amount_mismatch_unpaid_and_foreign_events(w, stripe):
    i = w.intent().json()
    assert _post(w, _event("checkout.session.completed", i["provider_ref"], 100)).status_code == 409
    assert _post(w, _event("checkout.session.completed", i["provider_ref"], 5000, payment_status="unpaid")).json() == {"status": "ignored"}
    assert _post(w, _event("charge.refunded", i["provider_ref"], 5000)).json() == {"status": "ignored"}
    assert _post(w, _event("checkout.session.completed", "cs_unknown", 5000)).status_code == 404
    assert _post(w, _event("checkout.session.completed", i["provider_ref"], 5000, currency="usd")).status_code == 400
    assert w.staff_bill()["paid_cents"] == 0


def test_expired_session_fails_the_attempt(w, stripe):
    i = w.intent().json()
    assert _post(w, _event("checkout.session.expired", i["provider_ref"], 5000, payment_status="unpaid")).json() == {"status": "failed"}
    assert w.c.get(f"/payments/intents/{i['id']}", headers=w.h(w.pat_user)).json()["status"] == "failed"


def test_stripe_webhook_is_closed_unless_stripe_is_the_configured_provider(w, stripe, monkeypatch):
    monkeypatch.setenv("PAYMENTS_PROVIDER", "mock")
    body = _event("checkout.session.completed", "cs_x", 5000)
    assert _post(w, body).status_code == 404


def test_refund_looks_up_the_payment_intent_then_refunds(stripe):
    assert providers.get_provider("stripe").refund("cs_test_77", 2500) == "re_test_1"
    assert [(m, p) for m, p, *_ in stripe] == [("GET", "/v1/checkout/sessions/cs_test_77"), ("POST", "/v1/refunds")]
    assert stripe[1][2] == {"payment_intent": "pi_test_9", "amount": "2500"}


def test_unconfigured_stripe_is_a_clean_503(w, monkeypatch):
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    r = w.intent()
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_cancelling_expires_the_stripe_page_so_it_cannot_be_paid_later(w, stripe):
    i = w.intent().json()
    r = w.c.post(f"/payments/intents/{i['id']}/cancel", headers=w.h(w.pat_user))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert [(m, p) for m, p, *_ in stripe][-1] == ("POST", f"/v1/checkout/sessions/{i['provider_ref']}/expire")


def test_a_counter_payment_also_expires_the_open_stripe_page(w, stripe):
    i = w.intent().json()
    r = w.c.post(f"/billing/bills/{w.bill['id']}/payments", headers=w.h(w.recep),
                 json={"amount_cents": 1000, "method": "cash"})
    assert r.status_code in (200, 201), r.text
    assert any(p.endswith("/expire") for _, p, *_ in stripe)
    assert w.c.get(f"/payments/intents/{i['id']}", headers=w.h(w.pat_user)).json()["status"] == "cancelled"


def test_two_refunds_of_the_same_amount_use_different_idempotency_keys(stripe):
    p = providers.get_provider("stripe")
    p.refund("cs_test_5", 1000, "refund-a")
    p.refund("cs_test_5", 1000, "refund-b")
    keys = [h["idempotency-key"] for m, path, f, h in stripe if path == "/v1/refunds"]
    assert keys == ["clarion-refund-refund-a", "clarion-refund-refund-b"]


def test_stripe_error_detail_is_not_shown_to_the_patient(w, stripe, monkeypatch):
    monkeypatch.setattr(providers, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(401, json={"error": {"message": "Invalid API Key provided: sk_live_****abcd"}}))))
    r = w.intent()
    assert r.status_code == 503 and "sk_live" not in r.text


def test_refund_goes_to_the_gateway_that_took_the_payment(w, stripe, monkeypatch):
    monkeypatch.setenv("PAYMENTS_PROVIDER", "mock")
    monkeypatch.setenv("PAYMENTS_ALLOW_MOCK", "1")
    p = w.pay_online()  # a mock-gateway payment...
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")  # ...then the node switches to Stripe
    r = w.c.post(f"/billing/payments/{p['payment_id']}/refunds", headers=w.h(w.recep),
                 json={"amount_cents": 1000, "reason": "test"})
    assert r.status_code == 201, r.text
    ok = w.c.post(f"/billing/refunds/{r.json()['id']}/approve", headers=w.h(w.admin), json={})
    assert ok.status_code == 200 and ok.json()["provider_ref"].startswith("MOCKRF-"), ok.text
    assert not any(path == "/v1/refunds" for _, path, *_ in stripe)   # Stripe never asked about a MOCK payment
