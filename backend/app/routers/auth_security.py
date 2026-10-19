"""Second factor + session management for the public-facing login.

Two groups, both under /auth:

* MFA (TOTP) -- the login-time challenge (`/mfa/verify`, `/mfa/enrol/*`,
  authenticated by the short-lived challenge token /auth/login hands out
  instead of an access token) and the signed-in management endpoints
  (`/mfa/status|setup|disable|recovery-codes`, admin `/mfa/reset/{id}`).
* Sessions -- list / revoke the caller's refresh-token chains.

Wrong codes feed the SAME per-account lockout as wrong passwords
(auth.LOGIN_MAX_ATTEMPTS), so a six-digit code can't be ground through.
Accepting a code is a compare-and-set on the database row, so two workers
can't both honour the same TOTP step or recovery code.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import auth, mfa, models, schemas
from ..audit import log_access
from ..database import get_db
from ..email_service import send_mfa_email_code, send_security_notice_email
from ..rate_limit import limiter
from .. import account_lock
import html as _html
from fastapi.responses import HTMLResponse
from .auth_router import _complete_login, _REFRESH_COOKIE_NAME, _verify_ldap_existing_user

router = APIRouter(prefix="/auth", tags=["auth-security"])
logger = logging.getLogger("clarion.mfa")

_SESSION_EXPIRED = "Sign-in expired. Please start again."


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _notify(user: models.User, what: str) -> None:
    """Best-effort heads-up; a failure here must never break the action."""
    if not user.email or user.email.endswith((".test", ".invalid", ".demo")):
        return
    try:
        send_security_notice_email(user.email, user.full_name, what)
    except Exception:  # noqa: BLE001
        logger.exception("security notice email failed")


def _challenge_user(db: Session, token: str, want: Optional[str] = None) -> models.User:
    parsed = mfa.read_challenge(token)
    if parsed is None:
        raise HTTPException(status_code=401, detail=_SESSION_EXPIRED)
    user_id, kind, marker = parsed
    if want and kind != want:
        raise HTTPException(status_code=401, detail=_SESSION_EXPIRED)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    # A password change/reset since the challenge was minted invalidates it.
    if user is None or marker != mfa.password_marker(user):
        raise HTTPException(status_code=401, detail=_SESSION_EXPIRED)
    return user


def _check_not_locked(db: Session, user: models.User) -> None:
    now = _now_naive()
    if user.login_locked_until and now < user.login_locked_until:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again after {user.login_locked_until.isoformat()}Z.",
        )
    if user.login_locked_until and now >= user.login_locked_until:
        # A lapsed lock is a fresh start (same rule as /auth/login) -- else
        # one wrong guess would immediately re-lock the account.
        user.login_failed_count = 0
        user.login_locked_until = None
        db.add(user)
        db.commit()


def _record_failure(db: Session, user: models.User, action: str) -> None:
    user.login_failed_count = (user.login_failed_count or 0) + 1
    if user.login_failed_count >= auth.LOGIN_MAX_ATTEMPTS:
        user.login_locked_until = _now_naive() + timedelta(minutes=auth.LOGIN_LOCKOUT_MINUTES)
    db.add(user)
    db.commit()
    log_access(db, user.patient_id, user.id, user.role, action,
               detail=f"count={user.login_failed_count}", actor_facility=user.facility)


def _clear_failures(db: Session, user: models.User) -> None:
    if user.login_failed_count or user.login_locked_until:
        user.login_failed_count = 0
        user.login_locked_until = None
        db.add(user)
        db.commit()


def _accept_code(db: Session, user: models.User, code: str) -> Optional[str]:
    """"totp" / "recovery" when `code` is good, else None. Single use is
    enforced by an atomic UPDATE ... WHERE (rowcount 1 wins), not by a
    read-then-write, so concurrent workers can't both accept one code."""
    if not mfa.is_enrolled(user):
        return None
    if mfa.looks_like_recovery_code(code):
        row = (
            db.query(models.MfaRecoveryCode)
            .filter_by(user_id=user.id, code_hash=mfa.hash_recovery_code(code), used_at=None)
            .first()
        )
        if row is None:
            return None
        won = (
            db.query(models.MfaRecoveryCode)
            .filter(models.MfaRecoveryCode.id == row.id, models.MfaRecoveryCode.used_at.is_(None))
            .update({"used_at": _now_naive()}, synchronize_session=False)
        )
        db.commit()
        if won != 1:
            return None
        log_access(db, user.patient_id, user.id, user.role, "mfa_recovery_code_used",
                   actor_facility=user.facility)
        _notify(user, "One of your CLARION recovery codes was just used to sign in.")
        return "recovery"
    try:
        secret = mfa.decrypt_secret(user.mfa_secret_enc, user.id)
    except ValueError:
        logger.error("MFA secret for user %s cannot be decrypted (key rotated or row altered)", user.id)
        log_access(db, user.patient_id, user.id, user.role, "mfa_secret_unreadable", actor_facility=user.facility)
        return None
    step = mfa.verify_totp(secret, code, user.mfa_last_step)
    if step is None:
        return None
    won = (
        db.query(models.User)
        .filter(models.User.id == user.id,
                or_(models.User.mfa_last_step.is_(None), models.User.mfa_last_step < step))
        .update({"mfa_last_step": step}, synchronize_session=False)
    )
    db.commit()
    if won != 1:
        return None  # another request consumed this (or a later) step first
    db.refresh(user)
    return "totp"


def _new_recovery_codes(db: Session, user: models.User) -> list:
    db.query(models.MfaRecoveryCode).filter_by(user_id=user.id).delete()
    codes = mfa.new_recovery_codes()
    for c in codes:
        db.add(models.MfaRecoveryCode(user_id=user.id, code_hash=mfa.hash_recovery_code(c)))
    db.commit()
    return codes


def _begin_enrolment(db: Session, user: models.User) -> schemas.MfaEnrolStartOut:
    if mfa.is_enrolled(user):
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    secret = mfa.new_secret()
    user.mfa_secret_enc = mfa.encrypt_secret(secret, user.id)
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    db.commit()
    log_access(db, user.patient_id, user.id, user.role, "mfa_enrol_started", actor_facility=user.facility)
    uri = mfa.otpauth_uri(secret, user.email)
    return schemas.MfaEnrolStartOut(secret=secret, otpauth_uri=uri, qr_png_base64=mfa.qr_png_base64(uri))


def _confirm_enrolment(db: Session, user: models.User, code: str) -> list:
    if not user.mfa_secret_enc or user.mfa_enabled_at:
        raise HTTPException(status_code=409, detail="No MFA enrolment in progress")
    try:
        secret = mfa.decrypt_secret(user.mfa_secret_enc, user.id)
    except ValueError:
        raise HTTPException(status_code=409, detail="Enrolment is invalid; start again")
    step = mfa.verify_totp(secret, code, None)
    if step is None:
        _record_failure(db, user, "mfa_enrol_failed")
        # 400, not 401: on the signed-in path a 401 would be read by the web
        # client as "session expired" (silent refresh / bounce to login).
        raise HTTPException(status_code=400, detail="That code didn't match. Check the time on your phone and try again.")
    user.mfa_enabled_at = datetime.now(timezone.utc)
    user.mfa_last_step = step
    db.commit()
    codes = _new_recovery_codes(db, user)
    log_access(db, user.patient_id, user.id, user.role, "mfa_enabled", actor_facility=user.facility)
    _notify(user, "Two-step verification (authenticator app) was just turned on for your CLARION account.")
    return codes


def _verify_password(db: Session, user: models.User, password: str) -> bool:
    if user.auth_source == "ldap":
        return bool(password) and _verify_ldap_existing_user(db, user, password)
    return auth.verify_password(password, user.hashed_password)


def _reauth_password(db: Session, user: models.User, password: str) -> None:
    _check_not_locked(db, user)
    if not _verify_password(db, user, password):
        _record_failure(db, user, "mfa_reauth_failed")
        raise HTTPException(status_code=400, detail="Password is incorrect")
    _clear_failures(db, user)


def _reauth(db: Session, user: models.User, password: str, code: str) -> None:
    _check_not_locked(db, user)
    if not (_verify_password(db, user, password) and _accept_code(db, user, code)):
        _record_failure(db, user, "mfa_reauth_failed")
        raise HTTPException(status_code=400, detail="Password or code is incorrect")
    _clear_failures(db, user)


def require_stepup(db: Session, actor: models.User, password: str, code: str) -> str:
    """Re-authenticate the acting admin before a credential-reset action: their own
    password + a current authenticator (or recovery) code. An admin who has not
    enrolled an authenticator (MFA not enforced for the role) is asked for the
    password only. Failures count toward the actor's own lockout. Returns the
    factor used ("totp" | "recovery" | "password") for the audit row."""
    if not mfa.is_enrolled(actor):
        _reauth_password(db, actor, password)
        return "password"
    _check_not_locked(db, actor)
    factor = _verify_password(db, actor, password) and _accept_code(db, actor, code or "")
    if not factor:
        _record_failure(db, actor, "mfa_reauth_failed")
        raise HTTPException(status_code=400, detail="Password or code is incorrect")
    _clear_failures(db, actor)
    return factor


# ---- login-time (authenticated by the challenge token) ----------------------

@router.post("/mfa/verify", response_model=schemas.Token)
@limiter.limit("10/minute")
def mfa_verify(request: Request, response: Response, payload: schemas.MfaCodeRequest,
               db: Session = Depends(get_db)):
    user = _challenge_user(db, payload.mfa_token, "verify")
    _check_not_locked(db, user)
    factor = _accept_code(db, user, payload.code)
    if factor is None:
        _record_failure(db, user, "mfa_failed")
        raise HTTPException(status_code=401, detail="Invalid code")
    _clear_failures(db, user)
    log_access(db, user.patient_id, user.id, user.role, "mfa_verified",
               detail=f"factor={factor}", actor_facility=user.facility)
    fp = auth.client_fingerprint(request.headers.get("user-agent"))
    return _complete_login(db, request, response, user, fp, mfa_ok=True)


_LOCK_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}
_LOCK_PAGE = (
    "<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>CLARION account</title><body style='font-family:system-ui,sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem'>"
    "{body}</body></html>"
)


@router.get("/account-lock", response_class=HTMLResponse)
def account_lock_page(token: str = ""):
    """Confirmation page for the email link (a GET never changes state: mail scanners prefetch links)."""
    if account_lock.read_lock_token(token) is None:
        return HTMLResponse(_LOCK_PAGE.format(body="<h1>Link expired</h1><p>This link is no longer valid. "
                                                   "If you think someone else used your record, choose "
                                                   "Forgot password in the app to secure it.</p>"),
                            status_code=400, headers=_LOCK_HEADERS)
    body = ("<h1>Lock this account?</h1><p>This signs the account out everywhere and stops it from being used "
            "until you reset the password with a code sent to your email.</p>"
            "<form method=post><input type=hidden name=token value='" + _html.escape(token, quote=True) + "'>"
            "<button type=submit style='font-size:1.1rem;padding:.8rem 1.2rem'>Yes, lock the account</button></form>")
    return HTMLResponse(_LOCK_PAGE.format(body=body), headers=_LOCK_HEADERS)


@router.post("/account-lock", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def account_lock_confirm(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    parsed = account_lock.read_lock_token(str(form.get("token", "")))
    user = db.query(models.User).filter(models.User.id == parsed[0]).first() if parsed else None
    if user is None or parsed[1] != mfa.password_marker(user):
        # unknown, expired, or already used (a lock or a password reset changes the marker)
        return HTMLResponse(_LOCK_PAGE.format(body="<h1>Link expired</h1><p>This link is no longer valid.</p>"),
                            status_code=400, headers=_LOCK_HEADERS)
    now = _now_naive()
    if user.owner_locked_at is None:
        user.owner_locked_at = now
        user.password_changed_at = now  # kills every access token already issued
        db.add(user)
        db.commit()
        auth.revoke_all_refresh_tokens_for_user(db, user)
        log_access(db, user.patient_id, user.id, user.role, "account_locked_by_owner", actor_facility=user.facility)
    return HTMLResponse(_LOCK_PAGE.format(
        body="<h1>Account locked</h1><p>It is signed out everywhere. To use it again, open the CLARION app "
             "and choose <strong>Forgot password</strong>.</p>"), headers=_LOCK_HEADERS)


# Email second factor. Reuses the user's otp_* columns (the password-reset OTP lives there too);
# the stored hash is domain-separated so a reset code can never satisfy this and vice versa.
_EMAIL_PURPOSE = "mfa-email:"


@router.post("/mfa/email/send")
@limiter.limit("5/minute")
def mfa_email_send(request: Request, payload: schemas.MfaTokenRequest, db: Session = Depends(get_db)):
    user = _challenge_user(db, payload.mfa_token)
    target = mfa.email_target(db, user)
    if target is None:
        raise HTTPException(status_code=400, detail="Email codes are not available for this account.")
    now = _now_naive()
    window = timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES)
    if not user.otp_request_window_start or now - user.otp_request_window_start > window:
        user.otp_request_window_start, user.otp_request_count = now, 0
    if (user.otp_request_count or 0) >= auth.OTP_MAX_REQUESTS_PER_WINDOW:
        db.add(user)
        db.commit()
        raise HTTPException(status_code=429, detail="Too many code requests. Try again in a few minutes.")
    code = auth.generate_otp_code()
    user.otp_request_count = (user.otp_request_count or 0) + 1
    user.otp_code_hash = auth.hash_otp_code(_EMAIL_PURPOSE + code)
    user.otp_expires_at = now + timedelta(minutes=auth.OTP_EXPIRY_MINUTES)
    user.otp_attempt_count = 0
    db.add(user)
    db.commit()
    if not send_mfa_email_code(target, user.full_name or "there", code):
        raise HTTPException(status_code=503, detail="We could not send the email. Try again shortly.")
    log_access(db, user.patient_id, user.id, user.role, "mfa_email_code_sent", actor_facility=user.facility)
    return {"status": "ok", "email_hint": mfa.mask_email(target)}


@router.post("/mfa/email/verify", response_model=schemas.Token)
@limiter.limit("10/minute")
def mfa_email_verify(request: Request, response: Response, payload: schemas.MfaCodeRequest,
                     db: Session = Depends(get_db)):
    user = _challenge_user(db, payload.mfa_token)
    if mfa.email_target(db, user) is None:
        raise HTTPException(status_code=400, detail="Email codes are not available for this account.")
    _check_not_locked(db, user)
    code = payload.code.strip().replace(" ", "")
    live = bool(user.otp_code_hash and user.otp_expires_at and _now_naive() <= user.otp_expires_at)
    good = live and auth.verify_otp_code(_EMAIL_PURPOSE + code, user.otp_code_hash)
    # Single use: this compare-and-set is the only way a code is honoured.
    won = good and db.query(models.User).filter(
        models.User.id == user.id, models.User.otp_code_hash == user.otp_code_hash,
    ).update({"otp_code_hash": None, "otp_expires_at": None, "otp_attempt_count": 0},
             synchronize_session=False) == 1
    db.commit()
    if not won:
        if live:
            user.otp_attempt_count = (user.otp_attempt_count or 0) + 1
            if user.otp_attempt_count >= auth.OTP_MAX_VERIFY_ATTEMPTS:
                user.otp_code_hash, user.otp_expires_at, user.otp_attempt_count = None, None, 0
            db.add(user)
            db.commit()
        _record_failure(db, user, "mfa_email_failed")
        raise HTTPException(status_code=401, detail="Invalid code")
    db.refresh(user)
    _clear_failures(db, user)
    log_access(db, user.patient_id, user.id, user.role, "mfa_verified", detail="factor=email",
               actor_facility=user.facility)
    fp = auth.client_fingerprint(request.headers.get("user-agent"))
    return _complete_login(db, request, response, user, fp, mfa_ok=True)


@router.post("/mfa/enrol/start", response_model=schemas.MfaEnrolStartOut)
@limiter.limit("10/minute")
def mfa_enrol_start(request: Request, payload: schemas.MfaTokenRequest, db: Session = Depends(get_db)):
    user = _challenge_user(db, payload.mfa_token, "enrol")
    return _begin_enrolment(db, user)


@router.post("/mfa/enrol/confirm", response_model=schemas.MfaTokenWithRecovery)
@limiter.limit("10/minute")
def mfa_enrol_confirm(request: Request, response: Response, payload: schemas.MfaCodeRequest,
                      db: Session = Depends(get_db)):
    user = _challenge_user(db, payload.mfa_token, "enrol")
    _check_not_locked(db, user)
    codes = _confirm_enrolment(db, user, payload.code)
    fp = auth.client_fingerprint(request.headers.get("user-agent"))
    token = _complete_login(db, request, response, user, fp, mfa_ok=True)
    return schemas.MfaTokenWithRecovery(**token.model_dump(), recovery_codes=codes)


# ---- signed-in management ----------------------------------------------------

@router.get("/mfa/status")
def mfa_status(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    remaining = db.query(models.MfaRecoveryCode).filter_by(user_id=current_user.id, used_at=None).count()
    return {
        "enabled": mfa.is_enrolled(current_user),
        "required": mfa.role_requires_mfa(current_user.role),
        "recovery_codes_remaining": remaining,
    }


@router.post("/mfa/setup/start", response_model=schemas.MfaEnrolStartOut)
@limiter.limit("10/minute")
def mfa_setup_start(request: Request, payload: schemas.PasswordOnly, db: Session = Depends(get_db),
                    current_user: models.User = Depends(auth.get_current_user)):
    # Re-authenticate: a stolen/unattended access token alone must not be
    # enough to bind someone else's authenticator to this account.
    _reauth_password(db, current_user, payload.password)
    return _begin_enrolment(db, current_user)


@router.post("/mfa/setup/confirm")
@limiter.limit("10/minute")
def mfa_setup_confirm(request: Request, payload: schemas.MfaCodeRequest = Body(...),
                      db: Session = Depends(get_db),
                      current_user: models.User = Depends(auth.get_current_user)):
    # `mfa_token` is part of the shared request model; unused when signed in.
    _check_not_locked(db, current_user)
    codes = _confirm_enrolment(db, current_user, payload.code)
    # Every OTHER session predates the second factor: end them.
    here = _current_hash(request, None)
    for s in _live_sessions(db, current_user):
        if s.token_hash != here:
            _revoke_chain(db, s)
    db.commit()
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
@limiter.limit("10/minute")
def mfa_disable(request: Request, payload: schemas.PasswordAndCode, db: Session = Depends(get_db),
                current_user: models.User = Depends(auth.get_current_user)):
    if mfa.role_requires_mfa(current_user.role):
        raise HTTPException(status_code=403, detail="MFA is required for your role and can't be turned off")
    if not mfa.is_enrolled(current_user):
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    _reauth(db, current_user, payload.password, payload.code)
    current_user.mfa_secret_enc = None
    current_user.mfa_enabled_at = None
    current_user.mfa_last_step = None
    db.query(models.MfaRecoveryCode).filter_by(user_id=current_user.id).delete()
    db.commit()
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "mfa_disabled",
               actor_facility=current_user.facility)
    _notify(current_user, "Two-step verification was just turned off for your CLARION account.")
    return {"enabled": False}


@router.post("/mfa/recovery-codes")
@limiter.limit("10/minute")
def mfa_regenerate_recovery_codes(request: Request, payload: schemas.PasswordAndCode,
                                  db: Session = Depends(get_db),
                                  current_user: models.User = Depends(auth.get_current_user)):
    if not mfa.is_enrolled(current_user):
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    _reauth(db, current_user, payload.password, payload.code)
    codes = _new_recovery_codes(db, current_user)
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "mfa_recovery_regenerated",
               actor_facility=current_user.facility)
    return {"recovery_codes": codes}


@router.post("/mfa/reset/{user_id}")
@limiter.limit("10/minute")
def admin_reset_mfa(request: Request, user_id: str, payload: schemas.AdminStepUp,
                    db: Session = Depends(get_db),
                    current_user: models.User = Depends(auth.require_roles("admin"))):
    """Lost phone AND recovery codes: an admin clears the user's MFA (they are
    prompted to enrol again at next sign-in if their role requires it) and
    every session of theirs is revoked. The user is emailed.

    Needs the acting admin's own password + authenticator code (step-up), and
    never targets the admin's own account -- a sole admin recovers through the
    host script (db/reset_admin_password.py --mfa-only)."""
    from .admin import _require_facility

    facility = _require_facility(current_user)  # 400 for an admin with no facility; never skipped
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if target is None or target.facility != facility:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't reset your own authenticator here. Ask another administrator.")
    if target.role == "admin" and target.must_change_password:
        # A temporary password is outstanding (or the account never signed in). Clearing the
        # authenticator now would let whoever holds that password enrol their own at sign-in.
        raise HTTPException(
            status_code=409,
            detail="This administrator has a pending password change. They must sign in and set a "
                   "password first, or an operator must reset them from the server.",
        )
    factor = require_stepup(db, current_user, payload.password, payload.code)
    target.mfa_secret_enc = None
    target.mfa_enabled_at = None
    target.mfa_last_step = None
    db.query(models.MfaRecoveryCode).filter_by(user_id=target.id).delete()
    target.password_changed_at = _now_naive()  # evict live access tokens too, not just refresh tokens
    db.commit()
    auth.revoke_all_refresh_tokens_for_user(db, target)
    log_access(db, target.patient_id, current_user.id, current_user.role, "mfa_reset_by_admin",
               detail=f"target={target.id} role={target.role} factor={factor}",
               actor_facility=current_user.facility)
    _notify(target, "An administrator reset two-step verification on your CLARION account.")
    return {"status": "mfa_reset"}


# ---- sessions ----------------------------------------------------------------

def _live_sessions(db: Session, user: models.User):
    return (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.user_id == user.id,
                models.RefreshToken.revoked_at.is_(None),
                models.RefreshToken.expires_at > _now_naive())
        .order_by(models.RefreshToken.issued_at.desc())
        .all()
    )


def _revoke_chain(db: Session, row: models.RefreshToken) -> None:
    """Revoke `row` and everything it was rotated into -- a session's id
    changes on every refresh, so an id the UI showed a minute ago may now be
    an already-revoked ancestor of the live token."""
    seen = set()
    while row is not None and row.id not in seen:
        seen.add(row.id)
        if row.revoked_at is None:
            row.revoked_at = _now_naive()
        row = (
            db.query(models.RefreshToken).filter_by(id=row.replaced_by_id).first()
            if row.replaced_by_id else None
        )


def _current_hash(request: Request, body: Optional[schemas.RefreshTokenRequest]) -> Optional[str]:
    """The caller's own refresh token: cookie (web) or X-Refresh-Token header
    / body (native client, which has no cookie jar)."""
    raw = (request.cookies.get(_REFRESH_COOKIE_NAME)
           or request.headers.get("x-refresh-token")
           or (body.refresh_token if body else None))
    return auth._hash_refresh_token(raw) if raw else None


@router.get("/sessions", response_model=list[schemas.SessionOut])
def list_sessions(request: Request, db: Session = Depends(get_db),
                  current_user: models.User = Depends(auth.get_current_user)):
    here = _current_hash(request, None)
    return [
        schemas.SessionOut(id=s.id, ip=s.ip, user_agent=s.user_agent,
                           issued_at=s.issued_at.isoformat() if s.issued_at else None,
                           current=(here is not None and s.token_hash == here))
        for s in _live_sessions(db, current_user)
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, db: Session = Depends(get_db),
                   current_user: models.User = Depends(auth.get_current_user)):
    row = db.query(models.RefreshToken).filter_by(id=session_id, user_id=current_user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _revoke_chain(db, row)
    db.commit()
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "session_revoked",
               actor_facility=current_user.facility)
    return {"status": "revoked"}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, body: Optional[schemas.RefreshTokenRequest] = Body(None),
                          db: Session = Depends(get_db),
                          current_user: models.User = Depends(auth.get_current_user)):
    here = _current_hash(request, body)
    if here is None:
        # Without knowing which session is "this one" we'd revoke the caller's
        # own too -- refuse rather than guess.
        raise HTTPException(status_code=400, detail="Cannot tell which session is current")
    n = 0
    for s in _live_sessions(db, current_user):
        if s.token_hash != here:
            _revoke_chain(db, s)
            n += 1
    db.commit()
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "sessions_revoked_others",
               detail=f"count={n}", actor_facility=current_user.facility)
    return {"revoked": n}
