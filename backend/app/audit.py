"""Audit logging + the P2.9 tamper-evident hash chain.

`log_access()` is the single chokepoint every audit write goes through
(routers, `emergency.py`, `self_registration.py`, background `system`
actions -- all of them). P2.9 makes that chokepoint also:

  1. link every row to its predecessor with a keyed hash (`seq` / `prev_hash`
     / `row_hash`), so any later edit / delete / mid-chain insert of
     `audit_logs` is detectable (`verify_chain`, `GET /admin/audit/chain-status`);
  2. advance a singleton `AuditChainState` tip row under a lock, so the
     `read-tip -> compute -> append` critical section is serialised across
     workers -- `SELECT ... FOR UPDATE` on the tip row (MariaDB), a
     cross-process `flock` + a thread `RLock` (SQLite, where FOR UPDATE is a
     no-op), with `uq_audit_logs_seq` as the last-resort backstop.

DB-level `BEFORE UPDATE` / `BEFORE DELETE` triggers on `audit_logs` (created
in the same migration) block edits + row deletes for the DML-scoped runtime
account; this chain + the daily WORM seal are the out-of-band check for a
tamper that a DDL-capable account or raw datadir access could still do.

The hash-chain wire format lives in `app/audit_hash.py` (stdlib-only, shared
byte-for-byte with the backfill migration). `seal_day()` writes the daily
WORM anchor (`AuditSeal`) -- run it from cron via `db/seal_audit_day.py`.
"""
import contextlib
import hmac
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .audit_hash import GENESIS_HASH, hash_fields
from .database import engine

# Reuses SECRET_KEY (same pattern as app.auth.hash_refresh_token) so there is
# no extra secret to provision.
#
# KNOWN LIMITATION: SECRET_KEY is also the HS256 JWT key. Rotating it re-keys
# this HMAC, so `verify_chain` would then report every pre-rotation row as
# broken and new rows would chain from an old-key tip. There is no key-id /
# multi-key support yet -- a rotation today means re-baselining the chain
# (and the old segment stays verifiable only against the retired key). Treat
# SECRET_KEY rotation as an audit-chain migration event. Fail closed if it is
# unset (the migration does the same).
_SECRET = os.environ.get("SECRET_KEY", "").encode("utf-8")
if not _SECRET:
    raise RuntimeError(
        "SECRET_KEY must be set -- it keys the audit-log hash chain "
        "(app/audit.py). Running without it would write an unverifiable "
        "audit trail."
    )

# Serialises the log_access critical section (read tip -> compute -> append):
#   - `_chain_lock` (this) -- same-process threads;
#   - `_cross_process_chain_lock()` -- other processes, but only on the
#     SQLite path, because the demo runs gunicorn with 4 workers on ONE
#     SQLite file where `_load_state_for_update`'s `SELECT ... FOR UPDATE`
#     is a silent no-op. Mirrors `main.py::_schema_lock`.
#   - On MariaDB the FOR UPDATE on the AuditChainState singleton is the real
#     serialiser and the cross-process lock is a no-op.
#   - `uq_audit_logs_seq` is the last-resort backstop: a race that still
#     slips through (a caller that violates the "log last, after your own
#     commit" contract, so its stale snapshot misses a concurrent advance)
#     makes the losing INSERT raise -- a loud 500, never a silent fork.
_chain_lock = threading.RLock()
_IS_SQLITE = engine.url.get_backend_name() == "sqlite"


@contextlib.contextmanager
def _cross_process_chain_lock():
    if not _IS_SQLITE:
        yield
        return
    try:
        import fcntl
    except ImportError:  # Windows dev -- single process
        yield
        return
    db_path = engine.url.database or "clarion.db"
    lock_path = Path(db_path).resolve().parent / ".clarion_audit_chain.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def compute_row_hash(row: "models.AuditLog", prev_hash: str) -> str:
    """row_hash a persisted `AuditLog` *should* have, given `prev_hash`.
    Used by both the write path and `verify_chain`."""
    return hash_fields(
        key=_SECRET, prev_hash=prev_hash,
        id=row.id, seq=row.seq, patient_id=row.patient_id, actor=row.actor,
        actor_role=row.actor_role, actor_facility=row.actor_facility,
        action=row.action, fields_accessed=row.fields_accessed, detail=row.detail,
        timestamp=row.timestamp,
    )


# --------------------------------------------------------------------------
# write path
# --------------------------------------------------------------------------

def _load_state_for_update(db: Session) -> "models.AuditChainState":
    q = db.query(models.AuditChainState).filter(models.AuditChainState.id == 1)
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        q = q.with_for_update()
    state = q.first()
    if state is None:
        # No state row yet: a DB migrated to a rev before this table existed,
        # or a bare create_all() in a test. Seed genesis from whatever chain
        # tip already exists (there should be none, but be defensive).
        tip = (
            db.query(models.AuditLog)
            .order_by(models.AuditLog.seq.desc())
            .first()
        )
        state = models.AuditChainState(
            id=1,
            last_seq=tip.seq if tip is not None else 0,
            last_hash=tip.row_hash if tip is not None else GENESIS_HASH,
        )
        db.add(state)
        db.flush()
    return state


def log_access(
    db: Session,
    patient_id: Optional[str],
    actor: str,
    actor_role: Optional[str],
    action: str,
    fields: Optional[list] = None,
    detail: Optional[str] = None,
    actor_facility: Optional[str] = None,
):
    # CONTRACT: call this LAST, after you have committed your own domain
    # work. `log_access` issues `db.commit()` on the shared session -- so
    # anything still pending gets committed here too, and (P2.9) it takes a
    # brief X-lock on the AuditChainState singleton then inserts referencing
    # `patients`, so logging mid-transaction while you hold a `patients` row
    # lock risks a deadlock. Every current caller follows "mutate -> commit
    # -> log"; keep it that way.
    #
    # actor_facility is a snapshot of WHERE the actor was based AT THE TIME
    # of this access (see AuditLog's class docstring for why this is a
    # snapshot, unlike the actor's display name which is resolved live at
    # read time instead). Optional/defaulted to None so every pre-existing
    # call site keeps compiling unchanged -- callers that log a staff
    # action should pass current_user.facility; callers with no real
    # `User` row to snapshot from (the "system" actor, or an
    # "emergency_responder:<name>" actor from the unauthenticated
    # emergency-scan endpoints) should just leave this unset.
    now = datetime.now(timezone.utc)
    new_id = models.gen_id()

    # See the _chain_lock / _cross_process_chain_lock comments above for the
    # three serialisation layers. The caller's "commit before you log"
    # contract is load-bearing: it means `_load_state_for_update`'s SELECT
    # below is this transaction's first read, so (SQLite) it gets a fresh
    # snapshot that includes any concurrent advance the cross-process lock
    # just waited out.
    with _chain_lock, _cross_process_chain_lock():
        state = _load_state_for_update(db)
        seq = state.last_seq + 1
        prev_hash = state.last_hash
        row_hash = hash_fields(
            key=_SECRET, prev_hash=prev_hash,
            id=new_id, seq=seq, patient_id=patient_id, actor=actor,
            actor_role=actor_role, actor_facility=actor_facility, action=action,
            fields_accessed=fields, detail=detail, timestamp=now,
        )

        entry = models.AuditLog(
            id=new_id,
            patient_id=patient_id,
            actor=actor,
            actor_role=actor_role,
            action=action,
            fields_accessed=fields,
            detail=detail,
            actor_facility=actor_facility,
            timestamp=now,
            seq=seq,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
        db.add(entry)
        state.last_seq = seq
        state.last_hash = row_hash
        state.updated_at = now
        db.add(state)
        db.commit()


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

@dataclass
class ChainReport:
    """Result of walking the whole chain. `ok` is the headline; the rest is
    for the CLI / the admin endpoint (`asdict(report)` for the JSON shape)."""

    ok: bool = True
    total_rows: int = 0
    last_seq: int = 0
    last_hash: str = GENESIS_HASH
    first_break_seq: Optional[int] = None
    first_break_reason: Optional[str] = None
    state_matches_tip: bool = True
    sealed_days: int = 0
    seal_mismatches: list = field(default_factory=list)
    worm_checked: bool = False
    worm_mismatches: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def verify_chain(db: Session, *, check_seals: bool = True, check_worm: bool = False) -> ChainReport:
    """Walk `audit_logs` in `seq` order, recomputing every `row_hash` and
    checking linkage, gap-freeness, and (optionally) the daily seals. Stops
    reporting detail at the first break but still returns a populated
    report. Read-only.

    `check_worm=True` additionally re-reads every sealed day's digest from
    the object-store WORM bucket and compares it to the in-DB seal + the
    recomputed chain -- this is what catches a tail-truncation / full wipe
    that also rewrote `audit_chain_state` and the `audit_seals` rows (the
    in-DB structures are all writable by a DDL-capable account; the WORM
    copy is not). A DB-sealed day with no WORM copy, or a mismatch, fails.
    Only meaningful where WORM object storage is actually provisioned -- the
    nightly production cron should pass it; the bare local-dir demo will
    still pass because `seal_day` mirrors there too.
    """
    report = ChainReport()

    # Read the chain tip FIRST, then walk. A `log_access` that commits a new
    # row *during* the walk then advances the state row -- if we read state
    # last, its `last_seq` would be ahead of our `last_seq` and we'd cry
    # "rows deleted from the end" on a perfectly intact chain (the control
    # would then get muted by operators). Anchoring on the tip we saw at the
    # start means a concurrent append shows up as `last_seq > tip_seq` with
    # intact linkage -- which we tolerate -- while a genuine truncation shows
    # up as the tip row being missing / not matching.
    state = db.query(models.AuditChainState).filter(models.AuditChainState.id == 1).first()
    tip_seq = state.last_seq if state is not None else 0
    tip_hash = state.last_hash if state is not None else GENESIS_HASH
    tip_row_hash_seen: Optional[str] = None

    prev_hash = GENESIS_HASH
    expected_seq = 1
    q = (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.seq.asc())
        .yield_per(1000)
    )
    for row in q:
        report.total_rows += 1
        if row.seq == tip_seq:
            tip_row_hash_seen = row.row_hash

        if report.ok:
            if row.seq != expected_seq:
                report.ok = False
                report.first_break_seq = row.seq
                report.first_break_reason = (
                    f"sequence gap: expected {expected_seq}, found {row.seq}"
                )
            elif row.prev_hash != prev_hash:
                report.ok = False
                report.first_break_seq = row.seq
                report.first_break_reason = (
                    f"prev_hash mismatch at seq {row.seq}: "
                    f"row says {row.prev_hash[:12]}..., chain tip is {prev_hash[:12]}..."
                )
            else:
                recomputed = compute_row_hash(row, prev_hash)
                if not hmac.compare_digest(recomputed, row.row_hash or ""):
                    report.ok = False
                    report.first_break_seq = row.seq
                    report.first_break_reason = (
                        f"row_hash mismatch at seq {row.seq}: row content has been altered"
                    )

        prev_hash = row.row_hash or ""
        expected_seq = row.seq + 1
        report.last_seq = row.seq
        report.last_hash = prev_hash

    if state is not None:
        if tip_seq == 0:
            # genesis -- no rows should exist for the tip to point past
            report.state_matches_tip = report.last_seq == 0
        elif tip_row_hash_seen is None:
            # the row the tip points at is gone: tail truncation
            report.state_matches_tip = False
        else:
            report.state_matches_tip = hmac.compare_digest(tip_row_hash_seen, tip_hash)
        if not report.state_matches_tip:
            report.ok = False
            if report.first_break_reason is None:
                report.first_break_reason = (
                    f"chain-state tip (seq {tip_seq}, {tip_hash[:12]}...) is not "
                    f"backed by a matching audit row -- rows deleted from the end"
                )

    if check_seals:
        seals = db.query(models.AuditSeal).order_by(models.AuditSeal.seal_date.asc()).all()
        report.sealed_days = len(seals)
        report.worm_checked = check_worm
        for seal in seals:
            anchor = (
                db.query(models.AuditLog)
                .filter(models.AuditLog.seq == seal.to_seq)
                .first()
            )
            if anchor is None or not hmac.compare_digest(anchor.row_hash or "", seal.chain_hash):
                report.ok = False
                report.seal_mismatches.append(seal.seal_date)

            if check_worm:
                worm = _read_seal_from_worm(seal.seal_date)
                if (
                    worm is None
                    or str(worm.get("chain_hash")) != seal.chain_hash
                    or int(worm.get("to_seq", -1)) != seal.to_seq
                    or int(worm.get("row_count", -1)) != seal.row_count
                ):
                    report.ok = False
                    report.worm_mismatches.append(seal.seal_date)

    return report


# --------------------------------------------------------------------------
# daily WORM seal
# --------------------------------------------------------------------------

def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def seal_day(db: Session, d: Optional[date] = None, *, mirror_to_object_store: bool = True) -> Optional["models.AuditSeal"]:
    """Create (or verify) the WORM seal for one UTC day. Defaults to
    *yesterday* -- the most recent fully-elapsed day. Idempotent: a second
    call for an already-sealed day re-checks the digest and raises
    `RuntimeError` if it has changed (tamper), otherwise returns the
    existing row. Returns None if the day had no audit rows.
    """
    if d is None:
        d = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    day_str = d.isoformat()
    start, end = _day_bounds(d)

    rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.timestamp >= start, models.AuditLog.timestamp < end)
        .order_by(models.AuditLog.seq.asc())
        .all()
    )
    existing = (
        db.query(models.AuditSeal)
        .filter(models.AuditSeal.seal_date == day_str)
        .first()
    )
    if not rows:
        if existing is not None:
            raise RuntimeError(
                f"audit seal for {day_str} exists but that day now has no audit rows"
            )
        return None

    from_seq = rows[0].seq
    to_seq = rows[-1].seq
    chain_hash = rows[-1].row_hash
    row_count = len(rows)

    if existing is not None:
        if not hmac.compare_digest(existing.chain_hash, chain_hash or ""):
            raise RuntimeError(
                f"audit seal for {day_str} already recorded {existing.chain_hash[:12]}... "
                f"but the day's rows now hash to {(chain_hash or '')[:12]}... -- "
                f"audit_logs has been tampered with"
            )
        # Re-attempt the WORM mirror if a prior seal committed the DB row but
        # the mirror failed that night (transient object-store outage). Left
        # unretried, `verify_chain(check_worm=True)` flags this day forever.
        if mirror_to_object_store and existing.object_key is None:
            existing.object_key = _mirror_seal_to_worm(day_str, existing)
            if existing.object_key is not None:
                db.add(existing)
                db.commit()
        return existing

    seal = models.AuditSeal(
        seal_date=day_str,
        from_seq=from_seq,
        to_seq=to_seq,
        row_count=row_count,
        chain_hash=chain_hash,
    )
    if mirror_to_object_store:
        seal.object_key = _mirror_seal_to_worm(day_str, seal)
    db.add(seal)
    db.commit()
    return seal


def _mirror_seal_to_worm(day_str: str, seal: "models.AuditSeal") -> Optional[str]:
    """Best-effort: write the seal JSON to the object-store WORM bucket so
    the anchor survives even a full DB restore. Never fails the seal -- if
    object storage is a local dir (the demo) or unreachable, the DB row is
    still the primary record."""
    try:
        from . import storage
    except Exception:  # pragma: no cover - storage optional
        return None
    try:
        store = storage.get_object_store()
        payload = json.dumps(
            {
                "seal_date": day_str,
                "from_seq": seal.from_seq,
                "to_seq": seal.to_seq,
                "row_count": seal.row_count,
                "chain_hash": seal.chain_hash,
                "sealed_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        ).encode("utf-8")
        store.put(storage.BUCKET_REPORTS, _worm_seal_key(day_str), payload, mime="application/json")
        return _worm_seal_key(day_str)
    except Exception:  # pragma: no cover - best effort
        return None


def _worm_seal_key(day_str: str) -> str:
    return f"audit-seals/{day_str}.json"


def _read_seal_from_worm(day_str: str) -> Optional[dict]:
    """Read one day's seal digest back from the object-store WORM bucket.
    Returns None if storage is unreachable or the object is absent -- the
    caller (`verify_chain(check_worm=True)`) treats a None as a failure for
    a day the DB says is sealed."""
    try:
        from . import storage
        raw = storage.get_object_store().get(storage.BUCKET_REPORTS, _worm_seal_key(day_str))
        return json.loads(raw)
    except Exception:
        return None
