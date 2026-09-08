"""The audit-log hash-chain wire format (P2.9) -- ONE definition.

This module is intentionally a stdlib-only leaf (``hashlib`` / ``hmac`` /
``json`` / ``datetime``). It is imported by BOTH:
  - ``app/audit.py`` (the runtime write + verify path), and
  - the Alembic migration ``b2d7e4a9c1f6`` (which back-fills the chain over
    existing rows and must reproduce byte-for-byte what the app writes).

The migration reaches it the same way ``649f25aeb36f`` reaches ``app.nric``
-- ``alembic/env.py`` puts the backend root on ``sys.path``. Keeping the
construction here instead of copy-pasted into the migration removes the
"keep these two in lockstep or every back-filled row silently fails to
verify" hazard.

``_CHAIN_DOMAIN`` = ``b"audit-chain-v1:"`` is a **frozen wire contract**. A
different canonical form is a NEW function with a NEW version tag, never an
edit to ``canonical_row`` / ``canonical_ts`` / ``row_hash`` -- old rows (and
the old migration) must keep verifying under v1 forever.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64
CHAIN_DOMAIN = b"audit-chain-v1:"


def canonical_ts(value) -> str:
    """Render a timestamp deterministically across engines and read paths.

    SQLAlchemy's SQLite ``DateTime`` drops tzinfo on write and reads back a
    naive value; pymysql coerces an aware datetime to naive-UTC for a MariaDB
    ``DATETIME(6)``; a raw ``SELECT`` returns a ``str`` on SQLite and a
    ``datetime`` on MariaDB. Normalise all of them to naive-UTC ISO-8601 to
    microseconds.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace(" ", "T"))
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def canonical_row(
    *, id: str, seq: int, patient_id, actor, actor_role, actor_facility,
    action, fields_accessed, detail, ts: str,
) -> str:
    """The exact string that gets hashed for a row. Reproducible at verify
    time purely from the persisted columns -- keep the key set in lockstep
    with ``models.AuditLog``."""
    payload = {
        "id": id,
        "seq": seq,
        "patient_id": patient_id,
        "actor": actor,
        "actor_role": actor_role,
        "actor_facility": actor_facility,
        "action": action,
        "fields_accessed": fields_accessed,
        "detail": detail,
        "ts": ts,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def row_hash(canonical: str, seq: int, prev_hash: str, key: bytes) -> str:
    """HMAC-SHA256(key, CHAIN_DOMAIN || seq || "\\n" || prev_hash || "\\n" ||
    canonical). The three segments are unambiguously delimited: ``seq`` is a
    ``\\n``-terminated decimal, ``prev_hash`` is always exactly 64 hex chars,
    ``canonical`` always starts with ``{``."""
    msg = CHAIN_DOMAIN + f"{seq}\n{prev_hash}\n".encode("utf-8") + canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def hash_fields(
    *, key: bytes, prev_hash: str, id: str, seq: int, patient_id, actor,
    actor_role, actor_facility, action, fields_accessed, detail, timestamp,
) -> str:
    """One call: canonicalise the row fields and return its ``row_hash``.
    ``timestamp`` may be a ``datetime`` or a ``str`` (see ``canonical_ts``)."""
    canonical = canonical_row(
        id=id, seq=seq, patient_id=patient_id, actor=actor, actor_role=actor_role,
        actor_facility=actor_facility, action=action, fields_accessed=fields_accessed,
        detail=detail, ts=canonical_ts(timestamp),
    )
    return row_hash(canonical, seq, prev_hash, key)
