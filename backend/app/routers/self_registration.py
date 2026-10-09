"""
Self-service patient registration via NRIC-OCR identity verification.

Today, a patient account can ONLY be created by staff, in person (POST
/auth/patients/{id}/issue-account, admin/records_officer-only -- see that
endpoint's docstring in auth_router.py, and the web console's own copy:
"Patients don't self-register -- NRIC alone isn't secret in Malaysia...").
This router adds a *self-service alternative* to that, NOT a replacement:
both endpoints coexist. Instead of "verify in person", this flow proves
identity with several independent factors stacked together:

  1. NRIC + full name, checked against an EXISTING Patient row a hospital
     already created (see /start below). The caller does NOT separately
     supply a date of birth -- a standard Malaysian NRIC already encodes
     the holder's birthdate in its first 6 digits, so /start derives the
     expected date of birth from the NRIC itself and checks it against the
     stored Patient row as a self-consistency check, not as a second
     independently-known factor (see ai/nric_ocr.py::dob_from_ic_number).
     This endpoint NEVER creates a new Patient -- if the NRIC doesn't
     resolve to one, or that Patient already has a User account,
     registration is rejected and the caller is told to visit a facility,
     exactly like today's manual-only status quo.
  2. A one-time code emailed to an address the caller provides (proves
     access to that inbox -- see /verify-otp).
  3. OCR-verified photos of the physical NRIC card, matched against the
     resolved Patient row (see /verify-photos and ai/nric_ocr.py).

Anyone who fails self-verification (5 failed photo attempts) is flagged
`flagged_manual_review` and directed back to the existing staff-issued
`issue_patient_account` flow -- no new staff-facing "unflag" endpoint is
needed, since that endpoint doesn't consult this table at all.
"""
import asyncio
import difflib
import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..email_service import send_self_registration_otp_email
from ..nric import normalize_nric
from ..rate_limit import limiter
from ..ai.nric_ocr import extract_nric_fields, dob_from_ic_number
from .auth_router import _resolve_patient_by_nric, _with_missing_profile_fields

logger = logging.getLogger("clarion.self_registration")

router = APIRouter(prefix="/auth/self-register", tags=["self-registration"])

# ---- Policy constants ----
# OTP request/verify limits are deliberately the SAME constants
# auth.py already defines for the email-OTP password-reset flow
# (OTP_MAX_REQUESTS_PER_WINDOW / OTP_REQUEST_WINDOW_MINUTES /
# OTP_MAX_VERIFY_ATTEMPTS / OTP_EXPIRY_MINUTES / OTP_LENGTH) rather than a
# self-registration-specific set -- there's no product reason for this
# flow's OTP to behave differently from the reset flow's, and reusing the
# constants means a future policy tweak (e.g. raising OTP_EXPIRY_MINUTES)
# automatically applies everywhere an OTP is used instead of needing to be
# kept in sync across two places.
PHOTO_VERIFY_MAX_ATTEMPTS = 5
# How long a caller has, after verifying their OTP, to submit NRIC photos
# before having to restart from /start. 30 minutes is generous for someone
# physically fetching their NRIC card and taking two photos, while bounding
# how long a "pending_photo" row can sit around half-finished.
PHOTO_VERIFICATION_WINDOW_MINUTES = 30
# Same difflib.SequenceMatcher threshold used both at /start (typed name vs
# Patient.full_name) and at /verify-photos (OCR-extracted name vs
# Patient.full_name) -- one constant so the two checks can't silently drift
# apart.
NAME_MATCH_THRESHOLD = 0.85
# Same 15MB-per-file convention as ai_router.MAX_UPLOAD_BYTES (this
# endpoint OCRs two photographed ID card images, not video/bulk data).
# Defined locally rather than imported from ai_router to avoid a
# router-to-router import for a single constant.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Opt-in ONLY, unset by default -- deliberately a SEPARATE env var from
# LOG_LEVEL (see main.py), not folded into DEBUG logging, because this
# writes the literal uploaded NRIC photo bytes to disk, which is a real
# divergence from this endpoint's documented "never persisted anywhere"
# privacy guarantee (see verify_self_registration_photos' docstring below).
# Local debugging only: set SELF_REGISTER_DEBUG_SAVE_DIR to a directory
# path to have each /verify-photos call dump its two images there so you
# can visually inspect exactly what Tesseract/the LLM saw (blur, wrong
# orientation, wrong side of the card, etc.) -- raw OCR text alone doesn't
# tell you WHY extraction failed, only THAT it did. Delete the directory's
# contents yourself when done; nothing here auto-expires or auto-cleans it.
_DEBUG_SAVE_DIR = os.environ.get("SELF_REGISTER_DEBUG_SAVE_DIR")


def _debug_save_photo(kind: str, image_bytes: bytes, media_type: str) -> "Path | None":
    """No-op (returns None) unless SELF_REGISTER_DEBUG_SAVE_DIR is
    explicitly set (see above). Never raises -- a debug convenience must
    not break the actual verification request if e.g. the directory
    doesn't exist or isn't writable. Returns the saved image's path (not
    just whether it succeeded) so `_debug_save_ocr_result` below can write
    its companion .txt file under the SAME base filename, keeping an
    image and the OCR result it produced trivially pairable by name."""
    if not _DEBUG_SAVE_DIR:
        return None
    try:
        ext = "png" if "png" in (media_type or "") else "jpg"
        out_dir = Path(_DEBUG_SAVE_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y%m%d_%H%M%S_%f')}_{kind}.{ext}"
        image_path = out_dir / filename
        image_path.write_bytes(image_bytes)
        logger.debug("self_registration: debug-saved %s photo to %s", kind, image_path)
        return image_path
    except Exception:
        logger.exception("self_registration: failed to debug-save %s photo (non-fatal)", kind)
        return None


def _debug_save_ocr_result(image_path: "Path | None", result: dict) -> None:
    """Companion to `_debug_save_photo` -- writes the OCR extraction result
    for one image (method used, extracted ic_number/name, and Tesseract's
    raw_text when present -- the LLM path doesn't return raw_text, only its
    already-parsed fields) to a sibling `<same base name>.txt` file, so it
    can be read directly instead of hunting through the (much noisier,
    PIL/pytesseract-subprocess-cluttered) DEBUG log for the one line that
    matters. No-op if the image wasn't saved (SELF_REGISTER_DEBUG_SAVE_DIR
    unset, or the image save itself failed) -- never raises."""
    if image_path is None:
        return
    try:
        # "raw_text" key ABSENT (LLM mode -- see _extract_via_llm, which
        # never sets this key) is a genuinely different situation from the
        # key being PRESENT but empty/None (Tesseract mode: an empty string
        # means it ran and found literally nothing; None means the OCR call
        # itself raised -- see _extract_via_tesseract's except branch). `or`
        # would collapse all three into one misleading message, so check
        # key presence explicitly instead.
        if "raw_text" not in result:
            raw_text_note = "(not available -- LLM mode returns parsed fields only, no raw OCR text)"
        elif result["raw_text"] is None:
            raw_text_note = "(None -- the Tesseract OCR call itself raised; see server log for the traceback)"
        elif result["raw_text"] == "":
            raw_text_note = "(empty string -- Tesseract ran but found no text at all in this image)"
        else:
            raw_text_note = result["raw_text"]

        lines = [
            f"method: {result.get('method')}",
            f"ic_number: {result.get('ic_number')}",
            f"name: {result.get('name')}",
            f"name_confidence: {result.get('name_confidence')}",
            "",
            "raw_text:",
            raw_text_note,
        ]
        image_path.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        logger.exception("self_registration: failed to debug-save OCR result text file (non-fatal)")


_START_MISMATCH_ERROR = (
    "The details provided don't match our records. Please check and try "
    "again, or visit a registration counter for help."
)
_ACCOUNT_EXISTS_ERROR = "An account already exists for this NRIC. Try 'Forgot password', or contact staff."
_VERIFY_OTP_GENERIC_ERROR = "Invalid or expired verification code."
_RESTART_REQUIRED_ERROR = "Please restart registration from the beginning."


def _normalize_name_for_match(name: str) -> str:
    return " ".join((name or "").strip().casefold().split())


def _names_reasonably_match(a: str, b: str, threshold: float = NAME_MATCH_THRESHOLD) -> bool:
    """difflib.SequenceMatcher on normalized/casefolded names -- same
    technique/threshold used at both /start (user-typed name vs
    Patient.full_name) and /verify-photos (OCR-extracted name vs
    Patient.full_name). Not a cryptographic-strength check -- it's a
    typo/OCR-noise tolerant fuzzy match, deliberately generous enough to
    absorb minor spelling variance while still catching a genuinely
    different name."""
    na, nb = _normalize_name_for_match(a), _normalize_name_for_match(b)
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def _get_or_reserve_attempt(db: Session, patient: models.Patient, email: str) -> "models.SelfRegistrationAttempt | None":
    """Fetch (or create) this patient's SelfRegistrationAttempt row --
    dedup via patient_id's unique index, same "re-registering updates in
    place" pattern as NfcRegisterRequest/EmergencyToken elsewhere in this
    codebase. Deliberately does NOT touch any OTP/photo-flow state yet
    (see _begin_new_otp_round below for that) -- just updates `email`
    (harmless even if this call ends up rate-limited; it's only "the
    address to use if/when a code IS actually sent") and returns the row
    so start_self_registration can run the OTP request-rate-limit check
    against its real, persisted counters BEFORE deciding whether a fresh
    OTP round is actually about to be issued.

    Returns None (a deliberate no-op) if the existing row is already
    flagged_manual_review. Once flagged, the self-service path is meant to
    be a genuine dead end (see verify_self_registration_photos' 5th-failure
    branch) -- if /start reset a flagged row back to pending_otp, an
    attacker who already knows this patient's NRIC+name (the exact bar
    /start itself requires -- date of birth is now DERIVED from the NRIC
    itself rather than an independently-known secret, see /start's
    docstring -- but NRIC+name is still a deliberately higher bar than the
    password-reset flow's NRIC-only lookup) could simply call /start again
    for a fresh 5 photo attempts, defeating the entire point of the flag. The caller
    (start_self_registration) still returns the same generic 200
    success-shaped response whether this returns a real attempt or None --
    mirrors request_password_reset_otp's "no email on file -> still
    generic response" no-op (see that function's docstring) -- so a
    flagged state is not itself an externally observable signal.
    """
    existing = (
        db.query(models.SelfRegistrationAttempt)
        .filter(models.SelfRegistrationAttempt.patient_id == patient.id)
        .first()
    )

    if existing and existing.status == "flagged_manual_review":
        return None

    # otp_request_count explicitly seeded to 0 (rather than relying on the
    # column's DB-side default) for a brand-new row -- SQLAlchemy only
    # applies a Column(default=...) at flush/INSERT time, so reading this
    # attribute on an unflushed new instance would otherwise be None, and
    # `None >= auth.OTP_MAX_REQUESTS_PER_WINDOW` below would raise.
    attempt = existing or models.SelfRegistrationAttempt(patient_id=patient.id, otp_request_count=0)
    attempt.email = email
    db.add(attempt)
    return attempt


def _begin_new_otp_round(attempt: models.SelfRegistrationAttempt) -> None:
    """Resets everything for a FRESH OTP + photo-verification round.

    Only ever called once start_self_registration's rate-limit check has
    already confirmed a new OTP is actually about to be issued -- NOT
    unconditionally on every /start call. Doing this unconditionally
    (an earlier version of this code did) was a real bug caught by this
    feature's own ad-hoc verification script: a rate-limited /start retry
    would still run the reset before hitting the 429, silently destroying
    the caller's still-valid, not-yet-expired OTP from an earlier
    successful call in the same window -- leaving them holding a code
    (already emailed to them) that could no longer verify. Callers other
    than start_self_registration should not call this directly."""
    attempt.otp_verified = False
    attempt.otp_attempt_count = 0
    attempt.photo_verify_attempt_count = 0
    attempt.status = "pending_otp"
    attempt.photo_verification_deadline = None
    attempt.last_ocr_failure_reason = None


@router.post("/start")
@limiter.limit("10/minute")  # per-IP, ON TOP OF the persisted OTP
# request-window counter below (Security Audit M2 -- that counter is
# per-NRIC, so it does nothing against a caller scripting through many
# different NRICs from one IP; _resolve_patient_by_nric also runs here on
# every call).
def start_self_registration(request: Request, payload: schemas.SelfRegisterStartRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated. Step 1 of self-service registration."""
    patient = _resolve_patient_by_nric(db, payload.national_id)
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="No matching patient record was found. Please visit a registration counter to be added to the system first.",
        )

    existing_user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
    if existing_user:
        raise HTTPException(status_code=409, detail=_ACCOUNT_EXISTS_ERROR)

    # Enumeration-safety tradeoff, deliberate and DIFFERENT from the
    # password-reset flow's anonymization: a 400 here confirms "a record
    # exists that resolves to a real patient" to anyone who could ALSO
    # correctly supply that patient's NRIC + full name (date of birth is no
    # longer an independently-known factor here -- it's derived FROM the
    # NRIC below and checked as a self-consistency check against the stored
    # record, not asked of the caller) -- still a materially higher bar
    # than the reset flow's NRIC-only lookup (which is why that flow
    # anonymizes so aggressively and this one doesn't need to as much). The
    # OTP (proof of access to a specific
    # inbox) and OCR-verified-photo (proof of physical card possession)
    # gates further downstream are what actually prevent a takeover here,
    # not response-shape secrecy at this step -- so this endpoint trades a
    # small amount of enumeration signal for a genuinely actionable error
    # message ("the details don't match" vs. reset's fully generic
    # "if this NRIC has a registered account...").
    name_ok = _names_reasonably_match(payload.full_name, patient.full_name)
    # dob_ok is no longer a check against an independently-supplied
    # date_of_birth (the client doesn't send one -- see
    # schemas.SelfRegisterStartRequest) -- it's now a SELF-CONSISTENCY check
    # between the NRIC's own encoded birthdate and the stored Patient row.
    # dob_from_ic_number needs a bare-digits string; payload.national_id may
    # be dash-formatted, so strip non-digits first (same normalization
    # dob_from_ic_number's own docstring/callers expect -- see
    # ai/nric_ocr.py). A None result (non-standard/unparseable NRIC) is
    # treated as a failed check, same as any other mismatch below.
    ic_digits = re.sub(r"\D", "", payload.national_id or "")
    dob_ok = dob_from_ic_number(ic_digits) == patient.date_of_birth
    if not (name_ok and dob_ok):
        raise HTTPException(status_code=400, detail=_START_MISMATCH_ERROR)

    attempt = _get_or_reserve_attempt(db, patient, payload.email)

    if attempt is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # OTP *request* rate limiting -- same rolling-window counter
        # semantics as auth_router.request_password_reset_otp, applied to
        # this SelfRegistrationAttempt row instead of a User row (no User
        # exists yet at this stage -- that's the whole point of this flow).
        # Deliberately checked BEFORE _begin_new_otp_round runs (see that
        # function's docstring) -- a rate-limited call must leave any
        # still-valid OTP from an earlier successful call in this same
        # window completely untouched.
        window_start = attempt.otp_request_window_start
        if not window_start or now - window_start > timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES):
            attempt.otp_request_window_start = now
            attempt.otp_request_count = 0

        if attempt.otp_request_count >= auth.OTP_MAX_REQUESTS_PER_WINDOW:
            db.add(attempt)
            db.commit()
            retry_after = attempt.otp_request_window_start + timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES)
            raise HTTPException(
                status_code=429,
                detail=f"Too many verification code requests. Try again after {retry_after.isoformat()}Z.",
            )

        attempt.otp_request_count = (attempt.otp_request_count or 0) + 1
        _begin_new_otp_round(attempt)

        otp_code = auth.generate_otp_code()
        attempt.otp_code_hash = auth.hash_otp_code(otp_code)
        attempt.otp_expires_at = now + timedelta(minutes=auth.OTP_EXPIRY_MINUTES)
        db.add(attempt)
        db.commit()

        # send_self_registration_otp_email degrades gracefully (logs,
        # returns False) if Mailtrap isn't configured or the call fails --
        # deliberately NOT branching the response on its return value, same
        # discipline as request_password_reset_otp.
        send_self_registration_otp_email(payload.email, otp_code, patient.full_name)
        log_access(db, patient.id, "system", None, "self_register_otp_requested")
    # else: existing row was flagged_manual_review -- deliberate no-op, see
    # _get_or_reserve_attempt's docstring. No log_access call here (nothing
    # actually happened this call); the flagging event itself was already
    # logged once, at the moment it occurred (see verify_self_registration_photos).

    return {
        "status": "ok",
        "detail": "If your details matched a registered patient, a verification code was sent to the email provided.",
        "next_step": "verify_otp",
    }


@router.post("/verify-otp")
@limiter.limit("10/minute")  # per-IP, ON TOP OF this endpoint's own
# per-attempt-row auth.OTP_MAX_VERIFY_ATTEMPTS (Security Audit M2 -- same
# distributed-spray reasoning as POST /auth/reset-password-with-otp).
def verify_self_registration_otp(request: Request, payload: schemas.SelfRegisterVerifyOtpRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated. Step 2 of self-service registration.

    Generic 400 for every failure mode (unknown NRIC, no pending attempt,
    expired OTP, wrong code) -- mirrors
    auth_router._RESET_WITH_OTP_GENERIC_ERROR's exact anti-enumeration
    style: a caller can't tell "no such attempt" from "right attempt, wrong
    code" from the response alone.
    """
    patient = _resolve_patient_by_nric(db, payload.national_id)
    attempt = (
        db.query(models.SelfRegistrationAttempt)
        .filter(models.SelfRegistrationAttempt.patient_id == patient.id)
        .first()
        if patient else None
    )

    if not attempt or attempt.status != "pending_otp" or not attempt.otp_code_hash or not attempt.otp_expires_at:
        raise HTTPException(status_code=400, detail=_VERIFY_OTP_GENERIC_ERROR)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if now > attempt.otp_expires_at:
        # Expired -- clear it rather than leaving a stale hash guessable
        # indefinitely; caller must call /start again for a fresh code.
        attempt.otp_code_hash = None
        attempt.otp_expires_at = None
        attempt.otp_attempt_count = 0
        db.add(attempt)
        db.commit()
        raise HTTPException(status_code=400, detail=_VERIFY_OTP_GENERIC_ERROR)

    if not auth.verify_otp_code(payload.otp_code, attempt.otp_code_hash):
        attempt.otp_attempt_count = (attempt.otp_attempt_count or 0) + 1
        if attempt.otp_attempt_count >= auth.OTP_MAX_VERIFY_ATTEMPTS:
            # 5 wrong tries -> invalidate the OTP entirely, same tradeoff as
            # reset_password_with_otp: forces a fresh /start call rather
            # than counting forever.
            attempt.otp_code_hash = None
            attempt.otp_expires_at = None
            attempt.otp_attempt_count = 0
        db.add(attempt)
        db.commit()
        raise HTTPException(status_code=400, detail=_VERIFY_OTP_GENERIC_ERROR)

    attempt.otp_verified = True
    attempt.status = "pending_photo"
    attempt.photo_verification_deadline = now + timedelta(minutes=PHOTO_VERIFICATION_WINDOW_MINUTES)
    attempt.otp_code_hash = None
    attempt.otp_expires_at = None
    attempt.otp_attempt_count = 0
    db.add(attempt)
    db.commit()

    log_access(db, patient.id, "system", None, "self_register_otp_verified")

    return {
        "status": "ok",
        "detail": "Code verified. Please photograph the front and back of your NRIC.",
        "next_step": "verify_photos",
        "photo_attempts_remaining": PHOTO_VERIFY_MAX_ATTEMPTS,
    }


def _evaluate_photo_verification(front_result: dict, back_result: dict, patient: models.Patient):
    """Runs the required checks in a fixed priority order and returns
    (matched: bool, client_message: Optional[str], internal_reason: Optional[str]).

    client_message is None when matched is True; internal_reason is always
    populated with a short debugging note (even on a match, for the soft
    back-image signal -- see below) and is NEVER shown verbatim to the
    caller (see verify_self_registration_photos).

    All of the following must pass for a match: extracted ic_number
    (normalized) == Patient.national_id (normalized); extracted name
    fuzzy-matches Patient.full_name; the IC-derived birthdate ==
    Patient.date_of_birth. Deliberately re-checks against the PATIENT row,
    not the user-typed values from /start -- those were already validated
    against the Patient row once, at /start; re-checking here against the
    same single source of truth (rather than cross-checking OCR output
    against the user's own earlier typed input) keeps there from being two
    independent "truths" that could drift apart.

    The back-image ic_number check is a SOFT signal only (see
    ai/nric_ocr.py's module docstring for why -- whether this MyKad print
    era repeats the ID number on the back is unconfirmed in this
    environment, no real sample card available) -- it never blocks a match
    on its own if every front-vs-database check above passed cleanly.
    """
    front_ic = front_result.get("ic_number")
    if not front_ic:
        return False, (
            "We couldn't clearly read the ID number on the front photo. "
            "Please retake in good lighting with the whole card visible."
        ), "front_ic_extraction_failed"

    expected_ic = normalize_nric(patient.national_id)
    if front_ic != expected_ic:
        return False, "The ID number doesn't match our records.", "ic_number_mismatch"

    front_name = front_result.get("name")
    if not front_name:
        return False, (
            "We couldn't clearly read the name on the front photo. "
            "Please retake in good lighting with the whole card visible."
        ), "name_extraction_failed"

    if not _names_reasonably_match(front_name, patient.full_name):
        return False, "The name doesn't match our records.", "name_mismatch"

    ic_dob = dob_from_ic_number(front_ic)
    if ic_dob != patient.date_of_birth:
        return False, "The birthdate encoded in the ID number doesn't match our records.", "dob_mismatch"

    back_ic = back_result.get("ic_number")
    if not back_ic:
        soft_note = "back_ic_extraction_inconclusive"
    elif back_ic != front_ic:
        soft_note = "back_ic_mismatch"
    else:
        soft_note = "back_ic_confirmed"

    return True, None, soft_note


@router.post("/verify-photos")
@limiter.limit("10/minute")  # per-IP -- coarse backstop layered ON TOP OF
# this endpoint's own photo_verify_attempt_count self-limiting, same
# reasoning as emergency.py's two unauthenticated scan endpoints (10/minute
# per-IP on top of their own DB-persisted logic). Unlike the near-free
# OTP-check endpoints above, this one does real image decode/OCR work
# (and, in LLM mode, an external API call) per request -- unauthenticated
# and comparatively expensive to process, so it's worth a per-IP backstop
# even though photo_verify_attempt_count already caps abuse PER ATTEMPT ROW
# (a caller could otherwise script through many different NRICs' attempts
# from one IP without ever tripping the per-row cap).
async def verify_self_registration_photos(
    request: Request,
    national_id: str = Form(...),
    front_image: UploadFile = File(...),
    back_image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Public, unauthenticated. multipart/form-data. Step 3 of self-service
    registration.

    Deliberately does NOT persist front_image/back_image BY DEFAULT, unlike
    ai_router.py's digitise_document (which persists general clinical
    document uploads to the ObjectStore for later retrieval)
    -- these are raw photographs of a physical government ID, materially
    more sensitive than a clinical scan, and this flow has no legitimate
    later use for the original image once OCR has run. Both byte buffers
    are normally only ever held in local variables for the duration of this
    request handler and never written anywhere. The one exception is local
    debugging: see `_debug_save_photo` / `SELF_REGISTER_DEBUG_SAVE_DIR`
    above -- an explicit, unset-by-default opt-in, never to be set in a
    real deployment.

    This endpoint's failure messages MAY be more specific than the
    enumeration-sensitive endpoints elsewhere in this codebase (/start's
    generic-on-purpose mismatch error, the OTP endpoints' fully generic
    errors) -- by this point the caller has already proven they know the
    NRIC + name (at /start, with date of birth checked as a
    self-consistency signal derived from that same NRIC -- see /start's
    docstring) AND has access to the registered email (at /verify-otp); the
    remaining risk here is OCR/photo-quality
    feedback, not account enumeration. Even so, messages never echo back
    the actual stored database values verbatim.
    """
    patient = _resolve_patient_by_nric(db, national_id)
    attempt = (
        db.query(models.SelfRegistrationAttempt)
        .filter(models.SelfRegistrationAttempt.patient_id == patient.id)
        .first()
        if patient else None
    )

    if not attempt or attempt.status != "pending_photo":
        raise HTTPException(status_code=400, detail=_RESTART_REQUIRED_ERROR)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not attempt.photo_verification_deadline or now >= attempt.photo_verification_deadline:
        raise HTTPException(
            status_code=400,
            detail=f"Photo verification window has expired. {_RESTART_REQUIRED_ERROR}",
        )

    front_bytes = await front_image.read()
    back_bytes = await back_image.read()

    if len(front_bytes) > MAX_UPLOAD_BYTES or len(back_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large — max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB per image",
        )

    front_media_type = front_image.content_type or "image/jpeg"
    back_media_type = back_image.content_type or "image/jpeg"

    # No-op unless SELF_REGISTER_DEBUG_SAVE_DIR is set -- see that
    # constant's comment above. Deliberately called here, before OCR runs,
    # so a photo still gets saved for inspection even if extraction itself
    # blows up. Paths captured (None if saving is off/failed) so the OCR
    # result can be written to a same-name sibling .txt file below.
    front_debug_path = _debug_save_photo("front", front_bytes, front_media_type)
    back_debug_path = _debug_save_photo("back", back_bytes, back_media_type)

    # OCR extraction (see ai/nric_ocr.py) -- local-LLM (Ollama vision) mode
    # by default, Tesseract fallback if Ollama is unreachable. Both paths
    # degrade to ic_number=None/name=None on any failure rather than
    # raising -- an extraction failure is ALWAYS treated as a failed
    # verification attempt below (never as an automatic pass; "unverifiable"
    # must never mean "verified").
    # extract_nric_fields is fully synchronous and slow -- a Tesseract
    # subprocess (seconds) or the blocking local-LLM HTTP call. This is
    # a public, unauthenticated endpoint, so running the two extractions
    # inline would freeze the event loop (stalling every other in-flight
    # request) for the whole OCR duration. Run both off-thread and in
    # parallel instead. Code-review follow-up 2026-09-07.
    front_result, back_result = await asyncio.gather(
        run_in_threadpool(extract_nric_fields, front_bytes, front_media_type),
        run_in_threadpool(extract_nric_fields, back_bytes, back_media_type),
    )
    _debug_save_ocr_result(front_debug_path, front_result)
    _debug_save_ocr_result(back_debug_path, back_result)

    matched, client_message, internal_note = _evaluate_photo_verification(front_result, back_result, patient)
    attempt.last_ocr_failure_reason = internal_note

    # Console-visible verification outcome for local dev/debugging -- the
    # uvicorn access log line for this request only ever shows
    # "POST /verify-photos -> 400", never *why*. Deliberately logs the OCR
    # `method` used (llm/tesseract -- confirms which extraction path
    # actually ran) plus the short internal_note code and client_message,
    # NEVER the raw extracted ic_number/name (those are the sensitive
    # values themselves, same non-PII-in-logs discipline as the
    # national_id_fingerprint hashing a few lines down for the flagged
    # branch).
    logger.info(
        "self-register verify-photos: matched=%s method=front:%s/back:%s internal_note=%s client_message=%r",
        matched, front_result.get("method"), back_result.get("method"), internal_note, client_message,
    )

    if matched:
        attempt.status = "photo_verified"
        db.add(attempt)
        db.commit()
        log_access(
            db, patient.id, actor="self_registration", actor_role=None,
            action="self_register_photo_verified", detail=internal_note,
        )
        # 200, flat body -- plain return (not an exception), so this
        # already matches the documented contract shape with no extra
        # handling needed.
        return {
            "status": "verified",
            "detail": "Identity verified. Set your password to finish registration.",
            "next_step": "complete",
        }

    attempt.photo_verify_attempt_count = (attempt.photo_verify_attempt_count or 0) + 1
    remaining = PHOTO_VERIFY_MAX_ATTEMPTS - attempt.photo_verify_attempt_count

    if attempt.photo_verify_attempt_count >= PHOTO_VERIFY_MAX_ATTEMPTS:
        attempt.status = "flagged_manual_review"
        db.add(attempt)
        db.commit()
        # Full plaintext NRIC is deliberately NOT retained in this log row
        # -- a short, non-reversible fingerprint (truncated SHA-256 of the
        # normalized NRIC) is enough to correlate repeated flagged attempts
        # for the same NRIC in the audit log without adding another place
        # in this codebase where the raw NRIC sits in plaintext at rest
        # (patient_id above already unambiguously identifies WHICH patient
        # this event is about; the hash is only useful for a human
        # cross-referencing "was this input NRIC the same one that already
        # resolves to this patient_id" during an investigation).
        national_id_fingerprint = hashlib.sha256(normalize_nric(national_id).encode("utf-8")).hexdigest()[:16]
        log_access(
            db, patient.id, actor="self_registration", actor_role=None,
            action="self_register_flagged_manual_review",
            detail=f"national_id_fingerprint={national_id_fingerprint}",
        )
        # Deliberately built as a raw JSONResponse (bypassing HTTPException's
        # usual `{"detail": <value>}` wrapping) so the body matches the
        # FLAT top-level contract the mobile client is built against
        # exactly: {"detail": ..., "next_step": ...} as sibling keys, not
        # nested under a second "detail" key the way e.g.
        # auth.get_current_user's 403 body is (that shape predates this
        # endpoint and wasn't renegotiated; this endpoint's contract was
        # specified flat from the start, so it's implemented flat).
        return JSONResponse(status_code=403, content={
            "detail": "We couldn't verify your identity automatically after multiple attempts. Please visit a registration counter with your physical NRIC for manual verification.",
            "next_step": "manual_registration_required",
        })

    db.add(attempt)
    db.commit()
    # Same flat-body rationale as the 403 branch above.
    return JSONResponse(status_code=400, content={
        "detail": client_message,
        "next_step": "verify_photos",
        "photo_attempts_remaining": remaining,
    })


@router.post("/complete", response_model=schemas.Token)
@limiter.limit("20/minute")  # per-IP -- lighter than the gates above since
# this step alone is genuinely low-exploitability (only reachable once an
# attempt has already reached photo_verified, which already required
# passing the rate-limited OTP-verify and photo-verify gates), but still a
# defense-in-depth backstop (Security Audit M2's blanket per-IP concern)
# rather than a total exemption.
def complete_self_registration(request: Request, payload: schemas.SelfRegisterCompleteRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated. Final step of self-service registration --
    creates the User row and logs the new patient straight in, same Token
    shape POST /auth/login returns, so the mobile client can proceed
    without a second round-trip."""
    patient = _resolve_patient_by_nric(db, payload.national_id)
    attempt = (
        db.query(models.SelfRegistrationAttempt)
        .filter(models.SelfRegistrationAttempt.patient_id == patient.id)
        .first()
        if patient else None
    )

    if not attempt or attempt.status != "photo_verified":
        raise HTTPException(
            status_code=400,
            detail="Identity verification is required before completing registration. Please restart from the beginning if needed.",
        )

    # Guards against a concurrent staff-issued /issue-account call landing
    # in the window between /verify-photos succeeding and this call -- if
    # an account now exists, don't silently create a second, conflicting
    # one on top of it.
    existing_user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
    if existing_user:
        raise HTTPException(status_code=409, detail=_ACCOUNT_EXISTS_ERROR)

    user = models.User(
        # Patients authenticate via NRIC (see auth_router._resolve_login_user),
        # not this field -- same synthetic-placeholder convention
        # issue_patient_account already uses, kept only to satisfy the
        # NOT NULL/unique schema constraint on User.email.
        email=f"patient-{patient.id}@clarion.local",
        hashed_password=auth.hash_password(payload.new_password),
        full_name=patient.full_name,
        role="patient",
        patient_id=patient.id,
        # They just chose this password themselves (unlike a staff-issued
        # temp password) -- no forced change-on-first-login needed.
        must_change_password=False,
    )
    db.add(user)

    if not patient.email:
        patient.email = attempt.email
        db.add(patient)

    attempt.status = "completed"
    db.add(attempt)
    db.commit()
    db.refresh(user)

    log_access(db, patient.id, actor="self_registration", actor_role="patient", action="self_register_completed")

    token = auth.create_access_token(
        {"sub": user.id, "role": user.role},
        password_changed_at=user.password_changed_at,
    )
    return schemas.Token(access_token=token, user=_with_missing_profile_fields(user))
