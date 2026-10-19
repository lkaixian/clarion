"""Payment gateway adapters.

The payments router talks to ONE interface (`create` / `refund`) and to one
signed webhook. Two providers: `mock` moves no money and is only usable when the node runs
as a demo (APP_ENV/DEMO_MODE=demo) or PAYMENTS_ALLOW_MOCK=1 is set; `stripe`
(PAYMENTS_PROVIDER=stripe) sends the patient to a Stripe Checkout page (cards,
and FPX where the Stripe account has it) and learns the outcome from a signed
Stripe webhook. Another gateway is a new class here plus its webhook mapping.

Webhook authenticity: HMAC-SHA256 over the raw body, key from
PAYMENTS_WEBHOOK_SECRET, else derived from SECRET_KEY. The mock provider's
"simulate" button signs its own event with the same key, so the demo
exercises the real settlement path, not a shortcut.
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Gateway unavailable or refused the request."""


def mock_allowed() -> bool:
    env = os.environ.get("APP_ENV", "").strip().lower()
    demo = os.environ.get("DEMO_MODE", "").strip().lower()
    return env == "demo" or demo in ("demo", "1", "true") or os.environ.get("PAYMENTS_ALLOW_MOCK") == "1"


def webhook_secret() -> bytes:
    key = os.environ.get("PAYMENTS_WEBHOOK_SECRET") or ("payments-webhook|" + os.environ["SECRET_KEY"])
    return key.encode()


def sign(body: bytes) -> str:
    return hmac.new(webhook_secret(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str) -> bool:
    return bool(signature) and hmac.compare_digest(sign(body), signature)


class MockProvider:
    name = "mock"

    def create(self, amount_cents: int, bill_id: str, intent_id: str = "") -> dict:
        return {"provider_ref": f"MOCK-{uuid.uuid4().hex[:16].upper()}"}

    def refund(self, provider_ref: str, amount_cents: int, refund_id: str = "") -> str:
        return f"MOCKRF-{uuid.uuid4().hex[:12].upper()}"


# ---- Stripe ----------------------------------------------------------------
# Plain REST over httpx (no SDK). Env: STRIPE_SECRET_KEY (sk_...),
# STRIPE_WEBHOOK_SECRET (whsec_...), PAYMENTS_RETURN_URL (the public web origin the
# patient comes back to), optional STRIPE_API_BASE for tests.
STRIPE_TOLERANCE_SECONDS = 300
_client_factory = lambda: httpx.Client(timeout=10.0)  # noqa: E731 -- swapped in tests


class StripeProvider:
    name = "stripe"
    currency = "myr"

    def __init__(self) -> None:
        self.key = os.environ.get("STRIPE_SECRET_KEY", "")
        self.base = os.environ.get("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
        self.return_url = os.environ.get("PAYMENTS_RETURN_URL", "").rstrip("/")
        if not (self.key and self.return_url and os.environ.get("STRIPE_WEBHOOK_SECRET")):
            raise ProviderError("Online payments are not configured on this node")

    def _request(self, method: str, path: str, data: dict = None, idem: str = None) -> dict:
        headers = {"Authorization": f"Bearer {self.key}"}
        if idem:
            headers["Idempotency-Key"] = idem
        try:
            with _client_factory() as client:
                resp = client.request(method, self.base + path, data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError("The payment service is unreachable") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            # The detail can name the key or the account state: log it, show patients nothing specific.
            logger.warning("Stripe %s %s -> %s: %s", method, path, resp.status_code,
                           (body.get("error") or {}).get("message"))
            raise ProviderError("The payment service refused the request")
        return body

    def create(self, amount_cents: int, bill_id: str, intent_id: str = "") -> dict:
        data = {
            "mode": "payment",
            "client_reference_id": intent_id,
            "success_url": f"{self.return_url}/my-bills?paid={intent_id}",
            "cancel_url": f"{self.return_url}/my-bills?cancelled={intent_id}",
            "expires_at": str(int(time.time()) + 31 * 60),   # Stripe's minimum is 30 minutes
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": self.currency,
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": "Clinic bill",
            "metadata[intent_id]": intent_id,
            "metadata[bill_id]": bill_id,
        }
        session = self._request("POST", "/v1/checkout/sessions", data, idem=f"clarion-intent-{intent_id}")
        return {"provider_ref": session["id"], "checkout_url": session.get("url")}

    def expire(self, provider_ref: str) -> None:
        """Close an unpaid Checkout page so it cannot be paid after CLARION gave up on it.
        Best effort: a session that is already paid or expired just answers with an error."""
        try:
            self._request("POST", f"/v1/checkout/sessions/{quote(provider_ref, safe='')}/expire")
        except ProviderError:
            pass

    def refund(self, provider_ref: str, amount_cents: int, refund_id: str = "") -> str:
        session = self._request("GET", f"/v1/checkout/sessions/{quote(provider_ref, safe='')}")
        pi = session.get("payment_intent")
        if not pi:
            raise ProviderError("That payment cannot be refunded online")
        refund = self._request("POST", "/v1/refunds", {"payment_intent": pi, "amount": str(amount_cents)},
                               idem=f"clarion-refund-{refund_id or provider_ref}")
        return refund["id"]


def stripe_event(body: bytes, header: str, now: float = None) -> "dict | None":
    """Verify Stripe's `Stripe-Signature` (HMAC-SHA256 of "<t>.<body>", 5 min tolerance)
    and map the event to CLARION's {provider_ref, status, amount_cents, reason}.
    Returns None for an authentic event we do not act on; raises ValueError if the
    signature is missing, wrong or stale."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    parts = [p.split("=", 1) for p in (header or "").split(",") if "=" in p]
    stamps = [v for k, v in parts if k == "t"]
    sigs = [v for k, v in parts if k == "v1"]
    if not (secret and stamps and sigs):
        raise ValueError("bad signature")
    try:
        ts = int(stamps[0])
    except ValueError:
        raise ValueError("bad signature")
    if abs((now if now is not None else time.time()) - ts) > STRIPE_TOLERANCE_SECONDS:
        raise ValueError("stale signature")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise ValueError("bad signature")

    event = json.loads(body)
    obj = (event.get("data") or {}).get("object") or {}
    kind = event.get("type")
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") != "paid":
            return None   # completed but still awaiting an async method: wait for the later event
        if str(obj.get("currency", "")).lower() != "myr":
            raise ValueError("unexpected currency")
        return {"provider_ref": obj["id"], "status": "succeeded", "amount_cents": int(obj["amount_total"])}
    if kind in ("checkout.session.async_payment_failed", "checkout.session.expired"):
        return {"provider_ref": obj["id"], "status": "failed", "amount_cents": int(obj.get("amount_total") or 0),
                "reason": "The payment was not completed"}
    return None


def expire_open_session(intent) -> None:
    """Called whenever CLARION closes a pending attempt (cancel, counter payment, local
    expiry): the gateway page must stop accepting money for it too."""
    if getattr(intent, "provider", None) == "stripe" and intent.provider_ref:
        try:
            StripeProvider().expire(intent.provider_ref)
        except ProviderError:
            logger.warning("could not expire the Stripe session for intent %s", intent.id)


def get_provider(name: str = None):
    name = name or os.environ.get("PAYMENTS_PROVIDER", "mock")
    if name == "stripe":
        return StripeProvider()
    if name == "mock":
        if not mock_allowed():
            raise ProviderError("Online payments are not configured on this node")
        return MockProvider()
    raise ProviderError(f"Unknown payment provider '{name}'")
