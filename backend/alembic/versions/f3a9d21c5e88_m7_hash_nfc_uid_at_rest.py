"""Security Audit M7: store the NFC card UID only as a keyed HMAC

Revision ID: f3a9d21c5e88
Revises: e7c1a9b3f2d4
Create Date: 2026-09-07 00:00:00.000000

- Adds ``emergency_tokens.nfc_uid_last4`` (nullable, cleartext 4-char tail
  of the raw UID, display-only).
- Rewrites every existing ``nfc_uid`` value in place from the raw MIFARE UID
  to ``auth.hash_nfc_uid(raw)`` (keyed HMAC-SHA256 hex) and backfills
  ``nfc_uid_last4``. A leak of the emergency_tokens table then yields no
  usable card keys.
- Adds an index on ``audit_logs.timestamp`` -- the M7c NFC-scan anomaly
  check windows on it (``WHERE timestamp >= now() - 1h``) on the life-safety
  scan path.

The demo seed has no NFC grants, so the data step is a no-op on a fresh DB.
``downgrade()`` drops the new column but CANNOT restore the raw UIDs (the
HMAC is one-way) -- a rollback past this point means every physical card
must be re-registered.
"""
import hashlib
import hmac
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9d21c5e88"
down_revision: Union[str, Sequence[str], None] = "e7c1a9b3f2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _canonical(raw_uid: str) -> str:
    return "".join(raw_uid.split()).replace(":", "").replace("-", "").upper()


def _hash_nfc_uid(raw_uid: str) -> str:
    """Same construction as app.auth.hash_nfc_uid -- inlined so the migration
    doesn't import the app."""
    key = os.environ.get("OTP_HMAC_KEY", "").encode("utf-8")
    if not key:
        raise RuntimeError(
            "OTP_HMAC_KEY must be set to run migration f3a9d21c5e88 -- it "
            "keys the NFC-UID HMAC. Migrating existing emergency_tokens rows "
            "with an empty key would permanently mismatch every physical card."
        )
    return hmac.new(
        key, b"nfc-uid:" + _canonical(raw_uid).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _last4(raw_uid: str) -> str:
    cleaned = _canonical(raw_uid)
    return cleaned[-4:] if cleaned else ""


def upgrade() -> None:
    with op.batch_alter_table("emergency_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nfc_uid_last4", sa.String(length=8), nullable=True))

    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"], unique=False)

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, nfc_uid FROM emergency_tokens WHERE nfc_uid IS NOT NULL")
    ).fetchall()
    for row_id, raw_uid in rows:
        # Skip anything that already looks like our 64-hex-char HMAC (idempotent re-run).
        if len(raw_uid) == 64 and all(c in "0123456789abcdef" for c in raw_uid):
            continue
        bind.execute(
            sa.text(
                "UPDATE emergency_tokens SET nfc_uid = :h, nfc_uid_last4 = :l4 WHERE id = :id"
            ),
            {"h": _hash_nfc_uid(raw_uid), "l4": _last4(raw_uid), "id": row_id},
        )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    with op.batch_alter_table("emergency_tokens", schema=None) as batch_op:
        batch_op.drop_column("nfc_uid_last4")
    # The raw UIDs are gone (HMAC is one-way). NULL the column rather than
    # leave a pre-M7 app matching raw UIDs against HMAC digests (every NFC
    # scan/check-in would silently 404) -- an honest "no card" beats a
    # "looks registered, never matches" state. Physical cards must be
    # re-registered after a rollback past this point.
    op.execute("UPDATE emergency_tokens SET nfc_uid = NULL WHERE nfc_uid IS NOT NULL")
