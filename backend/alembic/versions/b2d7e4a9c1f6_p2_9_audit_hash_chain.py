"""P2.9: audit_logs tamper-evident hash chain + append-only triggers + seals

Revision ID: b2d7e4a9c1f6
Revises: f3a9d21c5e88
Create Date: 2026-09-08 00:00:00.000000

Delivers roadmap P2.9 / [[Security Audit]] (the tender /
):

  1. Adds ``audit_logs.seq`` / ``prev_hash`` / ``row_hash`` and back-fills
     the chain over every existing row in ``(timestamp ASC, id ASC)`` order
     -- the same tiebreak ``patients.py::get_audit_log`` uses, ascending
     (that endpoint reads descending). ``row_hash`` construction is the ONE
     definition in ``app.audit_hash`` (a stdlib-only leaf, imported here the
     same way ``649f25aeb36f`` imports ``app.nric``), so the back-fill and
     ``app/audit.py`` cannot drift.
  2. Creates ``audit_chain_state`` (the singleton chain-tip row the write
     path ``SELECT ... FOR UPDATE``s) and seeds it from the back-fill.
  3. Creates ``audit_seals`` (the daily WORM anchor -- ``db/seal_audit_day.py``).
  4. Creates ``BEFORE UPDATE`` / ``BEFORE DELETE`` triggers on ``audit_logs``
     -- append-only for the DML-scoped ``clarion_app`` account (no
     DROP/ALTER/TRIGGER, so no TRUNCATE and no dropping the triggers). A
     DDL-capable account (``clarion_migrate`` / root) can still bypass; the
     hash chain + off-box daily WORM seal are what make that detectable.
     This is the part ``db/mariadb/10-accounts.sh`` notes it cannot express
     as a subtractive REVOKE.

``SECRET_KEY`` must be set to run this migration (same requirement pattern as
f3a9d21c5e88's ``OTP_HMAC_KEY``): backfilling with an empty key would bake a
permanently-unverifiable chain. ``downgrade()`` drops the triggers, the two
new tables, and the three columns -- fully reversible (the chain is
recomputed from scratch on a re-upgrade).

RESTARTABLE: on MariaDB the ``ALTER TABLE`` steps auto-commit, so if the
back-fill dies partway (large ``audit_logs``) a plain re-run of
``alembic upgrade head`` resumes -- every structural step is inspector-guarded
and the back-fill is deterministic (fixed ORDER BY, pure hash function) so
re-applying it reproduces identical values. The back-fill runs only when a
row still has ``seq IS NULL`` (or the columns were just added); it drops the
append-only triggers for its duration and re-creates them at the end, so a
failure *during* the back-fill leaves the table briefly unprotected until the
re-run completes -- acceptable because this runs at deploy time with the app
stopped. Streams the read, writes in batches (``_BACKFILL_BATCH``).
"""
import json
import os
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from alembic import op

# The hash-chain wire format is the ONE definition in app/audit_hash.py
# (stdlib-only leaf, reached via alembic/env.py's sys.path -- same as
# 649f25aeb36f importing app.nric). This migration back-fills the chain
# byte-for-byte identically to how app/audit.py writes new rows.
from app.audit_hash import GENESIS_HASH, hash_fields

revision: str = "b2d7e4a9c1f6"
down_revision: Union[str, Sequence[str], None] = "f3a9d21c5e88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _secret() -> bytes:
    key = os.environ.get("SECRET_KEY", "")
    if not key:
        raise RuntimeError(
            "SECRET_KEY must be set to run migration b2d7e4a9c1f6 -- it keys the "
            "audit-log hash chain. Back-filling the chain with an empty key would "
            "produce a permanently unverifiable audit trail."
        )
    return key.encode("utf-8")


def _trigger_sql(bind) -> list[str]:
    name = bind.dialect.name
    if name == "sqlite":
        return [
            "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update "
            "BEFORE UPDATE ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only (P2.9)'); END",
            "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete "
            "BEFORE DELETE ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only (P2.9)'); END",
        ]
    # MariaDB / MySQL
    return [
        "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update "
        "BEFORE UPDATE ON audit_logs FOR EACH ROW "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only (P2.9)'",
        "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete "
        "BEFORE DELETE ON audit_logs FOR EACH ROW "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only (P2.9)'",
    ]


_BACKFILL_BATCH = 2000


def upgrade() -> None:
    # This migration is written to be RESTARTABLE: on MariaDB the ALTER
    # statements auto-commit, so if the (potentially long) back-fill dies
    # partway a re-run of `alembic upgrade head` must not fail on
    # "column already exists". Every structural step below is guarded, and
    # the back-fill itself is deterministic (seq is assigned by a fixed
    # ORDER BY, every hash is a pure function of its inputs) so re-running
    # it over all rows reproduces identical values.
    key = _secret()
    bind = op.get_bind()
    insp = sa.inspect(bind)
    audit_cols = {c["name"] for c in insp.get_columns("audit_logs")}

    to_add = [
        sa.Column(name, type_)
        for name, type_ in (
            ("seq", sa.BigInteger()),
            ("prev_hash", sa.String(length=64)),
            ("row_hash", sa.String(length=64)),
        )
        if name not in audit_cols
    ]
    if to_add:
        with op.batch_alter_table("audit_logs", schema=None) as batch_op:
            for col in to_add:
                batch_op.add_column(sa.Column(col.name, col.type, nullable=True))

    total = bind.execute(sa.text("SELECT COUNT(*) FROM audit_logs")).scalar() or 0
    unfilled = 0
    if not to_add:  # columns already existed -> a prior run got at least this far
        unfilled = bind.execute(
            sa.text("SELECT COUNT(*) FROM audit_logs WHERE seq IS NULL")
        ).scalar() or 0

    if total and (to_add or unfilled):
        # The BEFORE UPDATE trigger (if a prior full run created it) would
        # block the back-fill UPDATEs. Drop them for the duration; they are
        # (re)created at the very end. Deploy-time only, app not serving.
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")

        result = bind.execute(
            sa.text(
                "SELECT id, patient_id, actor, actor_role, actor_facility, action, "
                "fields_accessed, timestamp, detail "
                "FROM audit_logs ORDER BY timestamp ASC, id ASC"
            )
        ).mappings()
        update = sa.text(
            "UPDATE audit_logs SET seq = :seq, prev_hash = :ph, row_hash = :rh WHERE id = :id"
        )
        prev_hash = GENESIS_HASH
        last_seq = 0
        last_hash = GENESIS_HASH
        batch: list = []
        for i, r in enumerate(result, start=1):
            fields = r["fields_accessed"]
            # SQLite JSON column comes back as a str; MariaDB as parsed JSON. The
            # app's ORM read gives a parsed list, so parse here too before hashing.
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (ValueError, TypeError):
                    pass
            row_hash = hash_fields(
                key=key, prev_hash=prev_hash,
                id=r["id"], seq=i, patient_id=r["patient_id"], actor=r["actor"],
                actor_role=r["actor_role"], actor_facility=r["actor_facility"],
                action=r["action"], fields_accessed=fields, detail=r["detail"],
                timestamp=r["timestamp"],
            )
            batch.append({"seq": i, "ph": prev_hash, "rh": row_hash, "id": r["id"]})
            if len(batch) >= _BACKFILL_BATCH:
                bind.execute(update, batch)
                batch = []
            prev_hash = row_hash
            last_seq = i
            last_hash = row_hash
        if batch:
            bind.execute(update, batch)
    else:
        # nothing to back-fill -- read the tip straight off the (complete) chain
        tip = bind.execute(
            sa.text("SELECT seq, row_hash FROM audit_logs ORDER BY seq DESC LIMIT 1")
        ).first()
        last_seq = tip[0] if tip else 0
        last_hash = tip[1] if tip else GENESIS_HASH

    # --- lock the columns down + unique seq (guarded) ------------------
    audit_cols = {c["name"]: c for c in sa.inspect(bind).get_columns("audit_logs")}
    need_notnull = [
        name for name in ("seq", "prev_hash", "row_hash")
        if audit_cols.get(name, {}).get("nullable", True)
    ]
    have_uq = any(
        uc["name"] == "uq_audit_logs_seq"
        for uc in sa.inspect(bind).get_unique_constraints("audit_logs")
    )
    if need_notnull or not have_uq:
        with op.batch_alter_table("audit_logs", schema=None) as batch_op:
            if "seq" in need_notnull:
                batch_op.alter_column("seq", existing_type=sa.BigInteger(), nullable=False)
            if "prev_hash" in need_notnull:
                batch_op.alter_column("prev_hash", existing_type=sa.String(length=64), nullable=False)
            if "row_hash" in need_notnull:
                batch_op.alter_column("row_hash", existing_type=sa.String(length=64), nullable=False)
            if not have_uq:
                batch_op.create_unique_constraint(batch_op.f("uq_audit_logs_seq"), ["seq"])

    # --- chain-tip singleton (guarded) ------------------------------
    if not sa.inspect(bind).has_table("audit_chain_state"):
        op.create_table(
            "audit_chain_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("last_seq", sa.BigInteger(), nullable=False),
            sa.Column("last_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_chain_state")),
        )
    # upsert the tip row (idempotent on a re-run -- the back-fill is deterministic)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    if bind.execute(sa.text("SELECT 1 FROM audit_chain_state WHERE id = 1")).first():
        bind.execute(
            sa.text("UPDATE audit_chain_state SET last_seq = :s, last_hash = :h, updated_at = :u WHERE id = 1"),
            {"s": last_seq, "h": last_hash, "u": now_naive},
        )
    else:
        bind.execute(
            sa.text("INSERT INTO audit_chain_state (id, last_seq, last_hash, updated_at) "
                    "VALUES (1, :s, :h, :u)"),
            {"s": last_seq, "h": last_hash, "u": now_naive},
        )

    # --- daily WORM seal (guarded) ----------------------------------
    if not sa.inspect(bind).has_table("audit_seals"):
        op.create_table(
            "audit_seals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("seal_date", sa.String(length=10), nullable=False),
            sa.Column("from_seq", sa.BigInteger(), nullable=False),
            sa.Column("to_seq", sa.BigInteger(), nullable=False),
            sa.Column("row_count", sa.BigInteger(), nullable=False),
            sa.Column("chain_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
                nullable=True,
            ),
            sa.Column("object_key", sa.String(length=512), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_seals")),
            sa.UniqueConstraint("seal_date", name=op.f("uq_audit_seals_seal_date")),
        )

    # --- physical append-only guarantee (CREATE ... IF NOT EXISTS) --
    for stmt in _trigger_sql(bind):
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")

    op.drop_table("audit_seals")
    op.drop_table("audit_chain_state")

    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_audit_logs_seq"), type_="unique")
        batch_op.drop_column("row_hash")
        batch_op.drop_column("prev_hash")
        batch_op.drop_column("seq")
