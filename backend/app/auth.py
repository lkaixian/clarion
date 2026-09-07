import hashlib
import hmac
import logging
import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models, permissions
from .database import get_db

# Defensive/idempotent: app/main.py already calls load_dotenv() as early as
# possible (before importing this module, in every real entry point --
# `uvicorn app.main:app`), so this is normally a no-op. It's here purely as
# a safety net for any hypothetical alternate entry point that imports
# auth.py before main.py has run (e.g. a standalone script/REPL/test that
# imports `app.auth` directly without going through `app.main` first) --
# load_dotenv() is safe to call more than once.
load_dotenv()

# SECRET_KEY / OTP_HMAC_KEY are read from the environment (see
# backend/.env.example) -- there is deliberately NO hardcoded fallback
# here. A guessable, shared, checked-into-git-history default secret
# defeats the entire point of JWT signing / OTP hashing (anyone with the
# source can forge tokens / OTP hashes). Fail loudly and immediately at
# import time instead of silently running with a known-bad secret.
try:
    SECRET_KEY = os.environ["SECRET_KEY"]
except KeyError as exc:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. Copy backend/.env.example "
        "to backend/.env and set SECRET_KEY to a real, high-entropy value "
        "(generate one with: python -c \"import secrets; print(secrets.token_hex(32))\")."
    ) from exc
ALGORITHM = "HS256"
# P2.5 (Security Audit M4): down from 60*8 (8 hours). A short-lived access
# token bounds the damage window of a stolen JWT (XSS, a leaked log line, a
# shared/public machine) to minutes, not most of a workday. Staying logged
# in beyond this is now POST /auth/refresh's job (a separate, longer-lived
# refresh token -- see REFRESH_TOKEN_EXPIRE_DAYS, issue/rotate/revoke_
# refresh_token below), not a long-lived access token.
ACCESS_TOKEN_EXPIRE_MINUTES = 15
# How long a refresh token stays valid without being used at all (a client
# that never calls POST /auth/refresh -- e.g. abandoned overnight -- can't
# silently resurrect a session past this). Each successful refresh ROTATES
# the token (revokes this one, issues a new one with a fresh clock), so an
# actively-used session's effective lifetime is unbounded until logout /
# password change / a detected-reuse compromise signal, not capped at this
# value -- see models.RefreshToken's docstring.
REFRESH_TOKEN_EXPIRE_DAYS = 30
# Grace window for a concurrent-tab refresh race (code-review follow-up
# 2026-09-07). Two browser tabs share one refresh cookie; when both fire an
# API call around the 15-min access-token expiry, both hit 401 and both POST
# /auth/refresh. The second presents the token the first just rotated away.
# Without a grace window that looks identical to token theft and nukes every
# session on every device -- users see random "logged out everywhere". If
# the already-revoked token was ROTATED (not logged-out/compromised), its
# replacement is still the live head of the chain, and it was revoked within
# this many seconds, treat it as the race it almost certainly is: fail the
# request (401, the client retries with the now-updated cookie) WITHOUT
# revoking the chain. Genuine reuse outside this window still trips the
# full-revoke compromise response. Kept SHORT deliberately -- a real
# cross-tab race resolves in milliseconds; the window only needs to cover
# clock skew + the refresh round-trip. Parsed fail-soft (bad value ->
# default, like LOG_LEVEL in main.py) and clamped to [0, 120].
def _grace_seconds_from_env() -> int:
    try:
        return max(0, min(120, int(os.environ.get("REFRESH_REUSE_GRACE_SECONDS", "8"))))
    except ValueError:
        print("[auth] Ignoring invalid REFRESH_REUSE_GRACE_SECONDS -- using 8.")
        return 8


REFRESH_REUSE_GRACE_SECONDS = _grace_seconds_from_env()

# POST /auth/login lockout policy (same "reasonable human typo tolerance vs.
# brute-force resistance" tradeoff as the email-OTP reset limits below)
# — 5 wrong passwords in a row is well past plausible fat-fingering
# (esp. for a temp password patients type once) but still cheap for a
# legitimate user to recover from after a 20 minute cooldown.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 20

# Email-OTP password reset (POST /auth/request-password-reset-otp,
# POST /auth/reset-password-with-otp) policy. Two independent limits, same
# "persist on the row, survive restarts" discipline as the lockout columns
# above:
#   - OTP_MAX_VERIFY_ATTEMPTS: wrong-code guesses against one live OTP.
#     Exceeding it invalidates that OTP outright (must request a fresh one)
#     rather than extending a cooldown indefinitely.
#   - OTP_MAX_REQUESTS_PER_WINDOW / OTP_REQUEST_WINDOW_MINUTES: how many
#     *new* OTPs can be requested for one NRIC in a rolling window, so an
#     attacker can't email-bomb a patient's inbox by repeatedly hitting
#     request-password-reset-otp.
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_VERIFY_ATTEMPTS = 5
OTP_MAX_REQUESTS_PER_WINDOW = 3
OTP_REQUEST_WINDOW_MINUTES = 15

# HMAC key for hashing OTP codes at rest -- deliberately NOT bcrypt
# (pwd_context.hash below): bcrypt is tuned to be slow, which is the right
# tradeoff for a long-lived login password but wasted cost for a 6-digit,
# 10-minute-lived, rate-limited code. A keyed HMAC-SHA256 is fast, fixed
# time-cost, and just as unrecoverable without this key. Same
# environment-sourced secret-management treatment as SECRET_KEY above --
# no hardcoded fallback, fail loudly at import time if unset.
try:
    _OTP_HMAC_KEY = os.environ["OTP_HMAC_KEY"].encode("utf-8")
except KeyError as exc:
    raise RuntimeError(
        "OTP_HMAC_KEY environment variable is not set. Copy backend/.env.example "
        "to backend/.env and set OTP_HMAC_KEY to a real, high-entropy value "
        "(generate one with: python -c \"import secrets; print(secrets.token_hex(32))\")."
    ) from exc

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
# auto_error=False: no 401 when the Authorization header is absent -- used
# by the deliberately-public emergency scan endpoints, which stay reachable
# without a token but bind (and mark "verified") the real staff identity
# when one IS presented. See get_optional_current_user below.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Ambiguous-looking characters excluded so a human can reliably read/type a
# temp password off a screen or printed slip: 0/O, 1/l/I.
_TEMP_PASSWORD_ALPHABET = "".join(
    c for c in string.ascii_letters + string.digits if c not in "0O1lI"
)


def generate_temp_password(length: int = 14) -> str:
    """Cryptographically random temporary password (secrets module, not
    random/uuid4). Used both when staff issue a brand-new patient login and
    when staff regenerate/reset an existing one."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


def generate_otp_code(length: int = OTP_LENGTH) -> str:
    """Cryptographically random numeric OTP (secrets module, not random).
    Zero-padded so e.g. "004821" is a valid 6-digit code, not "4821"."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_otp_code(code: str) -> str:
    """Keyed HMAC-SHA256 hex digest -- see _OTP_HMAC_KEY comment above for
    why this isn't bcrypt. Only ever the hash is persisted (User.otp_code_hash);
    the plaintext code exists only transiently in memory to email it out."""
    return hmac.new(_OTP_HMAC_KEY, code.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp_code(code), code_hash)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    password_changed_at: Optional[datetime] = None,
) -> str:
    """`password_changed_at` should be the issuing user's CURRENT
    `User.password_changed_at` at the moment the token is minted (the
    caller already has the full User row -- see auth_router.py::login).
    Embedded as the `pwd_changed_at` claim (epoch seconds, so it survives
    JSON/JWT round-tripping without a datetime-parsing dependency on the
    decode side) so _resolve_current_user below can detect and reject a
    token issued BEFORE a subsequent password change. Omitted entirely
    when `password_changed_at` is None (user has no watermark yet -- either
    they've never changed their password since this feature shipped, or
    this call site doesn't have one to embed), which is exactly the
    backward-compatible "don't reject" case on the decode side."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    if password_changed_at is not None:
        to_encode["pwd_changed_at"] = password_changed_at.timestamp()
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ---------- Refresh tokens (P2.5, Security Audit M4) ----------
def _hash_refresh_token(token: str) -> str:
    """Keyed HMAC-SHA256, same discipline as hash_otp_code -- only ever the
    hash is persisted (models.RefreshToken.token_hash). Reuses SECRET_KEY
    (already this app's general auth secret, used for JWT signing) rather
    than adding a third secret to backend/.env.example; the "refresh:"
    prefix domain-separates this HMAC's input space from anything else
    that might ever key off the same secret, so a collision in one context
    can't be replayed as a valid value in the other."""
    return hmac.new(SECRET_KEY.encode("utf-8"), b"refresh:" + token.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def client_fingerprint(user_agent: "str | None") -> "str | None":
    """A COARSE device fingerprint for a refresh token: sha256 of the
    User-Agent header, or None when there is no UA (native clients, curl).
    Deliberately not IP-based -- a phone's IP changes constantly. Only ever
    used to tighten the concurrent-refresh-race grace, never as a hard auth
    factor (a browser update legitimately changes the UA)."""
    ua = (user_agent or "").strip()
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()


def issue_refresh_token(
    db: Session, user: "models.User", *, fingerprint: "str | None" = None,
) -> tuple[str, "models.RefreshToken"]:
    """Mints a new refresh token for `user`. Returns (plaintext, row) --
    the plaintext is the caller's ONE chance to see it (set it as the
    HttpOnly cookie / return it to a native client); it is never stored or
    logged anywhere after this call returns. `fingerprint` (see
    client_fingerprint) is stored for the race-grace check only."""
    plaintext = _generate_refresh_token()
    row = models.RefreshToken(
        user_id=user.id,
        token_hash=_hash_refresh_token(plaintext),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        client_fingerprint=fingerprint,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return plaintext, row


def revoke_all_refresh_tokens_for_user(db: Session, user: "models.User") -> None:
    """Called on logout-everywhere triggers: a password change
    (auth_router._apply_new_password) and detected refresh-token reuse
    (see rotate_refresh_token below). Bulk UPDATE, not a Python loop -- a
    user could plausibly have many rows (one per device that ever logged
    in and was never cleanly logged out)."""
    db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user.id,
        models.RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()


def _is_concurrent_refresh_race(
    db: Session, revoked_row: "models.RefreshToken",
    presented_fingerprint: "str | None" = None,
) -> bool:
    """True when an already-revoked token being presented again looks like a
    concurrent-tab refresh race rather than token reuse/theft, per
    REFRESH_REUSE_GRACE_SECONDS. ALL must hold:
      - the row was ROTATED, not logged-out / chain-revoked
        (`replaced_by_id` is set),
      - it was revoked within the (short) grace window,
      - its replacement row still exists, is itself un-revoked, AND is still
        the head of the chain (`replaced_by_id is None`) -- i.e. NOBODY has
        rotated past it yet. Once any client has moved on to a further token,
        a reuse of this one is a stale replay, not a live race,
      - if BOTH the row and this request carry a device fingerprint (see
        client_fingerprint) they MATCH. A reuse from a different device than
        the token was issued to is not a tab race -- it is the theft case
        the grace must NOT cover. Skipped when either side is NULL (native
        client, pre-migration token) rather than failing closed on it.

    Residual risk this still accepts (see Security Audit.md): a same-device
    attacker -- one who exfiltrated the token AND runs the same User-Agent
    string -- winning a sub-second rotation race. Narrow.
    """
    if revoked_row.replaced_by_id is None or revoked_row.revoked_at is None:
        return False
    if datetime.utcnow() - revoked_row.revoked_at > timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS):
        return False
    if (
        revoked_row.client_fingerprint
        and presented_fingerprint
        and revoked_row.client_fingerprint != presented_fingerprint
    ):
        return False
    replacement = (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.id == revoked_row.replaced_by_id)
        .first()
    )
    return (
        replacement is not None
        and replacement.revoked_at is None
        and replacement.replaced_by_id is None
    )


def rotate_refresh_token(
    db: Session, raw_token: str, *, presented_fingerprint: "str | None" = None,
) -> Optional[tuple["models.User", str]]:
    """The core of POST /auth/refresh: validates `raw_token`, and on
    success ROTATES it (revokes this row, issues a brand new one) rather
    than just re-validating it repeatedly -- a caller that goes on to
    present the OLD token again after this is either replaying a stale
    request or is a stolen/duplicated copy of a token the legitimate
    client has already moved past. That specific case (a row that exists
    and matches, but is ALREADY revoked) is treated as a compromise
    signal: every refresh token for that user is revoked, forcing a fresh
    login on every device rather than trusting the chain further -- UNLESS
    it looks like a concurrent-tab race (see _is_concurrent_refresh_race /
    REFRESH_REUSE_GRACE_SECONDS), where only this one request fails.

    Returns (user, new_plaintext_refresh_token), or None if `raw_token`
    doesn't match any row, is expired, was a graced concurrent-refresh
    race, or was the reuse-of-revoked compromise case (already
    logged/handled internally)."""
    token_hash = _hash_refresh_token(raw_token)
    row = db.query(models.RefreshToken).filter(models.RefreshToken.token_hash == token_hash).first()
    if row is None:
        return None
    if row.revoked_at is not None:
        if _is_concurrent_refresh_race(db, row, presented_fingerprint):
            # Almost certainly a second browser tab presenting the token the
            # first tab just rotated -- not theft. Fail this request only
            # (the client retries with the updated cookie); do NOT revoke the
            # chain. See REFRESH_REUSE_GRACE_SECONDS.
            #
            # Logged at WARNING (not silent): the residual risk this grace
            # accepts (an attacker who holds a valid token winning a
            # rotation race, see _is_concurrent_refresh_race) is at least
            # detectable after the fact -- a burst of these for one user id
            # is the signal.
            logging.getLogger("clarion.auth").warning(
                "refresh-token reuse graced as a concurrent-tab race "
                "(user=%s, token row=%s)", row.user_id, row.id,
            )
            return None
        # Reuse of a token that was already rotated away -- see docstring.
        if row.user is not None:
            revoke_all_refresh_tokens_for_user(db, row.user)
        return None
    if row.expires_at < datetime.utcnow():
        return None

    user = row.user
    if user is None:
        return None

    new_plaintext, new_row = issue_refresh_token(db, user, fingerprint=presented_fingerprint)
    row.revoked_at = datetime.utcnow()
    row.replaced_by_id = new_row.id
    db.add(row)
    db.commit()
    return user, new_plaintext


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """POST /auth/logout: revokes exactly the one presented token (not
    every session on every device -- a deliberate "log out THIS device"
    semantics, unlike revoke_all_refresh_tokens_for_user's "everywhere").
    A no-op (not an error) if the token is unknown or already revoked --
    logout should never fail loudly over a stale/already-cleared cookie."""
    token_hash = _hash_refresh_token(raw_token)
    row = db.query(models.RefreshToken).filter(models.RefreshToken.token_hash == token_hash).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.add(row)
        db.commit()


def _resolve_current_user(token: str, db: Session) -> models.User:
    """Shared identity resolution for both get_current_user variants below:
    decode the JWT, look up the user, 401 if either fails. Does NOT check
    must_change_password -- that's layered on top by get_current_user.

    Also enforces JWT revocation-on-password-change. The ONLY thing that
    gates whether this check runs at all is the user's CURRENT
    `password_changed_at` on the DB row:
      - If it's still None (this user has never gone through
        _apply_new_password since the migration landed -- no watermark
        exists yet to compare against), skip the check entirely and accept
        the token regardless of whether it carries a `pwd_changed_at`
        claim. This is what keeps the migration itself from mass-logging
        out every existing session the moment it lands.
      - Once it's set (an ACTUAL password change has happened at some
        point), every token is held to it: a token with no `pwd_changed_at`
        claim at all necessarily predates that first-ever password change
        (create_access_token only ever omits the claim when
        password_changed_at was still None at issuance time -- see its
        docstring) and is rejected outright; a token that DOES carry the
        claim is rejected only if the DB value is strictly newer than the
        claim (i.e. the password was changed AFTER this particular token
        was issued). A token issued at/after the most recent change (claim
        equals the current DB value) is accepted, same 401 used for every
        other invalid-token case, so a stolen/leaked token stops working
        the moment the legitimate user changes their password.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_pwd_changed_at = payload.get("pwd_changed_at")
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception

    if user.password_changed_at is not None:
        if token_pwd_changed_at is None:
            # A password change has happened at some point, but this token
            # carries no watermark at all -- it necessarily predates that
            # change (see docstring above). Stale, reject.
            raise credentials_exception
        if user.password_changed_at.timestamp() > float(token_pwd_changed_at):
            raise credentials_exception

    return user


def get_current_user_allow_pending_change(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    """Same as get_current_user, but does NOT block a user whose
    must_change_password flag is still set. Reserved for the small,
    explicit set of endpoints that must stay reachable so such a user can
    actually clear that flag: GET /auth/me and POST /auth/change-password.
    (There is no server-side logout endpoint -- JWTs are stateless here --
    so there's nothing else to exempt.) Every other authenticated route
    should keep using get_current_user / require_roles below."""
    return _resolve_current_user(token, db)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    """Standard auth dependency used by (almost) every protected endpoint,
    directly or via require_roles(). Enforces must_change_password
    server-side: a staff-issued temp password or a fresh self-service reset
    is only ever good for GET /auth/me and POST /auth/change-password until
    the user actually changes it -- previously this flag was purely
    advisory/client-side (mobile happened to gate on it, the web console
    didn't even try), so a captured or shoulder-surfed temp password token
    was fully usable against every other endpoint indefinitely."""
    user = _resolve_current_user(token, db)
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "Password change required",
                "must_change_password": True,
            },
        )
    return user


def get_optional_current_user(
    token: "str | None" = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> "models.User | None":
    """Identity for endpoints that are reachable WITHOUT authentication but
    behave better with it -- currently only the emergency scan endpoints
    (Security Audit M6): no token -> None (the endpoint still runs); a valid
    token -> the real user; an invalid/expired/stale token -> None as well,
    never a 401 (a broken token must not turn a life-safety scan into an
    error). Deliberately does NOT enforce must_change_password -- that user
    is still a known, authenticated person for audit-attribution purposes."""
    if not token:
        return None
    try:
        return _resolve_current_user(token, db)
    except HTTPException:
        return None


def require_roles(*roles: str):
    """Dependency factory: require_roles('clinician', 'admin')"""
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires one of roles: {roles}")
        return user
    return checker


def require_page_access(page: str):
    """Dependency factory for the per-facility, admin-configurable
    page-access layer (see app/permissions.py and models.RolePagePermission).

    This is an ADDITIONAL layer on top of each endpoint's own
    require_roles(...) gate, NOT a replacement -- it's applied at ROUTER
    level in app/main.py (include_router(..., dependencies=[...])) so every
    endpoint on a page-scoped router is covered without touching each route.

    Enforcement rules:
      - admin: every page, always -> pass.
      - a role OUTSIDE permissions.CONFIGURABLE_STAFF_ROLES (patient /
        emergency_responder / anything unexpected): NOT page-gated here --
        governed only by the endpoint's own require_roles(...). This is what
        keeps a patient reachable on the patient-facing/self-service routes
        that live on the otherwise staff-scoped patients/reception routers
        (GET /patients/{id}, PATCH /patients/{id}/profile, self-checkin...).
      - a configurable staff role (clinician / records_officer /
        receptionist / pharmacist): allowed only if `page` is in that
        (facility, role)'s allowed_pages -- lazily defaulted if the facility
        has no row yet. 403 otherwise.
    """
    def checker(
        user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> models.User:
        if user.role == "admin":
            return user
        if user.role not in permissions.CONFIGURABLE_STAFF_ROLES:
            return user
        allowed = permissions.allowed_pages_for(db, user.facility, user.role)
        if page not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Your role does not have access to the {page} area.",
            )
        return user
    return checker
