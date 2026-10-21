import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth, permissions, ldap_auth, mfa
from ..guardianship import may_act_for
from ..database import get_db
from ..audit import log_access
from ..email_service import send_new_signin_email, send_password_reset_otp_email
from ..nric import normalize_nric
from ..rate_limit import limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

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

    # Patient accounts are NOT created here -- they go through
    # POST /auth/patients/{id}/issue-account, which hard-codes role="patient",
    # links the right Patient row, and forces a temp-password change. Allowing
    # a raw patient+patient_id here would let an admin mint a
    # known-password login bound to any patient's record.
    if payload.role == "patient" or payload.patient_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Use POST /auth/patients/{patient_id}/issue-account to create a patient login.",
        )
    # Community responders are always time-boxed, which this endpoint cannot express.
    if payload.role == "emergency_responder":
        raise HTTPException(
            status_code=400,
            detail="Use POST /admin/responders to create a time-boxed community responder account.",
        )

    # "Manager admin, not super admin" (see routers/admin.py's module
    # docstring): an admin provisions staff for THEIR OWN facility only.
    # facility is forced from the acting admin's own row and never taken
    # from the request body -- otherwise a facility-A admin could mint an
    # admin/pharmacist/clinician scoped to facility B and walk straight
    # through the facility boundary the admin/pharmacy routers rely on. The
    # one exception is a bootstrap admin who has no facility yet: they may
    # set one (there is no other way to seed the first facility's staff).
    facility = current_user.facility or payload.facility

    user = models.User(
        email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        facility=facility,
        patient_id=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_access(
        db, None, current_user.id, current_user.role, "register_staff_account",
        detail=f"email={user.email} role={user.role} facility={user.facility or '-'}",
        actor_facility=current_user.facility,
    )
    return user


def _resolve_patient_by_nric(db: Session, national_id: str) -> models.Patient | None:
    """Dash-tolerant NRIC -> Patient lookup, used everywhere an NRIC is
    accepted as input (login, both OTP-reset endpoints, and reused by
    patients.py's create-time duplicate check and reception.py's
    check-in-by-IC lookup). Normalizes the caller's input the same way
    models.Patient.normalized_national_id is populated at patient-creation
    time (see that column's docstring), so "520314-01-1234" and
    "520314011234" resolve to the same record via a single indexed query.

    Security Audit M2: this used to be a fetch-every-patient-and-compare
    Python loop, which ran on every unauthenticated login/OTP-reset attempt
    regardless of any per-IP limit -- its cost scaled with total patient
    count. Now O(1) against the indexed, unique normalized_national_id
    column instead."""
    normalized_input = normalize_nric(national_id)
    if not normalized_input:
        return None
    return (
        db.query(models.Patient)
        .filter(models.Patient.normalized_national_id == normalized_input)
        .first()
    )


def _resolve_login_user(db: Session, identifier: str) -> tuple[models.User | None, bool]:
    """Resolve the OAuth2 `username` field to a User, accepting an email, a
    patient's NRIC (Patient.national_id, dash-tolerant -- see
    _resolve_patient_by_nric), or a previously-JIT-provisioned LDAP
    account's stored login identifier (models.User.ldap_username). Tries
    email first (the common case), then ldap_username, then falls back to
    an NRIC -> Patient -> User lookup.

    Why ldap_username, not just email, for an LDAP-backed row (voltagent
    security review finding C1): `email` is populated from the directory's
    `mail` attribute, which is only guaranteed to equal the login string
    under the default `LDAP_USER_SEARCH_FILTER=(mail={username})`. A
    realistic AD deployment logs staff in by `sAMAccountName`/`uid` --
    a DIFFERENT string from their `mail` attribute. Keying this lookup on
    `email` alone would mean a second login for such a user can never find
    the row its first login created (it isn't stored under that email),
    so it would re-attempt JIT-provisioning and crash on the `email`
    unique constraint. Checking BOTH columns in one query keeps a genuine
    email/ldap_username collision (extremely unlikely, both are unique)
    from silently picking the wrong row.

    Returns (user, ldap_eligible). `ldap_eligible` is True unless the
    identifier resolved to a real Patient's NRIC. This is P1.10's
    staff-only boundary for LDAP: a patient identifier (whether or not it
    happens to have a linked User row yet) must never fall through to an
    LDAP bind/JIT-provision attempt, per healthcare/Integration Engine and
    LDAP.md ("Keep local accounts for break-glass admin, service
    integrations, and external/family patient logins"). `user` is None if
    no lookup resolves, so callers can fall through to the existing
    generic "incorrect credentials" response (or, when ldap_eligible,
    attempt an LDAP JIT login first).
    """
    user = (
        db.query(models.User)
        .filter(or_(models.User.email == identifier, models.User.ldap_username == identifier))
        .first()
    )
    if user:
        return user, True

    patient = _resolve_patient_by_nric(db, identifier)
    if patient:
        user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
        return user, False

    return None, True


def _jit_provision_ldap_user(db: Session, identifier: str, password: str) -> models.User | None:
    """P1.10 Case A: `identifier` matched no local User by email/ldap_username
    (and isn't a real patient NRIC -- caller already checked ldap_eligible).
    Attempts a full LDAP bind + role-resolve + provision. Returns the new
    User row on success, else None -- caller falls through to the existing
    generic 401. Never invents a role: if no LdapRoleMapping group matches,
    the login is denied even though the directory bind itself succeeded
    (least privilege -- see ldap_auth.resolve_role_for_groups)."""
    result = ldap_auth.authenticate_ldap(identifier, password)
    if result is None:
        return None
    role, facility = ldap_auth.resolve_role_for_groups(db, result.group_dns)
    if role is None:
        logger.warning(
            "ldap_auth: %s authenticated but no ldap_role_mappings group matched -- denying login",
            result.dn,
        )
        return None
    email = result.email or identifier
    user = models.User(
        email=email,
        # A random, never-issued bcrypt hash -- this account can never log
        # in via the local-password path (auth_source below routes every
        # future login for it back through LDAP). Not a shared/predictable
        # value, so it can't be brute-forced into a usable password either.
        hashed_password=auth.hash_password(secrets.token_urlsafe(32)),
        full_name=result.full_name or email,
        role=role,
        facility=facility,
        auth_source="ldap",
        ldap_dn=result.dn,
        # THE identity key for every subsequent login -- see
        # _resolve_login_user's docstring and _verify_ldap_existing_user
        # below, which searches the directory by this value, never by
        # `email` (voltagent review C1).
        ldap_username=identifier,
        must_change_password=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Race (voltagent review M4): a concurrent first-login for this
        # exact identity (same ldap_username, or an email collision with a
        # pre-existing different account) already committed between our
        # lookup and this insert. Re-query by ldap_username -- if it's now
        # there, this is just the benign "someone else's request won the
        # race" case and the caller should proceed as Case B on THAT row,
        # not fail the login outright. An email-only collision (a
        # different, non-ldap account already owns this mail address) is
        # NOT recoverable this way -- deny, don't silently attach to a
        # stranger's local account.
        db.rollback()
        winner = db.query(models.User).filter(models.User.ldap_username == identifier).first()
        if winner is not None:
            return winner
        logger.warning(
            "ldap_auth: JIT-provision for %s failed on a uniqueness conflict "
            "(likely email %r already used by a different, non-LDAP account) -- denying login",
            result.dn, email,
        )
        return None
    db.refresh(user)
    return user


def _verify_ldap_existing_user(db: Session, user: models.User, password: str) -> bool:
    """P1.10 Case B: `user.auth_source == "ldap"`. Re-authenticates against
    the directory on every login (never checks the local placeholder hash),
    searching by `user.ldap_username` -- the SAME identifier that resolved
    this account in the first place (never `user.email`, which may not even
    be searchable under a non-mail LDAP_USER_SEARCH_FILTER -- voltagent
    review C1) -- and re-syncs role/facility/full_name/ldap_dn from CURRENT
    group membership, so a revoked AD group (or a rename) takes effect on
    this account's very next login rather than only at JIT-provision time."""
    result = ldap_auth.authenticate_ldap(user.ldap_username or user.email, password)
    if result is None:
        return False
    role, facility = ldap_auth.resolve_role_for_groups(db, result.group_dns)
    if role is None:
        logger.warning(
            "ldap_auth: %s authenticated but no ldap_role_mappings group matched -- denying login",
            result.dn,
        )
        return False
    changed = False
    if user.role != role:
        user.role = role
        changed = True
    if facility is not None and user.facility != facility:
        user.facility = facility
        changed = True
    if result.full_name and user.full_name != result.full_name:
        user.full_name = result.full_name
        changed = True
    if user.ldap_dn != result.dn:
        user.ldap_dn = result.dn
        changed = True
    if changed:
        db.add(user)
        db.commit()
    return True


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


def _user_out_for(db: Session, user: models.User, patient_id: Optional[str] = None) -> schemas.UserOut:
    """The user as clients see it. When `patient_id` is a profile this patient login is acting
    for, `patient_id`/`full_name` describe that profile (so clients that read them need no
    change) and `home_patient_id` is the login's own record."""
    _with_missing_profile_fields(user)
    _attach_allowed_pages(db, user)
    _attach_has_signature(user)
    _attach_has_photo(user)
    out = schemas.UserOut.model_validate(user)
    if patient_id and patient_id != user.patient_id:
        profile = db.get(models.Patient, patient_id)
        out = out.model_copy(update={
            "patient_id": patient_id, "full_name": profile.full_name if profile else out.full_name,
            "acting_for": True, "home_patient_id": user.patient_id, "missing_profile_fields": [],
        })
    return out


def _with_missing_profile_fields(user: models.User) -> models.User:
    """Stashes the computed list as a plain (unmapped, non-persisted)
    instance attribute so schemas.UserOut's from_attributes conversion
    picks it up -- same technique this ORM already relies on for nested
    relationship attributes, just for a computed value instead of a
    mapped column."""
    user.missing_profile_fields = _missing_profile_fields(user)
    return user


def _attach_allowed_pages(db: Session, user: models.User) -> models.User:
    """Stashes this user's console page-access list on the ORM instance as
    an unmapped attribute so schemas.UserOut picks it up -- same technique
    as _with_missing_profile_fields above. Resolution (admin -> all pages,
    configurable staff role -> its (facility, role) allowed_pages with a
    lazy default, patient / emergency_responder -> []) lives in
    app/permissions.py, the same source the router-level
    auth.require_page_access enforcement reads from."""
    user.allowed_pages = permissions.allowed_pages_for(db, user.facility, user.role)
    return user


def _attach_has_signature(user: models.User) -> models.User:
    """Stashes bool(signature_object_key) as an unmapped attribute so
    schemas.UserOut.has_signature is populated on POST /auth/login and
    GET /auth/me -- same technique as _attach_allowed_pages above."""
    user.has_signature = bool(getattr(user, "signature_object_key", None))
    return user


def _attach_has_photo(user: models.User) -> models.User:
    """Same technique as _attach_has_signature above, for
    schemas.UserOut.has_photo / models.User.photo_object_key."""
    user.has_photo = bool(getattr(user, "photo_object_key", None))
    return user


# ---------- Session / refresh tokens (P2.5, Security Audit M4) ----------
_REFRESH_COOKIE_NAME = "clarion_refresh_token"

# Cookie Path. Default "/" -- the browser matches this against the
# REQUEST-URL path, not the path the backend ultimately sees. In the
# documented same-origin topology the SPA calls `/api/auth/refresh` (nginx /
# the Caddy edge strip `/api` before the backend), so a `Path=/auth` cookie
# would NEVER be sent on that request and silent refresh would be dead --
# the session would drop to a full re-login every 15 minutes. "/" is safe
# here: the cookie is HttpOnly + SameSite=Strict (its whole CSRF defense,
# see _set_refresh_cookie) and only /auth/refresh + /auth/logout ever read
# it. A deployment that is certain it runs the browser directly against the
# backend origin (no /api prefix) can narrow this to "/auth".
_REFRESH_COOKIE_PATH = os.environ.get("REFRESH_COOKIE_PATH", "/").strip() or "/"


_DUMMY_HASH: Optional[str] = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = auth.hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def _is_demo_env() -> bool:
    """Same demo-detection as main.py's CORS wildcard opt-in and seed.py's
    password-seeding gate -- duplicated rather than shared-imported, same
    as those two (each already independently re-derives this from the two
    raw env vars rather than depending on a shared helper module)."""
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    demo_mode = os.environ.get("DEMO_MODE", "").strip().lower()
    return app_env == "demo" or demo_mode in ("demo", "1", "true")


def _set_refresh_cookie(response: Response, plaintext_refresh_token: str) -> None:
    """Sets the HttpOnly refresh-token cookie the web console relies on
    (native clients get the equivalent value in the `refresh_token` JSON
    field instead -- see schemas.Token). `secure=False` only under
    APP_ENV/DEMO_MODE=demo (local plain-HTTP dev); a real deployment
    always sits behind the TLS-terminating Caddy proxy (P1.9), so
    `secure=True` there -- a browser silently drops a `Secure` cookie set
    over plain HTTP, which would otherwise break local dev entirely.
    Scoped to `path=/auth` so it's never sent to unrelated routes.
    `samesite="strict"` is this cookie's ENTIRE CSRF defense (no separate
    CSRF token needed) -- correct because it's the ONLY credential this
    app ever has a browser attach automatically; every other authenticated
    call is a Bearer header, which a cross-site request can't attach
    without this app's own JS running first (and that's an XSS problem,
    not a CSRF one).

    Path is `_REFRESH_COOKIE_PATH` (default "/"); see that constant for why
    the old `/auth` value silently broke refresh behind the `/api` proxy."""
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=plaintext_refresh_token,
        httponly=True,
        secure=not _is_demo_env(),
        samesite="strict",
        max_age=auth.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_REFRESH_COOKIE_PATH,
    )


def _client_meta(request: Request) -> "tuple[str, str]":
    """(ip, user_agent) for the sessions list. The IP is the proxy-resolved
    client address (same source the rate limiter keys on)."""
    return get_remote_address(request), (request.headers.get("user-agent") or "")[:255]


def _device_label(user_agent: str) -> str:
    ua = user_agent or "unknown device"
    for needle, label in (("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                          ("Safari/", "Safari"), ("okhttp", "CLARION mobile app"), ("Dart/", "CLARION mobile app")):
        if needle in ua:
            return label
    return ua[:60]


def _refuse_if_access_expired(db: Session, user: models.User) -> None:
    """A time-boxed account (community responder) whose window has ended can
    no longer sign in. Only reached with a correct password / verified second
    factor, so naming the reason leaks nothing an attacker could use."""
    if auth.access_expired(user):
        log_access(db, user.patient_id, user.id, user.role, "login_refused_access_expired",
                   actor_facility=user.facility)
        raise HTTPException(
            status_code=403,
            detail="This account's access period has ended. Ask an administrator to extend it.",
        )


def _finish_primary_auth(
    db: Session, request: Request, response: Response, user: models.User, fp: Optional[str],
) -> "Union[schemas.Token, schemas.MfaChallenge]":
    """Everything after a verified first factor: either hand back an MFA
    challenge (no token) or issue the session. Shared by the local, LDAP-JIT
    and LDAP-resync branches of login()."""
    _refuse_if_access_expired(db, user)
    if user.owner_locked_at is not None:
        log_access(db, user.patient_id, user.id, user.role, "login_refused_owner_lock",
                   actor_facility=user.facility)
        raise HTTPException(
            status_code=403,
            detail="This account was locked at the owner's request. Choose Forgot password "
                   "to unlock it with a code sent to your email.",
        )
    kind = mfa.challenge_kind(user)
    if kind is not None:
        log_access(db, user.patient_id, user.id, user.role, "login_mfa_challenge",
                   detail=f"kind={kind}", actor_facility=user.facility)
        target = mfa.email_target(db, user)
        return schemas.MfaChallenge(
            mfa_enrol=(kind == "enrol"),
            mfa_token=mfa.make_challenge(user.id, kind, mfa.password_marker(user)),
            email_available=target is not None,
            email_hint=mfa.mask_email(target) if target else None,
        )
    return _complete_login(db, request, response, user, fp)


def _complete_login(
    db: Session, request: Request, response: Response, user: models.User, fp: Optional[str],
    mfa_ok: bool = False,
) -> schemas.Token:
    _refuse_if_access_expired(db, user)  # the window can close between password and MFA
    ip, ua = _client_meta(request)
    new_device = bool(fp) and not db.query(models.RefreshToken.id).filter_by(
        user_id=user.id, client_fingerprint=fp).first()
    result = _issue_login_response(db, response, user, fingerprint=fp, ip=ip, user_agent=ua, mfa_ok=mfa_ok)
    log_access(db, user.patient_id, user.id, user.role, "login_success", actor_facility=user.facility)
    if new_device and user.email and not user.email.endswith((".test", ".invalid", ".demo")):
        try:
            send_new_signin_email(user.email, user.full_name,
                                  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), _device_label(ua))
        except Exception:  # noqa: BLE001 -- a notice must never break sign-in
            logging.getLogger("clarion.auth").exception("new-device email failed")
    return result


def _issue_login_response(
    db: Session, response: Response, user: models.User,
    refresh_plaintext: Optional[str] = None,
    fingerprint: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    mfa_ok: bool = False,
) -> schemas.Token:
    """Shared by every successful-auth branch in login() (local, LDAP JIT,
    LDAP resync) and by POST /auth/refresh: mints the short-lived access
    JWT, cookies a refresh token, and assembles the response.

    `refresh_plaintext` lets POST /auth/refresh pass the token
    `auth.rotate_refresh_token` ALREADY minted, instead of issuing yet
    another one -- previously that path rotated (row A) AND then issued a
    second fresh row (B), handing the client B and leaving A as an
    un-revoked orphan the client never saw. That both leaked a live token
    per refresh and broke the `replaced_by_id` rotation chain (A pointed at
    nothing the client held), which the concurrent-refresh-race check
    (auth._is_concurrent_refresh_race) relies on. The login paths pass
    nothing and still get a freshly issued token."""
    token = auth.create_access_token(
        {"sub": user.id, "role": user.role},
        password_changed_at=user.password_changed_at,
    )
    if refresh_plaintext is None:
        refresh_plaintext, _row = auth.issue_refresh_token(
            db, user, fingerprint=fingerprint, ip=ip, user_agent=user_agent, mfa_ok=mfa_ok)
    _set_refresh_cookie(response, refresh_plaintext)
    _with_missing_profile_fields(user)
    _attach_allowed_pages(db, user)
    _attach_has_signature(user)
    _attach_has_photo(user)
    return schemas.Token(access_token=token, user=user, refresh_token=refresh_plaintext)


@router.post("/login", response_model=Union[schemas.Token, schemas.MfaChallenge])
@limiter.limit("20/minute")  # per-IP, ON TOP OF the per-account lockout below
# (Security Audit M1) -- the per-account lockout alone doesn't stop
# password-spraying: an attacker trying ONE guess each against many
# DIFFERENT accounts never trips any single account's counter. 20/minute is
# generous enough for a shared front-desk kiosk logging in many different
# staff/patients over a shift, while still bounding a scripted spray.
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
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

    P1.10 adds LDAP/AD as a second, opt-in (LDAP_ENABLED) provider, staff-only
    (see the `ldap_eligible` docstring on _resolve_login_user -- a real
    patient NRIC never reaches it, JIT-provisioned or not). Two cases, both
    of which then rejoin this same lockout/token-issue flow below:
      - no local User at all, identifier is ldap_eligible -> attempt a full
        bind + role-resolve + JIT-provision (_jit_provision_ldap_user).
      - an existing User with auth_source == "ldap" -> its local
        hashed_password is an unusable placeholder (see
        _jit_provision_ldap_user), so the password check below is replaced
        with a fresh directory bind + role re-sync (_verify_ldap_existing_user)
        instead of ever comparing against that placeholder.
    With LDAP_ENABLED unset (the default), ldap_auth.ldap_enabled() is
    always False and this function's behavior is unchanged from before P1.10.
    """
    fp = auth.client_fingerprint(request.headers.get("user-agent"))
    user, ldap_eligible = _resolve_login_user(db, form_data.username)

    if user is None and ldap_eligible and ldap_auth.ldap_enabled():
        user = _jit_provision_ldap_user(db, form_data.username, form_data.password)
        if user is not None:
            return _finish_primary_auth(db, request, response, user, fp)
        # Unknown to the directory, or authenticated but unmapped to any
        # role -- fall through to the same generic 401 as an unknown local
        # identifier (ldap_auth/_jit_provision_ldap_user already logged why).

    if user:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if user.login_locked_until and now < user.login_locked_until:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again after {user.login_locked_until.isoformat()}Z.",
            )
        if user.login_locked_until and now >= user.login_locked_until:
            # Security Audit M1: the lock has LAPSED -- reset the counter
            # before the password check below, not after. Without this, a
            # lapsed lock left login_failed_count at its old (>= MAX)
            # value, so a single further wrong guess re-triggered
            # `login_failed_count >= LOGIN_MAX_ATTEMPTS` immediately and
            # re-locked the account for another full LOGIN_LOCKOUT_MINUTES
            # -- an attacker who merely knows the account's identifier
            # could keep it locked out indefinitely with one request every
            # LOGIN_LOCKOUT_MINUTES, forever, without ever knowing the
            # password. A lapsed timeout is a fresh start: it now takes a
            # full new run of LOGIN_MAX_ATTEMPTS wrong guesses to re-lock.
            user.login_failed_count = 0
            user.login_locked_until = None

        if user.auth_source == "ldap" and ldap_auth.ldap_enabled():
            password_ok = _verify_ldap_existing_user(db, user, form_data.password)
        else:
            password_ok = auth.verify_password(form_data.password, user.hashed_password)

        if password_ok:
            if user.login_failed_count or user.login_locked_until:
                user.login_failed_count = 0
                user.login_locked_until = None
                db.add(user)
                db.commit()
            return _finish_primary_auth(db, request, response, user, fp)

        # Same per-account lockout bookkeeping for an LDAP-backed account's
        # failed bind as for a local account's wrong password -- LDAP-backed
        # accounts are not exempt from brute-force protection.
        user.login_failed_count = (user.login_failed_count or 0) + 1
        if user.login_failed_count >= auth.LOGIN_MAX_ATTEMPTS:
            user.login_locked_until = now + timedelta(minutes=auth.LOGIN_LOCKOUT_MINUTES)
        db.add(user)
        db.commit()
        log_access(db, user.patient_id, user.id, user.role,
                   "login_locked" if user.login_locked_until else "login_failed",
                   detail=f"count={user.login_failed_count}", actor_facility=user.facility)
    else:
        # Unknown identifier: burn the same hashing time a real account costs
        # so response timing doesn't reveal which identifiers exist.
        auth.verify_password(form_data.password, _dummy_hash())

    raise HTTPException(status_code=401, detail="Incorrect email/NRIC or password")


@router.post("/refresh", response_model=schemas.Token)
@limiter.limit("30/minute")  # per-IP -- higher than /login since a busy
# multi-tab session can legitimately trigger several silent refreshes; still
# a real backstop against a scripted loop hammering this endpoint.
def refresh_access_token(
    request: Request,
    response: Response,
    body: Optional[schemas.RefreshTokenRequest] = Body(None),
    db: Session = Depends(get_db),
):
    """Mints a fresh short-lived access token from a still-valid refresh
    token, WITHOUT a full re-login -- the web console's silent-refresh
    call (cookie-based) and a native client's explicit one (JSON body;
    `request.cookies` is simply empty for those, so the `or` below falls
    through correctly). See auth.rotate_refresh_token for the actual
    validation/rotation/reuse-detection logic; this endpoint is a thin
    HTTP wrapper around it plus setting the new cookie.

    401 on anything wrong (missing/unknown/expired/reused token) -- same
    "nothing more specific than a generic failure" discipline as
    POST /auth/login, so this can't be used to fingerprint why a given
    refresh attempt failed."""
    raw_token = request.cookies.get(_REFRESH_COOKIE_NAME) or (body.refresh_token if body else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    fp = auth.client_fingerprint(request.headers.get("user-agent"))
    ip, ua = _client_meta(request)
    result = auth.rotate_refresh_token(db, raw_token, presented_fingerprint=fp, ip=ip, user_agent=ua)
    if result is None:
        # A stale cookie is now definitely dead (either genuinely expired,
        # or auth.rotate_refresh_token just nuked the whole chain on a
        # detected-reuse signal) -- clear it so the client doesn't keep
        # silently retrying it on every subsequent request.
        response.delete_cookie(_REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user, new_plaintext = result
    issued = _issue_login_response(db, response, user, refresh_plaintext=new_plaintext, fingerprint=fp)
    if body and body.act_as and may_act_for(db, user, body.act_as) and body.act_as != user.patient_id:
        # Keep the client acting for the profile it had selected (the link is re-checked here).
        issued.access_token = auth.create_access_token(
            {"sub": user.id, "role": user.role, "act_as": body.act_as}, password_changed_at=user.password_changed_at)
        issued.user = _user_out_for(db, user, body.act_as)
    return issued


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    body: Optional[schemas.RefreshTokenRequest] = Body(None),
    db: Session = Depends(get_db),
):
    """Real server-side logout (Security Audit M4 -- there was none
    before): revokes exactly the refresh token this caller presents (see
    auth.revoke_refresh_token's "this device only" semantics) so it can
    never be used again to mint a fresh access token, then clears the
    cookie. Same cookie-or-body source as POST /auth/refresh, for the same
    reason (native clients have no cookie jar). Always 200 -- an
    absent/already-invalid token is not an error (the caller's intent,
    "make sure I'm logged out", is already satisfied); this must never
    leak whether a given token was valid."""
    raw_token = request.cookies.get(_REFRESH_COOKIE_NAME) or (body.refresh_token if body else None)
    if raw_token:
        auth.revoke_refresh_token(db, raw_token)
    response.delete_cookie(_REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)
    return {"status": "logged_out"}


@router.get("/me", response_model=schemas.UserOut)
def me(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user_allow_pending_change),
    token: str = Depends(auth.oauth2_scheme),
):
    # Deliberately exempt from the must_change_password block below (see
    # auth.get_current_user_allow_pending_change) -- clients need this to
    # discover the flag is set in the first place.
    act_as = auth.act_as_claim(token)
    if act_as and act_as != current_user.patient_id:
        if not may_act_for(db, current_user, act_as):
            raise HTTPException(status_code=403, detail="You can no longer act for this profile")
        return _user_out_for(db, current_user, act_as)
    _with_missing_profile_fields(current_user)
    _attach_allowed_pages(db, current_user)
    _attach_has_signature(current_user)
    _attach_has_photo(current_user)
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
    # JWT revocation watermark -- any token issued before this moment now
    # fails auth._resolve_current_user's pwd_changed_at check (see that
    # function's docstring / models.User.password_changed_at's comment).
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.owner_locked_at = None
    db.add(user)
    db.commit()
    # P2.5 (Security Audit M4): the watermark above only ever covered the
    # short-lived access token; without this, a refresh token issued
    # before the password change could keep silently minting fresh access
    # tokens forever afterward. "Change your password" now really does
    # mean "log out everywhere" for both halves of a session.
    auth.revoke_all_refresh_tokens_for_user(db, user)


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
            email=f"patient-{patient.id}@clarion.local",
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
        # Staff verified someone in person: pending web claims lose. Not flagged -- this endpoint
        # cannot tell which claim was the genuine owner's, and flagging them would blacklist
        # their real email (use the claim's Approve button to also flag the others).
        from .. import claims
        claims.reject_other_claims(db, patient, keep_claim_id=None, winner_email=None, flag=False)

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
@limiter.limit("10/minute")  # per-IP, ON TOP OF this endpoint's own
# per-account OTP_MAX_REQUESTS_PER_WINDOW/OTP_REQUEST_WINDOW_MINUTES
# (Security Audit M2) -- that counter is keyed per NRIC/account, so it
# does nothing against a caller scripting through many DIFFERENT NRICs
# from one IP. Also matters because _resolve_patient_by_nric runs here on
# every call.
def request_password_reset_otp(request: Request, payload: schemas.PasswordResetOtpRequest, db: Session = Depends(get_db)):
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
    these four cases from the response alone. Whether Mailtrap is even
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
    # False) if Mailtrap isn't configured or the call fails -- deliberately
    # NOT branching the response on its return value (see docstring above).
    send_password_reset_otp_email(patient.email, otp_code, patient.full_name)

    log_access(db, patient.id, "system", None, "password_reset_otp_requested")
    return _REQUEST_OTP_GENERIC_RESPONSE


@router.post("/reset-password-with-otp")
@limiter.limit("10/minute")  # per-IP, ON TOP OF this endpoint's own
# per-account OTP_MAX_VERIFY_ATTEMPTS (Security Audit M2) -- same
# distributed-spray reasoning as POST /auth/request-password-reset-otp
# above; _resolve_patient_by_nric also runs here on every call.
def reset_password_with_otp(request: Request, payload: schemas.PasswordResetWithOtpRequest, db: Session = Depends(get_db)):
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
@limiter.limit("10/minute")  # a stolen token must not be able to guess the current password
def change_password(
    request: Request,
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
    # A forced change (temporary password) is already authenticated by the
    # session that just signed in with it, so only new + confirm are asked.
    # Any voluntary change must still prove the current password.
    if not current_user.must_change_password and not auth.verify_password(
        payload.current_password or "", current_user.hashed_password
    ):
        # 400, not 401: a 401 means "session expired" to every client (refresh/bounce).
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if auth.verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Choose a password different from your current one.")

    _apply_new_password(db, current_user, payload.new_password, must_change=False)
    log_access(db, current_user.patient_id, current_user.id, current_user.role, "change_password",
               actor_facility=current_user.facility)
    return {"status": "ok", "detail": "Password changed successfully."}
