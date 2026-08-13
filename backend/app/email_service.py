"""Mailgun email integration.

Config is entirely via environment variables (see backend/.env.example) --
no key is ever hardcoded here. `load_dotenv()` is called early in main.py
so a local `backend/.env` file is picked up automatically during
development; in a real deployment these would just be real env vars.

Graceful degradation is the core design constraint: if Mailgun isn't
configured (missing key/domain) or the API call fails for any reason
(network error, bad key, Mailgun outage), `send_password_reset_otp_email`
must NOT raise -- it logs the condition and returns False. Callers
(auth_router's request-password-reset-otp) must not let that boolean
change the shape/content of their HTTP response, otherwise "email
configured and sent" vs. "email not configured" becomes an
enumeration-adjacent signal to an external caller.
"""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger("medibridge.email")

_REQUEST_TIMEOUT_SECONDS = 10


def _mailgun_config() -> Optional[dict]:
    """Reads Mailgun env vars fresh on every call (rather than at import
    time) so tests/tools can monkeypatch os.environ without reloading this
    module. Returns None if the required vars aren't set."""
    api_key = os.environ.get("MAILGUN_API_KEY")
    domain = os.environ.get("MAILGUN_DOMAIN")
    if not api_key or not domain:
        return None

    base_url = os.environ.get("MAILGUN_API_BASE_URL", "https://api.mailgun.net/v3")
    sender = os.environ.get("MAILGUN_SENDER_EMAIL") or f"MediBridge <noreply@{domain}>"
    return {
        "api_key": api_key,
        "domain": domain,
        "base_url": base_url.rstrip("/"),
        "sender": sender,
    }


def send_password_reset_otp_email(to_email: str, otp_code: str, patient_name: str) -> bool:
    """Sends the password-reset OTP email via Mailgun's HTTP API. Returns
    True only on a confirmed-sent (2xx from Mailgun); False in every other
    case (not configured, network failure, non-2xx from Mailgun) --
    callers must treat False as "could not confirm delivery", not as an
    error to surface to the end user (see module docstring)."""
    config = _mailgun_config()
    if config is None:
        logger.warning(
            "send_password_reset_otp_email: Mailgun not configured "
            "(MAILGUN_API_KEY/MAILGUN_DOMAIN unset) -- email not sent."
        )
        return False

    subject = "Your MediBridge password reset code"
    text_body = (
        f"Hello {patient_name},\n\n"
        f"Your MediBridge password reset code is: {otp_code}\n\n"
        "This code expires in 10 minutes. If you did not request a "
        "password reset, you can safely ignore this email.\n\n"
        "-- MediBridge"
    )
    html_body = (
        f"<p>Hello {patient_name},</p>"
        f"<p>Your MediBridge password reset code is: <strong>{otp_code}</strong></p>"
        "<p>This code expires in 10 minutes. If you did not request a "
        "password reset, you can safely ignore this email.</p>"
        "<p>-- MediBridge</p>"
    )

    url = f"{config['base_url']}/{config['domain']}/messages"
    try:
        response = requests.post(
            url,
            auth=("api", config["api_key"]),
            data={
                "from": config["sender"],
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if 200 <= response.status_code < 300:
            return True
        logger.error(
            "send_password_reset_otp_email: Mailgun returned status=%s body=%s",
            response.status_code, response.text[:500],
        )
        return False
    except requests.RequestException:
        logger.exception("send_password_reset_otp_email: Mailgun request failed")
        return False
