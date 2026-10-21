"""Phone-number parsing shared by the schema validators and the emergency-contact alerts.
No imports from the rest of the app, so anything can use it without a cycle."""
import os
import re

# Only what a person types into a phone field. Anything else (letters, "ext 5", a note) is
# refused rather than having its digits glued into a different, valid-looking number.
_TYPED = re.compile(r"^\+?[\d\s\-().]+$")


def normalize_phone(raw):
    """Digits only, Malaysian local form (0123456789) turned into 60123456789.
    None if it isn't a plausible phone number."""
    if not isinstance(raw, str) or not _TYPED.match(raw.strip()):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "60" + digits[1:]
    return digits if 9 <= len(digits) <= 15 else None


def sms_allowed(key):
    """May we text this (already normalized) number? Default: Malaysian mobiles only (60 1x),
    which keeps premium-rate, short-code and satellite ranges out. Widen with
    CONTACT_SMS_ALLOWED_PREFIXES, e.g. "601,651"."""
    prefixes = [p.strip() for p in os.environ.get("CONTACT_SMS_ALLOWED_PREFIXES", "601").split(",") if p.strip()]
    return bool(key) and any(key.startswith(p) for p in prefixes)
