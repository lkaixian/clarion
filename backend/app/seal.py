"""Tamper seals for signed-off clinical records.

A signature image proves nothing on its own -- anyone can copy a PNG. The seal
binds {record kind + id, signer, signature-image hash, the record's content,
sealed time} under an Ed25519 key only this server holds. `verify` recomputes
the message from the live row, so any later edit to the row (note text,
signer, timestamp, the stored signature hash) flips it to "altered".

Key: CLARION_SEAL_PRIVATE_KEY (base64 32-byte seed) -> CLARION_FACILITY_PRIVATE_KEY
(the federation key, so peers can verify with the same public key) -> derived
from SECRET_KEY (demo default; rotating SECRET_KEY then invalidates old seals).
# ponytail: one current key; a rotated-out key reads as "unknown_key". Add a
# CLARION_SEAL_PREV_PUBLIC_KEYS list when rotation is actually needed.
"""
import base64
import hashlib

import os
from datetime import datetime, timezone

from mpi import sigs

# kind -> (row fields, ConsultationNote fields or ())
_FIELDS = {
    "encounter": (
        ("patient_id", "facility_name", "encounter_type", "reason", "department", "started_at",
         "notes", "signed_by", "signed_by_name", "signed_by_role"),
        ("subjective", "objective", "assessment", "plan", "treatment_plan", "follow_up_at",
         "referral_service_request_id", "bp_systolic", "bp_diastolic", "temperature_c", "pulse_bpm"),
    ),
    "annotation": (
        ("patient_id", "target_type", "target_id", "kind", "note", "facility_name",
         "signed_by", "signed_by_name", "signed_by_role"), (),
    ),
    "service_result": (
        ("service_request_id", "patient_id", "result_text", "flag_abnormal", "flag_critical",
         "performed_by", "performed_by_name", "performed_by_role", "performed_at", "facility_name",
         "file_sha256", "signed_by", "signed_by_name", "signed_by_role"), (),
    ),
    "dental_entry": (
        ("patient_id", "encounter_id", "tooth_code", "finding", "treatment", "notes", "facility_name",
         "recorded_by", "recorded_by_name", "recorded_by_role",
         "signed_by", "signed_by_name", "signed_by_role"), (),
    ),
}


def _seed() -> str:
    for var in ("CLARION_SEAL_PRIVATE_KEY", "CLARION_FACILITY_PRIVATE_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    from . import auth
    return base64.b64encode(hashlib.sha256(b"clarion-seal-v1|" + auth.SECRET_KEY.encode()).digest()).decode()


def public_key() -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    raw = Ed25519PrivateKey.from_private_bytes(sigs.unb64(_seed())).public_key().public_bytes_raw()
    return sigs.b64(raw)


def key_id() -> str:
    return hashlib.sha256(public_key().encode()).hexdigest()[:16]


def _norm(v):
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.replace(microsecond=0).isoformat()  # MariaDB/SQLite round-trip naive
    if isinstance(v, float):
        return round(v, 3)  # FLOAT column round-trip noise
    return v


def _message(kind: str, row, sealed_at) -> bytes:
    fields, note_fields = _FIELDS[kind]
    doc = {f: _norm(getattr(row, f, None)) for f in fields}
    if note_fields:
        note = getattr(row, "consultation_note", None)
        doc["note"] = None if note is None else {f: _norm(getattr(note, f, None)) for f in note_fields}
    return "|".join([
        "clarion-seal-v1", kind, row.id, str(_norm(sealed_at)), row.signature_sha256 or "",
        sigs.content_hash(doc),
    ]).encode()


def seal(kind: str, row) -> None:
    """Stamp `row.seal` / `seal_key_id` / `sealed_at`. Call after the signature
    snapshot is applied and the row (and its consultation note) is flushed."""
    row.sealed_at = datetime.now(timezone.utc)
    row.seal_key_id = key_id()
    row.seal = sigs.sign(_seed(), _message(kind, row, row.sealed_at))


def status(kind: str, row) -> str:
    """"valid" | "altered" | "unsealed" (pre-seal row) | "unknown_key"."""
    if not row.seal or not row.sealed_at:
        return "unsealed"
    if row.seal_key_id != key_id():
        return "unknown_key"
    return "valid" if sigs.verify(public_key(), _message(kind, row, row.sealed_at), row.seal) else "altered"
