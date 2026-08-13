import re

# Malaysian NRICs are conventionally displayed with dashes
# (e.g. "520314-01-1234") but are frequently typed without them
# ("520314011234"). Every place an NRIC is accepted as user input and
# compared against a stored Patient.national_id should normalize BOTH
# sides with this helper before comparing, so dash/no-dash variants (and
# incidental whitespace) resolve to the same account.
_NON_ALNUM_RE = re.compile(r"[^0-9A-Za-z]")


def normalize_nric(value: str) -> str:
    """Strip everything except letters/digits and uppercase the result, e.g.
    "520314-01-1234", "520314011234", and "alphacase99887" all normalize to
    the same canonical form ("520314011234" / "ALPHACASE99887"). Does not
    validate format/length -- callers still get a "not found" style outcome
    for garbage input, same as today.

    Uppercasing (rather than lowercasing) matches how Malaysian NRICs and
    most alphanumeric ID formats are conventionally displayed. Every
    comparison against a stored Patient.national_id MUST normalize BOTH
    sides with this helper -- see _resolve_patient_by_nric in
    auth_router.py, the sole place NRIC matching happens today."""
    if value is None:
        return ""
    return _NON_ALNUM_RE.sub("", value).upper()
