"""Mailtrap email integration.

Config is entirely via environment variables (see backend/.env.example) --
no key is ever hardcoded here. `load_dotenv()` is called early in main.py
so a local `backend/.env` file is picked up automatically during
development; in a real deployment these would just be real env vars.

Two modes, chosen by one variable:
  * Email API (real delivery): MAILTRAP_API_TOKEN, plus a sender on a domain
    verified in Mailtrap. POSTs to https://send.api.mailtrap.io/api/send.
  * Email Testing (sandbox, nothing is delivered -- messages land in a
    Mailtrap inbox): also set MAILTRAP_INBOX_ID. POSTs to
    https://sandbox.api.mailtrap.io/api/send/{inbox_id}.

Graceful degradation is the core design constraint: if Mailtrap isn't
configured (missing token) or the API call fails for any reason
(network error, bad token, Mailtrap outage), the send functions
must NOT raise -- they log the condition and return False. Callers
(auth_router's request-password-reset-otp) must not let that boolean
change the shape/content of their HTTP response, otherwise "email
configured and sent" vs. "email not configured" becomes an
enumeration-adjacent signal to an external caller.
"""
import html
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger("clarion.email")

_REQUEST_TIMEOUT_SECONDS = 10
_LIVE_URL = "https://send.api.mailtrap.io/api/send"
_SANDBOX_URL = "https://sandbox.api.mailtrap.io/api/send"


def _mailtrap_config() -> Optional[dict]:
    """Reads Mailtrap env vars fresh on every call (rather than at import
    time) so tests/tools can monkeypatch os.environ without reloading this
    module. Returns None if the token isn't set."""
    token = os.environ.get("MAILTRAP_API_TOKEN")
    if not token:
        return None

    inbox_id = (os.environ.get("MAILTRAP_INBOX_ID") or "").strip()
    default_url = f"{_SANDBOX_URL}/{inbox_id}" if inbox_id else _LIVE_URL
    return {
        "token": token,
        "url": default_url,
        "sender": os.environ.get("MAILTRAP_SENDER_EMAIL") or "noreply@clarion.larmkx.com",
        "sender_name": os.environ.get("MAILTRAP_SENDER_NAME") or "CLARION",
    }


def _send(to_email: str, subject: str, text_body: str, html_body: str, category: str, who: str) -> bool:
    """One Mailtrap send. True only on a confirmed 2xx; False in every other
    case (not configured, network failure, non-2xx). `who` is the public
    function's name, only used to make the log lines attributable."""
    config = _mailtrap_config()
    if config is None:
        logger.warning("%s: Mailtrap not configured (MAILTRAP_API_TOKEN unset) -- email not sent.", who)
        return False

    try:
        response = requests.post(
            config["url"],
            headers={"Authorization": f"Bearer {config['token']}"},
            json={
                "from": {"email": config["sender"], "name": config["sender_name"]},
                "to": [{"email": to_email}],
                "subject": subject,
                "text": text_body,
                "html": html_body,
                "category": category,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if 200 <= response.status_code < 300:
            return True
        logger.error("%s: Mailtrap returned status=%s body=%s", who, response.status_code, response.text[:500])
        return False
    except requests.RequestException:
        logger.exception("%s: Mailtrap request failed", who)
        return False


def send_password_reset_otp_email(to_email: str, otp_code: str, patient_name: str) -> bool:
    """Sends the password-reset OTP email. Returns True only on a
    confirmed-sent (2xx from Mailtrap); False in every other case --
    callers must treat False as "could not confirm delivery", not as an
    error to surface to the end user (see module docstring)."""
    text_body = (
        f"Hello {patient_name},\n\n"
        f"Your CLARION password reset code is: {otp_code}\n\n"
        "This code expires in 10 minutes. If you did not request a "
        "password reset, you can safely ignore this email.\n\n"
        "-- CLARION"
    )
    html_body = (
        f"<p>Hello {html.escape(patient_name)},</p>"
        f"<p>Your CLARION password reset code is: <strong>{html.escape(otp_code)}</strong></p>"
        "<p>This code expires in 10 minutes. If you did not request a "
        "password reset, you can safely ignore this email.</p>"
        "<p>-- CLARION</p>"
    )
    return _send(
        to_email, "Your CLARION password reset code", text_body, html_body,
        "password-reset", "send_password_reset_otp_email",
    )


def send_self_registration_otp_email(to_email: str, otp_code: str, patient_name: str) -> bool:
    """Sibling of send_password_reset_otp_email above, adjusted copy for
    the self-service registration flow (POST /auth/self-register/start) --
    same "never raise, log + return False, the caller's HTTP response shape
    must not change either way" contract (see module docstring). Kept as a
    separate function so each flow's email copy can be edited independently
    without a risk of accidentally changing the other's."""
    text_body = (
        f"Hello {patient_name},\n\n"
        f"Your CLARION account registration verification code is: {otp_code}\n\n"
        "This code expires in 10 minutes. If you did not request to "
        "register a CLARION account, you can safely ignore this email.\n\n"
        "-- CLARION"
    )
    html_body = (
        f"<p>Hello {html.escape(patient_name)},</p>"
        f"<p>Your CLARION account registration verification code is: <strong>{html.escape(otp_code)}</strong></p>"
        "<p>This code expires in 10 minutes. If you did not request to "
        "register a CLARION account, you can safely ignore this email.</p>"
        "<p>-- CLARION</p>"
    )
    return _send(
        to_email, "Your CLARION registration verification code", text_body, html_body,
        "self-registration", "send_self_registration_otp_email",
    )
