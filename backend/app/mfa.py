"""TOTP multi-factor authentication for the public-facing login.

Pieces (all stdlib + `cryptography`, no new dependency):

* RFC 6238 TOTP (SHA-1, 6 digits, 30 s, +/-1 step) with replay protection --
  `User.mfa_last_step` rejects a code at or below the last accepted step.
* The shared secret is stored AES-256-GCM encrypted (HKDF key derived from
  SECRET_KEY, domain-separated), never in clear.
* A short-lived, purpose-bound *challenge token* (HMAC-signed, 5 min) that
  carries "this user passed the password step" between /auth/login and
  /auth/mfa/*. It is deliberately NOT a JWT, so it can never be accepted as
  an access token by get_current_user.
* One-time recovery codes, stored as HMACs.

Policy: `CLARION_MFA_REQUIRED_ROLES` (comma list, default empty = MFA is
opt-in). A user who has enrolled is ALWAYS challenged, whatever the policy.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ISSUER = "CLARION"
CHALLENGE_TTL_SECONDS = 300
RECOVERY_CODE_COUNT = 8
_STEP = 30
_DIGITS = 6
_WINDOW = 1  # accept the previous and next step (clock skew)


def _secret_key() -> bytes:
    key = os.environ.get("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY must be set")
    return key.encode("utf-8")


def _derive(label: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label.encode()).derive(_secret_key())


# ---- policy ----------------------------------------------------------------

def required_roles() -> set:
    return {r.strip() for r in os.environ.get("CLARION_MFA_REQUIRED_ROLES", "").split(",") if r.strip()}


# Email code as a second factor. Weaker than an authenticator (anyone with the mailbox has it),
# so it is opt-in per role and off for admin / records_officer by default.
_DEFAULT_EMAIL_ROLES = "patient,clinician,pharmacist,receptionist,emergency_responder"


def email_roles() -> set:
    raw = os.environ.get("CLARION_MFA_EMAIL_ROLES", _DEFAULT_EMAIL_ROLES)
    return {r.strip() for r in raw.split(",") if r.strip()}


def _roles_of(user) -> set:
    """Every role the account holds (this runs before a session picks one)."""
    return {user.role, *(r.role for r in getattr(user, "extra_roles", None) or [])}


def email_target(db, user) -> Optional[str]:
    """Where an emailed code goes: the linked patient's own address, else the login email.
    None when the role may not use the email factor or no usable address exists."""
    if not _roles_of(user) & email_roles():
        return None
    from . import models  # local import: mfa.py is loaded before models in some entry points
    addr = None
    # Only a patient-only login trusts the patient record's address (staff can edit it); a login
    # that also holds staff roles gets its codes at its own login email.
    if getattr(user, "patient_id", None) and _roles_of(user) == {"patient"}:
        p = db.query(models.Patient.email).filter(models.Patient.id == user.patient_id).first()
        addr = p[0] if p else None
    addr = (addr or user.email or "").strip()
    return addr if "@" in addr else None


def mask_email(addr: str) -> str:
    local, _, domain = addr.partition("@")
    return f"{local[:1]}***@{domain}"


def is_enrolled(user) -> bool:
    return bool(getattr(user, "mfa_enabled_at", None) and getattr(user, "mfa_secret_enc", None))


def role_requires_mfa(role: str) -> bool:
    return role in required_roles()


def required_for(user) -> bool:
    """MFA is required if ANY role the account holds requires it (not just the active one)."""
    return any(role_requires_mfa(r) for r in _roles_of(user))


def challenge_kind(user) -> Optional[str]:
    """None = no second factor; "verify" = enrolled, ask for a code;
    "enrol" = role requires MFA but the user has not set it up yet."""
    if is_enrolled(user):
        return "verify"
    if required_for(user):
        return "enrol"
    return None


# ---- secret at rest --------------------------------------------------------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_secret(secret_b32: str, user_id: str) -> str:
    """`v1:` + base64(nonce || ct). The AAD is the owning user id, so a blob
    copied into another user's row (DB write access) will not decrypt."""
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_derive("clarion-mfa-secret-v1")).encrypt(nonce, secret_b32.encode(), user_id.encode())
    return "v1:" + base64.b64encode(nonce + ct).decode()


def decrypt_secret(blob: str, user_id: str) -> str:
    """Raises ValueError on any failure (wrong user, tampered, rotated key)."""
    try:
        if not blob.startswith("v1:"):
            raise ValueError("unknown format")
        raw = base64.b64decode(blob[3:])
        return AESGCM(_derive("clarion-mfa-secret-v1")).decrypt(raw[:12], raw[12:], user_id.encode()).decode()
    except Exception as exc:  # noqa: BLE001 -- InvalidTag, binascii.Error, ...
        raise ValueError("cannot decrypt MFA secret") from exc


# ---- TOTP ------------------------------------------------------------------

def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** _DIGITS)
    return str(value).zfill(_DIGITS)


def current_step(now: "float | None" = None) -> int:
    return int((now if now is not None else time.time()) // _STEP)


def code_at(secret_b32: str, step: int) -> str:
    return _hotp(secret_b32, step)


def verify_totp(secret_b32: str, code: str, last_step: "int | None", now: "float | None" = None) -> Optional[int]:
    """The matched step (store it as the new last_step) or None. A step at or
    below `last_step` is a replay and never matches."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != _DIGITS or not code.isdigit():
        return None
    step_now = current_step(now)
    for step in range(step_now - _WINDOW, step_now + _WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_hotp(secret_b32, step), code):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str) -> str:
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(ISSUER)}:{quote(account)}?secret={secret_b32}"
            f"&issuer={quote(ISSUER)}&algorithm=SHA1&digits={_DIGITS}&period={_STEP}")


def qr_png_base64(text: str) -> str:
    import io

    import qrcode
    buf = io.BytesIO()
    qrcode.make(text, box_size=6, border=2).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---- challenge token -------------------------------------------------------

def password_marker(user) -> str:
    """Short digest of the account's password-change watermark, folded into
    the challenge so a password change/reset kills any in-flight challenge."""
    return hashlib.sha256(str(getattr(user, "password_changed_at", None)).encode()).hexdigest()[:8]


def make_challenge(user_id: str, kind: str, marker: str = "0", now: "float | None" = None) -> str:
    exp = int((now if now is not None else time.time()) + CHALLENGE_TTL_SECONDS)
    body = f"mfa1.{kind}.{user_id}.{marker}.{exp}"
    sig = hmac.new(_derive("clarion-mfa-challenge-v1"), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_challenge(token: str, now: "float | None" = None) -> "Optional[tuple[str, str, str]]":
    """(user_id, kind, marker) for a valid, unexpired challenge, else None."""
    try:
        version, kind, user_id, marker, exp, sig = token.split(".")
        if version != "mfa1" or kind not in ("verify", "enrol"):
            return None
        body = f"{version}.{kind}.{user_id}.{marker}.{exp}"
        good = hmac.new(_derive("clarion-mfa-challenge-v1"), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return None
        if (now if now is not None else time.time()) > int(exp):
            return None
        return user_id, kind, marker
    except (ValueError, AttributeError):
        return None


# ---- recovery codes --------------------------------------------------------

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes


def new_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list:
    def one() -> str:
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"
    return [one() for _ in range(n)]


def hash_recovery_code(code: str) -> str:
    norm = code.strip().lower().replace(" ", "")
    return hmac.new(_derive("clarion-mfa-recovery-v1"), norm.encode(), hashlib.sha256).hexdigest()


def looks_like_recovery_code(code: str) -> bool:
    c = (code or "").strip().lower()
    return len(c) == 11 and c[5] == "-"
