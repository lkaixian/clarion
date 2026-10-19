"""Shared signing helpers for the federation protocol (central MPI <-> hospitals).

Identity is an Ed25519 key pair per facility; the public half is registered
at the central MPI by an admin. There are no shared secrets on the wire.

Two things are signed:

* every request (`request_message`) -- proves *who is calling*, binds the
  body and a timestamp (replay window), and
* every visit pointer (`pointer_message`) -- proves *which hospital vouches
  for that visit and its content hash*, and travels with the pointer so a
  third hospital can verify it without trusting central.

The signed request path is relative to the *service root* (no `/mpi` or
`/api` prefix, no query string), so a reverse proxy that strips a prefix
cannot break verification.
"""
import base64
import os
import hashlib
import json
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MAX_SKEW_SECONDS = 120


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(document: dict) -> str:
    """Stable hash of a visit document: sorted keys, no whitespace."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(canonical.encode("utf-8"))


CENTRAL_AUDIENCE = "mpi"


def request_message(method: str, rel_path: str, ts: int, nonce: str, audience: str, body: bytes) -> bytes:
    # The nonce makes two otherwise-identical requests in the same second
    # sign differently (Ed25519 is deterministic), so the replay cache can
    # tell a legitimate retry from a replay. The audience (the intended
    # recipient: "mpi" or a facility id) means a signature captured by a
    # wrong/hostile endpoint is useless anywhere else.
    return "\n".join(
        ["clarion-req-v1", method.upper(), rel_path, str(ts), nonce, audience, sha256_hex(body)]).encode()


def pointer_message(patient_key: str, facility_id: str, visit_ref: str,
                    visited_at: str, chash: str) -> bytes:
    return "|".join(["clarion-ptr-v1", patient_key, facility_id, visit_ref, visited_at, chash]).encode()


def generate_keypair() -> "tuple[str, str]":
    """(private_seed_b64, public_key_b64) -- for provisioning and tests."""
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes_raw()
    return b64(seed), b64(priv.public_key().public_bytes_raw())


def sign(private_seed_b64: str, message: bytes) -> str:
    return b64(Ed25519PrivateKey.from_private_bytes(unb64(private_seed_b64)).sign(message))


def verify(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(unb64(public_key_b64)).verify(unb64(signature_b64), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_headers(facility_id: str, private_seed_b64: str, method: str,
                 rel_path: str, body: bytes = b"", audience: str = CENTRAL_AUDIENCE) -> dict:
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    return {
        "X-Facility": facility_id,
        "X-Timestamp": str(ts),
        "X-Nonce": nonce,
        "X-Signature": sign(private_seed_b64, request_message(method, rel_path, ts, nonce, audience, body)),
    }


class ReplayCache:
    """(facility, signature) pairs seen inside the freshness window. With
    REDIS_URL set (and the `redis` package installed) the check is a shared
    SET NX EX, so it holds across workers; if Redis is unreachable it falls
    back to this process's own memory (the old behaviour), never to "allow"."""

    def __init__(self, redis_url: "str | None" = None) -> None:
        self._seen: dict = {}
        self._redis = None
        url = redis_url or os.environ.get("REDIS_URL")
        if url:
            try:
                import redis
                self._redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
            except Exception:  # noqa: BLE001 -- package missing / bad URL: stay process-local
                self._redis = None

    def first_time(self, key: tuple, now: float) -> bool:
        if self._redis is not None:
            try:
                return bool(self._redis.set("clarion:replay:" + "|".join(key), 1, nx=True, ex=2 * MAX_SKEW_SECONDS))
            except Exception:  # noqa: BLE001 -- Redis blip: fall through to the local check
                pass
        self._seen = {k: exp for k, exp in self._seen.items() if exp >= now}
        if key in self._seen:
            return False
        self._seen[key] = now + 2 * MAX_SKEW_SECONDS
        return True


def timestamp_fresh(ts: int, now: "float | None" = None) -> bool:
    return abs((now if now is not None else time.time()) - ts) <= MAX_SKEW_SECONDS
