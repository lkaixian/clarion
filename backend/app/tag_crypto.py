"""Encrypted payload for the on-tag offline emergency record.

The tag text used to be plaintext readable by any NFC reader. It is now an
AES-256-GCM blob that only a CLARION device holding the data key can open:

    C1.<key_id>.<base64url(nonce(12) || ciphertext || tag(16))>

- The key is derived (HKDF-SHA256) from a server secret per `key_id`; rotate
  by bumping CLARION_TAG_KEY_ID and (after re-writing tags) CLARION_TAG_MIN_KEY_ID.
- AAD binds the blob to the tag's own UID, so a blob copied onto another
  tag fails to open.
- The Flutter app implements the same open() with a key it receives from
  GET /emergency/tag-keys at login (staff only -> every offline read is
  attributable to a logged-in user and uploaded later, see
  POST /emergency/offline-reads).
"""
import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = "C1"
_NONCE_LEN = 12
_GCM_TAG_LEN = 16
OVERHEAD_BYTES = _NONCE_LEN + _GCM_TAG_LEN


def _master() -> bytes:
    # A dedicated secret is preferred; SECRET_KEY is the fallback so a deploy
    # that never set it still works (rotating SECRET_KEY then re-keys tags).
    secret = os.environ.get("CLARION_TAG_KEY_SECRET")
    if not secret:
        # Rotating SECRET_KEY would silently make every tag in the field
        # unreadable -- set CLARION_TAG_KEY_SECRET in production.
        secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("CLARION_TAG_KEY_SECRET or SECRET_KEY must be set")
    return secret.encode("utf-8")


def current_key_id() -> int:
    kid = int(os.environ.get("CLARION_TAG_KEY_ID", "1"))
    if not 0 <= kid <= 10_000:
        raise RuntimeError("CLARION_TAG_KEY_ID must be 0..10000")
    return kid


def min_key_id() -> int:
    kid = int(os.environ.get("CLARION_TAG_MIN_KEY_ID", str(current_key_id())))
    if not 0 <= kid <= current_key_id():
        raise RuntimeError("CLARION_TAG_MIN_KEY_ID must be 0..CLARION_TAG_KEY_ID")
    return kid


def key_for(key_id: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=f"clarion-tag-v1|{key_id}".encode(),
    ).derive(_master())


def revocation_key() -> bytes:
    """Key a device uses to recognise a revoked card offline. Independent of the
    data key ids, so rotating those does not change any card's revocation id."""
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"clarion-tag-revocation-v1",
    ).derive(_master())


def revocation_id(uid_canonical: str) -> str:
    """Stable per-card id (hex, 128 bits) the server lists once the card is
    revoked and a device recomputes from the UID it just read. The Flutter
    app implements the same HMAC (see tag_crypto.dart)."""
    return hmac.new(revocation_key(), f"rev|{uid_canonical}".encode(), hashlib.sha256).hexdigest()[:32]


_DEFAULT_KEY_MAX_AGE_HOURS = 24


def key_max_age_hours() -> int:
    """How long a device may keep using cached keys (and the revocation list)
    without a successful refresh. Env CLARION_TAG_KEY_MAX_AGE_HOURS, 1..168."""
    hours = int(os.environ.get("CLARION_TAG_KEY_MAX_AGE_HOURS", str(_DEFAULT_KEY_MAX_AGE_HOURS)))
    if not 1 <= hours <= 168:
        raise RuntimeError("CLARION_TAG_KEY_MAX_AGE_HOURS must be 1..168")
    return hours


def active_keys() -> dict:
    """{key_id: base64 key} for every id a device may still need to open."""
    return {
        str(k): base64.b64encode(key_for(k)).decode()
        for k in range(min_key_id(), current_key_id() + 1)
    }


def _aad(key_id: int, uid_canonical: str) -> bytes:
    return f"{VERSION}|{key_id}|{uid_canonical}".encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(plaintext: str, uid_canonical: str, key_id: "int | None" = None) -> str:
    kid = current_key_id() if key_id is None else key_id
    nonce = secrets.token_bytes(_NONCE_LEN)
    ct = AESGCM(key_for(kid)).encrypt(nonce, plaintext.encode("utf-8"), _aad(kid, uid_canonical))
    return f"{VERSION}.{kid}.{_b64e(nonce + ct)}"


def open_blob(blob: str, uid_canonical: str) -> str:
    """Server-side mirror of what the app does; raises ValueError on any
    malformed/tampered/wrong-tag blob."""
    try:
        version, kid_s, body = blob.split(".", 2)
        kid = int(kid_s)
        if version != VERSION:
            raise ValueError("unsupported version")
        raw = _b64d(body)
        return AESGCM(key_for(kid)).decrypt(
            raw[:_NONCE_LEN], raw[_NONCE_LEN:], _aad(kid, uid_canonical)
        ).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 -- one opaque failure mode on purpose
        raise ValueError("cannot open tag blob") from exc


def plaintext_budget(max_text_bytes: int, key_id: "int | None" = None) -> int:
    """Largest plaintext (bytes) whose sealed blob still fits `max_text_bytes`."""
    kid = current_key_id() if key_id is None else key_id
    prefix = len(f"{VERSION}.{kid}.")
    b64_chars = max_text_bytes - prefix
    return max(0, (b64_chars * 3) // 4 - OVERHEAD_BYTES)


GENESIS_HASH = "0" * 64
# NOTE on strength: this is an UNKEYED hash over device-chosen fields. It
# detects accidental gaps, replays and edits to rows the server already holds;
# it does not stop a device owner rewriting entries before first upload.


def read_entry_hash(prev_hash: str, seq: int, read_at: str, uid_canonical: str,
                    key_id: int, outcome: str) -> str:
    """Hash-chain link for one offline tag read. The Flutter app computes the
    identical string (lib/services/offline_read_log.dart)."""
    import hashlib
    return hashlib.sha256(
        "|".join([prev_hash, str(seq), read_at, uid_canonical, str(key_id), outcome]).encode("utf-8")
    ).hexdigest()
