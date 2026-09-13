"""
Malaysian NRIC (MyKad) OCR extraction, used by
routers/self_registration.py::verify_self_registration_photos to check a
photographed physical NRIC card against an existing Patient record.

Two modes, same "LLM mode with a deterministic/regex fallback" pattern as
ai/summarize.py:
1. Local-LLM mode (default, on-prem -- P4.3): sends the image to the local
   Ollama vision model (see ai/local_llm.py) with a tightly-scoped prompt
   asking for strict JSON {"ic_number": ..., "name": ...}. Nothing leaves
   the machine. Any parse/validation failure is treated as "extraction
   failed" -- this NEVER raises out to the caller (mirrors summarize.py's
   `generate_text(...) or _fallback...` -- an unreachable Ollama server or a
   malformed model response must degrade, not break a public,
   unauthenticated registration endpoint).
2. Tesseract fallback (Ollama/the vision model unavailable, or the LLM
   call/parse failed):
   adapts ai/ocr.py's `extract_text_from_image` for in-memory bytes (this
   module never writes the uploaded photo to disk -- see
   self_registration.py's verify-photos docstring for why), then applies a
   regex over the raw text to find a 12-digit IC number. Name extraction
   via pure Tesseract is unreliable -- best-effort only (longest
   all-uppercase, non-boilerplate, digit-free line). Every result carries a
   `method` ("llm" | "tesseract") and `name_confidence` ("high" | "low") so
   the caller can be stricter about a Tesseract-derived name match if it
   wants to; today the caller (self_registration.py) treats both the same
   for simplicity, but the fields are there for a future tightening.

IMPORTANT, explicit limitation (same honesty-about-limits discipline as
ai/ocr.py's own docstring): this module has NOT been validated against a
real MyKad photo in this environment -- no physical sample card was
available. The birthdate-century heuristic and the "back of card repeats
the IC number" assumption below are both best-effort/documented guesses,
not confirmed facts about every MyKad print era. See
self_registration.py's verify-photos docstring for how the back-image
check is deliberately treated as a SOFT signal because of this.
"""
import io
import json
import logging
import re
from datetime import date, datetime
from typing import Optional

from .local_llm import generate_vision_text

logger = logging.getLogger("clarion.nric_ocr")

# Malaysian NRIC facts hardcoded here (no external format library used --
# this is a small, stable, well-documented national format):
#   - 12 digits total, conventionally displayed as YYMMDD-PB-#### but OCR
#     output is dash-inconsistent, so every extraction path strips to bare
#     digits FIRST and validates length==12 before anything else.
#   - The first 6 digits are the holder's birthdate (YYMMDD). The next 2
#     (PB) are a state/place-of-birth code and the last 4 are a serial --
#     neither is used by this module (only the IC number as a whole, for
#     matching against Patient.national_id, and the birthdate, for
#     matching against Patient.date_of_birth).
_DIGITS_RE = re.compile(r"\D")
_IC_CANDIDATE_RE = re.compile(r"\d[\d\-]{9,15}\d")

# Extraction of a name via pure Tesseract is unreliable (see module
# docstring) -- these are the boilerplate tokens most MyKad OCR passes will
# also pick up (issuing-authority/demographic boilerplate printed on every
# card), excluded so they don't get mistaken for the holder's actual name.
_MYKAD_BOILERPLATE_TOKENS = {
    "MYKAD", "KAD", "PENGENALAN", "MALAYSIA", "WARGANEGARA", "ISLAM",
    "LELAKI", "PEREMPUAN", "IDENTITY", "CARD", "JABATAN", "PENDAFTARAN",
    "NEGARA",
}
_MIN_NAME_LINE_LENGTH = 6


def _extract_digits(value: str) -> str:
    return _DIGITS_RE.sub("", value or "")


def _resolve_dob_from_yymmdd(yymmdd: str) -> Optional[str]:
    """The century (19xx vs 20xx) is genuinely ambiguous from a bare
    YYMMDD prefix alone. Heuristic used here: try both centuries, discard
    any candidate that would be a future date OR an implausible age
    (>100 or <0 years old as of today), and return whichever single
    candidate survives. In the (rare) case both centuries happen to survive
    -- e.g. a serial mid-transition where NEITHER exceeds the plausible-age
    bound -- the more recent (2000s) candidate is preferred, since a
    freshly self-registering adult patient skews younger in practice than
    someone who'd be centenarian-or-older. This is a heuristic, not a
    guarantee -- documented explicitly per this module's docstring."""
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None

    yy, mm, dd = yymmdd[0:2], yymmdd[2:4], yymmdd[4:6]
    today = datetime.utcnow().date()
    candidates = []
    for century in (2000, 1900):
        year = century + int(yy)
        try:
            candidate = date(year, int(mm), int(dd))
        except ValueError:
            continue  # not a real calendar date (e.g. MM=13) under this century guess
        if candidate > today:
            continue  # future date -- can't be a real birthdate
        age_years = (today - candidate).days / 365.25
        if age_years > 100 or age_years < 0:
            continue
        candidates.append(candidate)

    if not candidates:
        return None
    candidates.sort(reverse=True)  # prefer the more recent (2000s) candidate if more than one survives
    return candidates[0].isoformat()


def dob_from_ic_number(ic_number: str) -> Optional[str]:
    """First 6 digits of a normalized (digits-only) 12-digit IC number ->
    ISO date string, via the century heuristic above. Returns None for
    anything that isn't a clean 12-digit string or doesn't resolve to a
    plausible date under either century guess."""
    if not ic_number or len(ic_number) != 12 or not ic_number.isdigit():
        return None
    return _resolve_dob_from_yymmdd(ic_number[:6])


_NRIC_PROMPT = (
    "This image is a photograph of a Malaysian MyKad (national "
    "identity card), either the front or back side. Extract ONLY "
    "the following two fields and respond with STRICT JSON and "
    "nothing else -- no markdown fences, no commentary:\n"
    '{"ic_number": "<the 12-digit IC number exactly as printed, '
    'dashes optional>", "name": "<the cardholder full name exactly '
    'as printed, or an empty string if this side of the card does '
    'not show a name>"}\n'
    "If you cannot confidently read a field, use an empty string "
    "for that field rather than guessing."
)


def _extract_via_llm(image_bytes: bytes, media_type: str) -> Optional[dict]:
    """Returns None on ANY failure (Ollama unreachable, model not pulled,
    malformed/unparseable response, ic_number that doesn't reduce to
    exactly 12 digits) -- never raises. Caller falls back to Tesseract.
    `media_type` is accepted for signature stability but unused -- Ollama's
    vision models take raw base64 image bytes without a MIME hint."""
    raw_text = generate_vision_text(_NRIC_PROMPT, image_bytes, max_tokens=200)
    if raw_text is None:
        return None
    try:
        # Defensive: some models wrap JSON in a markdown code fence despite
        # being asked not to -- strip a leading/trailing ``` block if present
        # rather than failing outright on an otherwise-good response.
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        data = json.loads(raw_text)
        ic_digits = _extract_digits(str(data.get("ic_number", "")))
        if len(ic_digits) != 12:
            return None
        name = str(data.get("name", "")).strip() or None
        return {
            "ic_number": ic_digits,
            "name": name,
            "method": "llm",
            "name_confidence": "high" if name else "low",
        }
    except Exception:
        # Malformed/unparseable model response -- degrade to Tesseract
        # instead (same discipline as ai/summarize.py::generate_handover_brief).
        logger.exception("nric_ocr: local-LLM response unparseable, falling back to Tesseract")
        return None


def _guess_name_from_text(text: str) -> Optional[str]:
    """Best-effort only (see module docstring) -- longest all-uppercase,
    digit-free line, excluding known MyKad boilerplate tokens. Pure-Tesseract
    name extraction is unreliable; this is a heuristic, not a guarantee."""
    candidates = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < _MIN_NAME_LINE_LENGTH:
            continue
        if any(ch.isdigit() for ch in stripped):
            continue
        if stripped != stripped.upper():
            continue
        letters_only = re.sub(r"[^A-Z]", "", stripped)
        if len(letters_only) < _MIN_NAME_LINE_LENGTH:
            continue
        tokens = set(stripped.split())
        if tokens & _MYKAD_BOILERPLATE_TOKENS:
            continue
        candidates.append(stripped)

    if not candidates:
        return None
    return max(candidates, key=len)


def _find_ic_number_in_text(text: str) -> Optional[str]:
    for match in _IC_CANDIDATE_RE.finditer(text):
        digits = _extract_digits(match.group(0))
        if len(digits) == 12:
            return digits
    return None


def _extract_via_tesseract(image_bytes: bytes) -> dict:
    """In-memory adaptation of ai/ocr.py::extract_text_from_image -- takes
    raw bytes rather than a file path, since this module deliberately never
    persists the uploaded NRIC photo to disk (see self_registration.py's
    verify-photos docstring)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("nric_ocr: pytesseract/pillow not available -- OCR fallback unusable.")
        return {
            "ic_number": None, "name": None, "method": "tesseract",
            "name_confidence": "low", "raw_text": None,
        }

    try:
        image = Image.open(io.BytesIO(image_bytes))
        raw_text = pytesseract.image_to_string(image)
    except Exception:
        logger.exception("nric_ocr: Tesseract OCR failed")
        return {
            "ic_number": None, "name": None, "method": "tesseract",
            "name_confidence": "low", "raw_text": None,
        }

    # DEBUG-only, deliberately -- this is the literal card text (NRIC +
    # name), genuinely sensitive, unlike the short internal_note codes
    # logged at INFO elsewhere in the self-registration flow. Under this
    # app's logging.basicConfig(level=INFO) default (see main.py) this line
    # never emits; it only shows up if someone explicitly raises the log
    # level to DEBUG for local debugging of a failed extraction.
    logger.debug("nric_ocr: tesseract raw_text=%r", raw_text)

    return {
        "ic_number": _find_ic_number_in_text(raw_text),
        "name": _guess_name_from_text(raw_text),
        "method": "tesseract",
        "name_confidence": "low",
        "raw_text": raw_text,
    }


def extract_nric_fields(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Public entry point. Tries the local-LLM path first; falls back to
    Tesseract if Ollama is unreachable or the LLM extraction fails. Always
    returns a dict with at least `ic_number` (Optional[str],
    normalized to bare digits, or None if extraction failed) and `name`
    (Optional[str]) -- never raises. `method` tells the caller which path
    produced the result ("llm" or "tesseract"), and `name_confidence`
    ("high" | "low") flags that a Tesseract-derived name is best-effort
    only (see module docstring)."""
    llm_result = _extract_via_llm(image_bytes, media_type)
    if llm_result is not None:
        return llm_result
    return _extract_via_tesseract(image_bytes)
