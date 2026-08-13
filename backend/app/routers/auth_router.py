from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic message for every self-service reset failure mode (unknown NRIC,
# DOB mismatch, no linked login yet). Deliberately identical in all three
# cases so the response can't be used to enumerate which NRICs exist in the
# system or which patients have a login yet.
_RESET_GENERIC_ERROR = "Unable to reset password with the details provided."


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


def _resolve_login_user(db: Session, identifier: str) -> models.User | None:
    """Resolve the OAuth2 `username` field to a User, accepting either an
    email or a patient's NRIC (Patient.national_id). Tries email first
    (the common case), then falls back to an NRIC -> Patient -> User lookup.
    Returns None if neither resolves, so callers can fall through to the
    existing generic "incorrect credentials" response.
    """
    user = db.query(models.User).filter(models.User.email == identifier).first()
    if user:
        return user

    patient = db.query(models.Patient).filter(models.Patient.national_id == identifier).first()
    if patient:
        user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
        if user:
            return user

    return None


@router.post("/login", response_model=schemas.Token)
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
            token = auth.create_access_token({"sub": user.id, "role": user.role})
            return schemas.Token(access_token=token, user=user)

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
    return current_user


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
        detail=f"login email={user.email}",
    )

    return schemas.IssueAccountResponse(
        temporary_password=temp_password,
        national_id=patient.national_id,
        email=user.email,
    )


@router.post("/forgot-password")
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated self-service reset via NRIC + date of birth.

    Account-enumeration tradeoff (deliberate): every failure — unknown
    NRIC, correct NRIC but wrong DOB, or an NRIC with no linked login yet —
    returns the exact same generic 400 message, so this endpoint can't be
    used to probe which NRICs are registered in the system. The one
    exception is the lockout response, which is a distinct message; we
    judged that acceptable because "this NRIC is temporarily locked" only
    confirms a *login exists*, not medical data, and a determined attacker
    already gets that same signal for free after enough attempts anyway
    (the generic error keeps coming back forever for a truly unknown NRIC,
    only ever locking out NRICs that *do* have an account).
    """
    patient = db.query(models.Patient).filter(models.Patient.national_id == payload.national_id).first()
    if not patient:
        raise HTTPException(status_code=400, detail=_RESET_GENERIC_ERROR)

    user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
    if not user:
        raise HTTPException(status_code=400, detail=_RESET_GENERIC_ERROR)

    now = datetime.utcnow()
    if user.reset_locked_until and now < user.reset_locked_until:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again after {user.reset_locked_until.isoformat()}Z.",
        )

    if patient.date_of_birth != payload.date_of_birth:
        user.reset_attempt_count = (user.reset_attempt_count or 0) + 1
        if user.reset_attempt_count >= auth.RESET_MAX_ATTEMPTS:
            user.reset_locked_until = now + timedelta(minutes=auth.RESET_LOCKOUT_MINUTES)
        db.add(user)
        db.commit()
        raise HTTPException(status_code=400, detail=_RESET_GENERIC_ERROR)

    _apply_new_password(db, user, payload.new_password, must_change=False)
    log_access(db, patient.id, user.id, user.role, "self_service_password_reset")
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
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "change_password")
    return {"status": "ok", "detail": "Password changed successfully."}
