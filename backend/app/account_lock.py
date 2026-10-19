"""One-tap "this wasn't me" lock link, and the cooling period for new self-registered accounts.

The link token is HMAC-signed and purpose-bound (not a JWT, so it can never be used as an
access token), valid 7 days. Locking is self-service end to end: the owner locks from the
email, and unlocks by resetting the password through the emailed code (the existing
forgot-password flow clears the lock). No clinician or administrator is involved.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from . import mfa

LOCK_TOKEN_TTL_SECONDS = 7 * 24 * 3600


def cooling_hours() -> float:
    try:
        return max(0.0, float(os.environ.get("SELF_REG_COOLING_HOURS", "24")))
    except ValueError:
        return 24.0


def public_base_url() -> Optional[str]:
    """Set per node (docker-compose passes it). None means no link can be built."""
    return (os.environ.get("CLARION_PUBLIC_URL") or "").rstrip("/") or None


def _sign(label: str, body: str) -> str:
    return hmac.new(mfa._derive(label), body.encode(), hashlib.sha256).hexdigest()


def make_lock_token(user_id: str, marker: str, now: "float | None" = None) -> str:
    """`marker` is mfa.password_marker(user): locking (or any password change) changes it, so the
    link is spent after one use and dies if the password is reset."""
    exp = int((now if now is not None else time.time()) + LOCK_TOKEN_TTL_SECONDS)
    body = f"lock2.{user_id}.{marker}.{exp}"
    return f"{body}.{_sign('clarion-account-lock-v2', body)}"


def read_lock_token(token: str, now: "float | None" = None) -> Optional[tuple]:
    """(user_id, marker) for a valid, unexpired token, else None."""
    try:
        version, user_id, marker, exp, sig = (token or "").split(".")
        if version != "lock2":
            return None
        if not hmac.compare_digest(_sign("clarion-account-lock-v2", f"{version}.{user_id}.{marker}.{exp}"), sig):
            return None
        if (now if now is not None else time.time()) > int(exp):
            return None
        return user_id, marker
    except (ValueError, AttributeError):
        return None


def lock_url(user) -> Optional[str]:
    base = public_base_url()
    if base is None:
        return None
    return f"{base}/api/auth/account-lock?token={make_lock_token(user.id, mfa.password_marker(user))}"


COMPLETION_TTL_SECONDS = 30 * 60


def make_completion_token(patient_id: str, now: "float | None" = None) -> str:
    """Handed to whoever just proved the emailed code; /complete refuses without it, so a
    stranger who only knows the NRIC cannot finish someone else's registration."""
    exp = int((now if now is not None else time.time()) + COMPLETION_TTL_SECONDS)
    body = f"reg1.{patient_id}.{exp}"
    return f"{body}.{_sign('clarion-self-register-complete-v1', body)}"


def completion_token_ok(token: str, patient_id: str, now: "float | None" = None) -> bool:
    try:
        version, pid, exp, sig = (token or "").split(".")
        if version != "reg1" or pid != patient_id:
            return False
        if not hmac.compare_digest(_sign("clarion-self-register-complete-v1", f"{version}.{pid}.{exp}"), sig):
            return False
        return (now if now is not None else time.time()) <= int(exp)
    except (ValueError, AttributeError):
        return False


def require_account_mature(user) -> None:
    """403 for a self-registered account still inside its cooling period. Used on the few
    actions that move money or send record data out of the app. Staff-issued accounts
    (self_registered_at is NULL) are never affected."""
    hours = cooling_hours()
    made = getattr(user, "self_registered_at", None)
    if not made or hours <= 0:
        return
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    until = made + timedelta(hours=hours)
    if datetime.now(timezone.utc) < until:
        raise HTTPException(
            status_code=403,
            detail="For your protection, a new account cannot do this for its first "
                   f"{int(hours)} hours. Please try again later.",
        )
