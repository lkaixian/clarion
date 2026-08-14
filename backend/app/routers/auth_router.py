from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..email_service import send_password_reset_otp_email
from ..nric import normalize_nric
from ..rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic response for EVERY outcome of POST /auth/request-password-reset-otp
# except the rate-limit lockout (see its own docstring) -- unknown NRIC, a
# real NRIC with no linked login, or a real NRIC/login with no email on
# file, and an NRIC that really did just get a fresh code emailed to it,
# all look identical from the outside. Same enumeration-safety discipline
# this codebase already applied to the old DOB-based forgot-password flow.
_REQUEST_OTP_GENERIC_RESPONSE = {
    "status": "ok",
    "detail": "If this NRIC has a registered account with an email on file, a verification code has been sent.",
}

# Generic message for every failure mode of POST /auth/reset-password-with-otp
# (unknown NRIC, no pending OTP, expired OTP, wrong code) -- deliberately
# identical so the response can't be used to distinguish any of those cases.
_RESET_WITH_OTP_GENERIC_ERROR = "Invalid or expired verification code."


@router.post("/register", response_model=schemas.UserOut)
def register(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    # Staff-only account creation. This endpoint previously had NO auth
    # check at all — any unauthenticated caller could POST here with
    # role="admin" and mint themselves a full admin account. Nothing in
    # this codebase calls it (grep confirms), so it was dead, open attack
    # surface rather than a used integration. Superseded by the
    # staff-issued temp-password registration flow (see /auth/issue-account
    # once that lands) for patient accounts specifically; kept here,
    # admin-gated, for staff/clinician account creation.
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        facility=payload.facility,
        patient_id=payload.patient_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _resolve_patient_by_nric(db: Session, national_id: str) -> models.Patient | None:
    """Dash-tolerant NRIC -> Patient lookup, used everywhere an NRIC is
    accepted as input (login, both OTP-reset endpoints). Normalizes BOTH
    the caller's input and each stored Patient.national_id (which may
    still have dashes, e.g. "520314-01-1234") before comparing, so
    "520314-01-1234" and "520314011234" resolve to the same record without
    needing a data migration to reformat existing rows. The patient table
    is tiny at this project's scale, so a fetch-and-compare-in-Python loop
    is simpler and just as fast in practice as a func.replace(...) SQL
    expression; revisit if the table ever grows large."""
    normalized_input = normalize_nric(national_id)
    if not normalized_input:
        return None

    for patient in db.query(models.Patient).filter(models.Patient.national_id.isnot(None)).all():
        if normalize_nric(patient.national_id) == normalized_input:
            return patient
    return None


def _resolve_login_user(db: Session, identifier: str) -> models.User | None:
    """Resolve the OAuth2 `username` field to a User, accepting either an
    email or a patient's NRIC (Patient.national_id, dash-tolerant -- see
    _resolve_patient_by_nric). Tries email first (the common case), then
    falls back to an NRIC -> Patient -> User lookup. Returns None if
    neither resolves, so callers can fall through to the existing generic
    "incorrect credentials" response.
    """
    user = db.query(models.User).filter(models.User.email == identifier).first()
    if user:
        return user

    patient = _resolve_patient_by_nric(db, identifier)
    if patient:
        user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
        if user:
            return user

    return None


def _missing_profile_fields(user: models.User) -> list:
    """Informational-only data-completeness signal for schemas.UserOut
    (see models.PATIENT_PROFILE_FIELDS_TO_PROMPT). Always [] for non-patient
    roles -- this is never a security gate, just a soft client-side prompt."""
    if user.role != "patient" or not user.patient:
        return []
    return [
        field for field in models.PATIENT_PROFILE_FIELDS_TO_PROMPT
        if not getattr(user.patient, field, None)
    ]


def _with_missing_profile_fields(user: models.User) -> models.User:
    """Stashes the computed list as a plain (unmapped, non-persisted)
    instance attribute so schemas.UserOut's from_attributes conversion
    picks it up -- same technique this ORM already relies on for nested
    relationship attributes, just for a computed value instead of a
    mapped column."""
    user.missing_profile_fields = _missing_profile_fields(user)
    return user


@router.post("/login", response_model=schemas.Token)
@limiter.exempt  # exempt from the global per-IP default -- see auth.LOGIN_MAX_ATTEMPTS
# / login_locked_until docstring below: this endpoint already has its own
# stricter, persisted-in-DB, per-ACCOUNT lockout, which shouldn't be
# double-limited (or accidentally superseded) by a coarser global per-IP
# rate limit.
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Account-enumeration tradeoff mirrors POST /auth/forgot-password (see
    its docstring above): every failure -- unknown email/NRIC or a wrong
    password for a real account -- returns the identical generic 401, so
    this endpoint can't be used to probe which identifiers have accounts.
    The one exception is the lockout response, a distinct 429; that's the
    same accepted tradeoff as the forgot-password lockout message -- it
    confirms an account exists but nothing more sensitive than that, and it
    only ever fires for identifiers that already resolve to a real account
    (an unknown identifier just keeps getting the generic 401 forever).

    Locked out *by account*, not by source IP alone: IP-based limiting is
    weak once this sits behind a shared NAT / Cloudflare tunnel where many
    legitimate users can appear to share one IP, and it's trivially
    bypassed by an attacker who rotates IPs. This matters most for
    staff-issued temp passwords -- handed out in person, but guessable by a
    network attacker in the window before the patient's first login and
    forced password change. Persisted on the User row (not in-memory), same
    as reset_attempt_count/reset_locked_until, so it survives process
    restarts and behaves correctly if the backend ever runs multiple
    workers.
    """
    user = _resolve_login_user(db, form_data.username)

    if user:
        now = datetime.utcnow()
        if user.login_locked_until and now < user.login_locked_until:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again after {user.login_locked_until.isoformat()}Z.",
            )

        if auth.verify_password(form_data.password, user.hashed_password):
            if user.login_failed_count or user.login_locked_until:
                user.login_failed_count = 0
                user.login_locked_until = None
                db.add(user)
                db.commit()
            token = auth.create_access_token(
                {"sub": user.id, "role": user.role},
                password_changed_at=user.password_changed_at,
            )
            return schemas.Token(access_token=token, user=_with_missing_profile_fields(user))

        user.login_failed_count = (user.login_failed_count or 0) + 1
        if user.login_failed_count >= auth.LOGIN_MAX_ATTEMPTS:
            user.login_locked_until = now + timedelta(minutes=auth.LOGIN_LOCKOUT_MINUTES)
        db.add(user)
        db.commit()

    raise HTTPException(status_code=401, detail="Incorrect email/NRIC or password")


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(auth.get_current_user_allow_pending_change)):
    # Deliberately exempt from the must_change_password block below (see
    # auth.get_current_user_allow_pending_change) -- clients need this to
    # discover the flag is set in the first place.
    return _with_missing_profile_fields(current_user)


def _apply_new_password(db: Session, user: models.User, new_password: str, must_change: bool) -> None:
    """Single place that actually writes a new password + resets lockout
    bookkeeping. Shared by staff-issued/regenerated accounts and
    self-service forgot-password, per the "same primitive" design — avoids
    the two flows drifting out of sync."""
    user.hashed_password = auth.hash_password(new_password)
    user.must_change_password = must_change
    user.reset_attempt_count = 0
    user.reset_locked_until = None
    # A brand-new password makes any prior login lockout moot (whatever was
    # being brute-forced no longer works), so clear that bookkeeping too.
    user.login_failed_count = 0
    user.login_locked_until = None
    # JWT revocation watermark -- any token issued before this moment now
    # fails auth._resolve_current_user's pwd_changed_at check (see that
    # function's docstring / models.User.password_changed_at's comment).
    user.password_changed_at = datetime.utcnow()
    db.add(user)
    db.commit()


@router.post("/patients/{patient_id}/issue-account", response_model=schemas.IssueAccountResponse)
def issue_patient_account(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """Staff-only. Creates a patient login if none exists yet, or
    regenerates the password of an existing one (this doubles as the
    staff-mediated password-reset path — same code, same primitive as a
    brand-new issuance). Returns the plaintext temp password exactly once;
    it is never stored or logged in plaintext again."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    temp_password = auth.generate_temp_password()
    user = db.query(models.User).filter(models.User.patient_id == patient_id).first()

    if user:
        _apply_new_password(db, user, temp_password, must_change=True)
        action = "reissue_patient_account_password"
    else:
        user = models.User(
            # Patients authenticate with their NRIC via _resolve_login_user,
            # not email — email is only NOT NULL/unique because of the
            # schema, so a synthetic placeholder keeps that constraint
            # satisfied without a nullable-column migration.
            email=f"patient-{patient.id}@medibridge.local",
            hashed_password=auth.hash_password(temp_password),
            full_name=patient.full_name,
            role="patient",
            patient_id=patient.id,
            must_change_password=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        action = "issue_patient_account"

    # Audit the event itself, never the plaintext password.
    log_access(
        db, patient.id, current_user.id, current_user.role, action,
        detail=f"login email={user.email}", actor_facility=current_user.facility,
    )

    return schemas.IssueAccountResponse(
        temporary_password=temp_password,
        national_id=patient.national_id,
        email=user.email,
    )


@router.post("/request-password-reset-otp")
@limiter.exempt  # already has its own bespoke, persisted-in-DB rate limiting
# (OTP_MAX_REQUESTS_PER_WINDOW / OTP_REQUEST_WINDOW_MINUTES, per-account) --
# see the global-default rationale on POST /auth/login above.
def request_password_reset_otp(payload: schemas.PasswordResetOtpRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated. Step 1 of the two-step email-OTP reset
    (replaces the old NRIC+DOB single-step /auth/forgot-password — DOB is
    guessable/knowable PII, same weakness as the NRIC it was meant to
    supplement, so the product decision was to drop it entirely and prove
    identity via a code sent to the patient's own registered email
    instead).

    Account-enumeration tradeoff (deliberate, carried over from the old
    forgot-password design): unknown NRIC, an NRIC with no linked login
    yet, and an NRIC/login with no registered email on file all return the
    exact identical generic success-shaped response as an NRIC that really
    did just get a code emailed to it — a caller cannot distinguish any of
    these four cases from the response alone. Whether Mailgun is even
    configured is folded into the same non-signal (see email_service.py) —
    a misconfigured deployment must not become externally detectable
    either.

    The one exception is the request-rate-limit response, a distinct 429 —
    same accepted tradeoff this codebase already made for login lockout
    and the old forgot-password lockout: "this NRIC is temporarily rate
    limited" only confirms a login exists, not medical data or whether an
    email is on file, and only ever fires for identifiers that already
    resolve to a real account (an unknown NRIC just keeps getting the
    generic response forever).
    """
    patient = _resolve_patient_by_nric(db, payload.national_id)
    user = db.query(models.User).filter(models.User.patient_id == patient.id).first() if patient else None

    if not user:
        return _REQUEST_OTP_GENERIC_RESPONSE

    now = datetime.utcnow()

    # OTP *request* rate limiting -- separate rolling-window counter from
    # the per-OTP verify-attempt counter below. Applies uniformly to every
    # resolvable NRIC/account regardless of whether it has an email on
    # file, so hitting the limit is never itself a signal about email
    # presence (only about "this NRIC resolves to an account", the same
    # thing the login/forgot-password lockouts already reveal).
    window_start = user.otp_request_window_start
    if not window_start or now - window_start > timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES):
        user.otp_request_window_start = now
        user.otp_request_count = 0

    if user.otp_request_count >= auth.OTP_MAX_REQUESTS_PER_WINDOW:
        db.add(user)
        db.commit()
        retry_after = user.otp_request_window_start + timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES)
        raise HTTPException(
            status_code=429,
            detail=f"Too many verification code requests. Try again after {retry_after.isoformat()}Z.",
        )

    user.otp_request_count = (user.otp_request_count or 0) + 1

    if not patient.email:
        db.add(user)
        db.commit()
        log_access(
            db, patient.id, "system", None, "password_reset_otp_requested",
            detail="no email on file",
        )
        return _REQUEST_OTP_GENERIC_RESPONSE

    otp_code = auth.generate_otp_code()
    user.otp_code_hash = auth.hash_otp_code(otp_code)
    user.otp_expires_at = now + timedelta(minutes=auth.OTP_EXPIRY_MINUTES)
    user.otp_attempt_count = 0
    db.add(user)
    db.commit()

    # send_password_reset_otp_email degrades gracefully (logs, returns
    # False) if Mailgun isn't configured or the call fails -- deliberately
    # NOT branching the response on its return value (see docstring above).
    send_password_reset_otp_email(patient.email, otp_code, patient.full_name)

    log_access(db, patient.id, "system", None, "password_reset_otp_requested")
    return _REQUEST_OTP_GENERIC_RESPONSE


@router.post("/reset-password-with-otp")
@limiter.exempt  # already has its own bespoke, persisted-in-DB rate limiting
# (OTP_MAX_VERIFY_ATTEMPTS, per-account) -- see the global-default rationale
# on POST /auth/login above.
def reset_password_with_otp(payload: schemas.PasswordResetWithOtpRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated. Step 2 of the two-step email-OTP reset.

    Enumeration tradeoff mirrors request-password-reset-otp above: unknown
    NRIC, no pending OTP, an expired OTP, and a simply-wrong code all
    return the exact same generic 400 -- a caller can't tell "no such
    account" from "right account, wrong code" from the response alone.
    """
    patient = _resolve_patient_by_nric(db, payload.national_id)
    user = db.query(models.User).filter(models.User.patient_id == patient.id).first() if patient else None

    if not user or not user.otp_code_hash or not user.otp_expires_at:
        raise HTTPException(status_code=400, detail=_RESET_WITH_OTP_GENERIC_ERROR)

    now = datetime.utcnow()
    if now > user.otp_expires_at:
        # Expired -- clear it out rather than leaving a stale hash a client
        # could keep guessing against indefinitely; caller must request a
        # fresh code.
        user.otp_code_hash = None
        user.otp_expires_at = None
        user.otp_attempt_count = 0
        db.add(user)
        db.commit()
        raise HTTPException(status_code=400, detail=_RESET_WITH_OTP_GENERIC_ERROR)

    if not auth.verify_otp_code(payload.otp_code, user.otp_code_hash):
        user.otp_attempt_count = (user.otp_attempt_count or 0) + 1
        if user.otp_attempt_count >= auth.OTP_MAX_VERIFY_ATTEMPTS:
            # 5 wrong tries -> invalidate the OTP entirely rather than just
            # keep counting forever; forces a fresh request-password-reset-otp
            # call, same "cheap for a legitimate user, expensive for an
            # attacker" tradeoff as the login/reset lockouts elsewhere.
            user.otp_code_hash = None
            user.otp_expires_at = None
            user.otp_attempt_count = 0
        db.add(user)
        db.commit()
        raise HTTPException(status_code=400, detail=_RESET_WITH_OTP_GENERIC_ERROR)

    _apply_new_password(db, user, payload.new_password, must_change=False)
    # _apply_new_password already clears reset_attempt_count/reset_locked_until
    # and login_failed_count/login_locked_until (see its docstring). Also
    # invalidate the now-used OTP and its request-rate-limit window.
    user.otp_code_hash = None
    user.otp_expires_at = None
    user.otp_attempt_count = 0
    user.otp_request_count = 0
    user.otp_request_window_start = None
    db.add(user)
    db.commit()

    log_access(db, patient.id, user.id, user.role, "password_reset_via_otp")
    return {"status": "ok", "detail": "Password reset successfully."}


@router.post("/change-password")
def change_password(
    payload: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user_allow_pending_change),
):
    """Authenticated flow for both a forced first-login change
    (must_change_password=True) and a voluntary password change.
    Deliberately exempt from the must_change_password block enforced by
    auth.get_current_user (via get_current_user_allow_pending_change
    instead) -- otherwise a user in that state could never call this
    endpoint to clear the flag."""
    if not auth.verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    _apply_new_password(db, current_user, payload.new_password, must_change=False)
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "change_password",
               actor_facility=current_user.facility)
    return {"status": "ok", "detail": "Password changed successfully."}
