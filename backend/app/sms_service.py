"""Outbound SMS, used for emergency-contact alerts. Same shape as email_service: the
environment is read on every call, it returns True only on a confirmed send, and it
never raises (apart from SmsRejected; the caller -- a retried background job -- decides what a False means).

  SMS_PROVIDER=twilio  Twilio REST; needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM
  SMS_PROVIDER=log     writes a masked line to the log instead of sending; only honoured
                       when APP_ENV=demo, so a production box can never "succeed" silently
  (unset)              not configured -> False, the job is retried and eventually gives up
"""
import logging
import os

import requests

logger = logging.getLogger("clarion.sms")

_TIMEOUT_SECONDS = 10


class SmsRejected(Exception):
    """The gateway refused this message for good (bad number, opted out, bad credentials):
    retrying cannot help, unlike a timeout or a 5xx."""


def _masked(number: str) -> str:
    return f"***{number[-3:]}" if len(number) > 3 else "***"


def send_sms(to_e164: str, text: str) -> bool:
    provider = (os.environ.get("SMS_PROVIDER") or "").strip().lower()
    if provider == "log":
        if (os.environ.get("APP_ENV") or "").strip().lower() != "demo":
            logger.error("SMS_PROVIDER=log is only allowed with APP_ENV=demo -- SMS not sent.")
            return False
        logger.warning("DEMO SMS to %s (%d chars) -- not actually sent", _masked(to_e164), len(text))
        return True
    if provider != "twilio":
        logger.warning("SMS not configured (SMS_PROVIDER unset) -- SMS to %s not sent.", _masked(to_e164))
        return False

    sid, token, sender = (os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))
    if not (sid and token and sender):
        logger.error("SMS_PROVIDER=twilio but TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM is missing.")
        return False
    try:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"To": f"+{to_e164.lstrip('+')}", "From": sender, "Body": text},
            timeout=_TIMEOUT_SECONDS,
        )
        if 200 <= response.status_code < 300:
            return True
        logger.error("Twilio returned status=%s for %s", response.status_code, _masked(to_e164))
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise SmsRejected(f"Twilio status {response.status_code}")
        return False
    except requests.RequestException:
        logger.exception("Twilio request failed for %s", _masked(to_e164))
        return False
