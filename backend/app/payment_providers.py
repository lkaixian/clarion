"""Payment gateway adapters.

The payments router talks to ONE interface (`create` / `refund`) and to one
signed webhook. Only the `mock` provider exists: it moves no money and is
only usable when the node runs as a demo (APP_ENV/DEMO_MODE=demo) or
PAYMENTS_ALLOW_MOCK=1 is set. A real gateway (FPX / card) is a new class
here plus its webhook mapping; nothing else in the app changes.

Webhook authenticity: HMAC-SHA256 over the raw body, key from
PAYMENTS_WEBHOOK_SECRET, else derived from SECRET_KEY. The mock provider's
"simulate" button signs its own event with the same key, so the demo
exercises the real settlement path, not a shortcut.
"""
import hashlib
import hmac
import os
import uuid


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

    def create(self, amount_cents: int, bill_id: str) -> dict:
        return {"provider_ref": f"MOCK-{uuid.uuid4().hex[:16].upper()}"}

    def refund(self, provider_ref: str, amount_cents: int) -> str:
        return f"MOCKRF-{uuid.uuid4().hex[:12].upper()}"


def get_provider(name: str = None):
    name = name or os.environ.get("PAYMENTS_PROVIDER", "mock")
    if name == "mock":
        if not mock_allowed():
            raise ProviderError("Online payments are not configured on this node")
        return MockProvider()
    raise ProviderError(f"Unknown payment provider '{name}'")
