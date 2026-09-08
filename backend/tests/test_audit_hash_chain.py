"""P2.9 -- audit_logs tamper-evident hash chain, append-only triggers, seals.

The non-destructive checks run against the shared session-scoped DB and only
assert properties that hold regardless of what else has been logged (chain
intact, gap-free, each row links to its predecessor, tip matches).

The tamper / seal tests need their own throwaway DB: proving *detection*
means simulating an out-of-band edit (raw datadir access, a doctored
backup) -- which, by design, the app cannot do through SQL because of the
append-only triggers -- so they build a fresh migrated SQLite file, drop
the triggers there, and mutate freely without touching the shared chain.
"""
import contextlib
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import audit, models


# --------------------------------------------------------------------------
# shared-DB, non-destructive
# --------------------------------------------------------------------------

def _log_a_few(db, n=3):
    for i in range(n):
        audit.log_access(db, None, "system", "system", f"test_chain_event_{i}")


def test_new_rows_extend_an_intact_gap_free_chain(db_session):
    _log_a_few(db_session, 5)
    report = audit.verify_chain(db_session)
    assert report.ok, report.first_break_reason
    assert report.state_matches_tip
    assert report.total_rows == report.last_seq  # gap-free: N rows => max seq N

    seqs = [s for (s,) in db_session.query(models.AuditLog.seq).order_by(models.AuditLog.seq).all()]
    assert seqs == list(range(1, len(seqs) + 1))


def test_each_row_links_to_its_predecessor(db_session):
    _log_a_few(db_session, 3)
    rows = db_session.query(models.AuditLog).order_by(models.AuditLog.seq).all()
    assert rows[0].prev_hash == audit.GENESIS_HASH
    for earlier, later in zip(rows, rows[1:]):
        assert later.prev_hash == earlier.row_hash


def test_append_only_trigger_blocks_update(db_session):
    _log_a_few(db_session, 1)
    row = db_session.query(models.AuditLog).order_by(models.AuditLog.seq.desc()).first()
    with pytest.raises(Exception):
        db_session.execute(
            text("UPDATE audit_logs SET detail = 'tampered' WHERE id = :id"), {"id": row.id}
        )
        db_session.commit()
    db_session.rollback()


def test_append_only_trigger_blocks_delete(db_session):
    _log_a_few(db_session, 1)
    row = db_session.query(models.AuditLog).order_by(models.AuditLog.seq.desc()).first()
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": row.id})
        db_session.commit()
    db_session.rollback()


def test_chain_status_endpoint_admin_only(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility="Hospital Sejahtera")
    clinician = make_user(role="clinician", facility="Hospital Sejahtera")

    ok = test_client.get("/admin/audit/chain-status", headers=auth_headers(admin))
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert "last_hash" in body and "total_rows" in body

    denied = test_client.get("/admin/audit/chain-status", headers=auth_headers(clinician))
    assert denied.status_code == 403


# --------------------------------------------------------------------------
# isolated throwaway DB, destructive
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _throwaway_db(target: str = "head"):
    """A fresh SQLite file migrated to `target`, + a session. Independent of
    the shared conftest DB (alembic/env.py reads DATABASE_URL at run time and
    builds its own engine, so this never touches it)."""
    from alembic import command
    from alembic.config import Config

    fd, path = tempfile.mkstemp(suffix=".db", prefix="clarion_chain_")
    os.close(fd)
    url = "sqlite:///" + path.replace("\\", "/")
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = None
    try:
        cfg = Config(str(pathlib.Path(audit.__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(cfg, target)
        engine = create_engine(url)
        db = sessionmaker(bind=engine)()
        try:
            yield db, url, cfg
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if prev is not None:
            os.environ["DATABASE_URL"] = prev
        else:
            os.environ.pop("DATABASE_URL", None)
        with contextlib.suppress(OSError):
            os.remove(path)


@pytest.fixture
def fresh_db():
    with _throwaway_db("head") as (db, _url, _cfg):
        yield db


def _drop_triggers(db):
    db.execute(text("DROP TRIGGER IF EXISTS trg_audit_logs_no_update"))
    db.execute(text("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete"))
    db.commit()


def test_verify_detects_an_altered_row(fresh_db):
    _log_a_few(fresh_db, 4)
    victim = fresh_db.query(models.AuditLog).filter(models.AuditLog.seq == 2).first()

    assert audit.verify_chain(fresh_db).ok
    _drop_triggers(fresh_db)
    fresh_db.execute(
        text("UPDATE audit_logs SET detail = 'silently changed' WHERE id = :id"),
        {"id": victim.id},
    )
    fresh_db.commit()

    report = audit.verify_chain(fresh_db)
    assert not report.ok
    assert report.first_break_seq == 2
    assert "row_hash mismatch" in report.first_break_reason


def test_verify_detects_a_deleted_tail_row(fresh_db):
    _log_a_few(fresh_db, 3)
    _drop_triggers(fresh_db)
    fresh_db.execute(text("DELETE FROM audit_logs WHERE seq = 3"))
    fresh_db.commit()

    report = audit.verify_chain(fresh_db)
    assert not report.ok
    assert not report.state_matches_tip


def _row_day(db):
    """UTC date of an existing audit row -- derive the seal day from real
    data, never `datetime.now()`, so a run straddling 00:00 UTC can't put
    the rows on one day and the seal target on the next."""
    r = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).first()
    ts = r.timestamp
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.date()


def test_verify_detects_a_gap_from_a_deleted_middle_row(fresh_db):
    _log_a_few(fresh_db, 4)
    _drop_triggers(fresh_db)
    fresh_db.execute(text("DELETE FROM audit_logs WHERE seq = 2"))  # leaves 1, 3, 4
    fresh_db.commit()

    report = audit.verify_chain(fresh_db)
    assert not report.ok
    assert report.first_break_seq == 3
    assert "sequence gap" in report.first_break_reason


def test_verify_detects_a_mid_chain_forged_row(fresh_db):
    _log_a_few(fresh_db, 3)
    _drop_triggers(fresh_db)
    fresh_db.execute(text("DELETE FROM audit_logs WHERE seq = 2"))
    fresh_db.execute(
        text(
            "INSERT INTO audit_logs (id, actor, action, timestamp, seq, prev_hash, row_hash) "
            "VALUES ('forged', 'attacker', 'view_record', :ts, 2, :ph, :rh)"
        ),
        {"ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" "),
         "ph": "0" * 64, "rh": "f" * 64},
    )
    fresh_db.commit()

    report = audit.verify_chain(fresh_db)
    assert not report.ok
    assert report.first_break_seq == 2
    assert "prev_hash mismatch" in report.first_break_reason


def test_seal_day_anchors_the_day_and_is_idempotent(fresh_db):
    _log_a_few(fresh_db, 3)
    day = _row_day(fresh_db)

    seal = audit.seal_day(fresh_db, day, mirror_to_object_store=False)
    assert seal is not None
    assert seal.row_count == 3
    assert seal.from_seq == 1 and seal.to_seq == 3

    again = audit.seal_day(fresh_db, day, mirror_to_object_store=False)
    assert again.id == seal.id


def test_seal_day_re_seal_after_tamper_raises(fresh_db):
    _log_a_few(fresh_db, 2)
    day = _row_day(fresh_db)
    audit.seal_day(fresh_db, day, mirror_to_object_store=False)

    _drop_triggers(fresh_db)
    fresh_db.execute(text("UPDATE audit_logs SET row_hash = :h WHERE seq = 2"), {"h": "0" * 64})
    fresh_db.commit()

    with pytest.raises(RuntimeError):
        audit.seal_day(fresh_db, day, mirror_to_object_store=False)


def test_empty_chain_verifies_ok(fresh_db):
    report = audit.verify_chain(fresh_db)
    assert report.ok
    assert report.total_rows == 0
    assert report.last_hash == audit.GENESIS_HASH


def test_verify_tolerates_a_concurrent_append_past_the_tip_it_read(fresh_db):
    # verify_chain reads the chain-state tip FIRST; a log_access that commits
    # AFTER that read must not be misreported as "rows deleted from the end".
    # Simulate by rewinding the state row to an earlier tip while the extra
    # rows stay in place.
    _log_a_few(fresh_db, 4)
    row3 = fresh_db.query(models.AuditLog).filter(models.AuditLog.seq == 3).first()
    fresh_db.execute(
        text("UPDATE audit_chain_state SET last_seq = 3, last_hash = :h WHERE id = 1"),
        {"h": row3.row_hash},
    )
    fresh_db.commit()

    report = audit.verify_chain(fresh_db)
    assert report.ok, report.first_break_reason
    assert report.state_matches_tip
    assert report.last_seq == 4


def test_worm_seal_readback(fresh_db):
    _log_a_few(fresh_db, 2)
    day = _row_day(fresh_db)
    seal = audit.seal_day(fresh_db, day, mirror_to_object_store=True)
    assert seal.object_key is not None  # mirror actually wrote

    report = audit.verify_chain(fresh_db, check_worm=True)
    assert report.worm_checked
    assert report.worm_mismatches == []
    assert report.ok, report.first_break_reason

    # tampering the DB seal digest breaks BOTH the in-DB anchor cross-check
    # and the WORM cross-check
    fresh_db.execute(text("UPDATE audit_seals SET chain_hash = :h WHERE seal_date = :d"),
                     {"h": "9" * 64, "d": day.isoformat()})
    fresh_db.commit()
    report = audit.verify_chain(fresh_db, check_worm=True)
    assert not report.ok
    assert day.isoformat() in report.worm_mismatches
    assert day.isoformat() in report.seal_mismatches


# --------------------------------------------------------------------------
# migration back-fill (the lockstep between app/audit.py and the migration)
# --------------------------------------------------------------------------

def test_migration_backfills_pre_p29_rows_into_a_verifiable_chain():
    """The migration's raw-SQL back-fill must produce byte-identical hashes to
    what `app/audit.py` writes -- otherwise every pre-P2.9 row fails
    verification. `fresh_db` always starts empty, so this is the only test
    that exercises the back-fill against real rows + then appends live."""
    from alembic import command

    with _throwaway_db("f3a9d21c5e88") as (db, url, cfg):  # one rev before P2.9
        # pre-P2.9 audit_logs has no seq/prev_hash/row_hash columns
        for i in range(5):
            db.execute(
                text(
                    "INSERT INTO audit_logs (id, actor, actor_role, action, timestamp, detail) "
                    "VALUES (:id, :actor, 'system', :action, :ts, :detail)"
                ),
                {
                    "id": f"pre-{i}", "actor": "system", "action": f"legacy_event_{i}",
                    "ts": datetime(2026, 9, 1, 8, i, 30, 123456 + i).isoformat(sep=" "),
                    "detail": None if i % 2 else f"detail {i}",
                },
            )
        db.commit()

        command.upgrade(cfg, "b2d7e4a9c1f6")
        db.expire_all()

        report = audit.verify_chain(db, check_seals=False)
        assert report.ok, report.first_break_reason
        assert report.total_rows == 5
        assert report.last_seq == 5

        # and a live append continues the same chain
        audit.log_access(db, None, "system", "system", "post_migration_event")
        report = audit.verify_chain(db, check_seals=False)
        assert report.ok, report.first_break_reason
        assert report.last_seq == 6


def test_migration_backfill_is_restartable():
    """Re-running P2.9's `upgrade()` against an already-migrated DB must be a
    no-op, not a crash on "column/table already exists" -- this is what makes
    it safe to just retry after a mid-back-fill failure on MariaDB."""
    import sqlalchemy as sa
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    with _throwaway_db("head") as (db, url, cfg):
        _log_a_few(db, 3)
        upgrade = ScriptDirectory.from_config(cfg).get_revision("b2d7e4a9c1f6").module.upgrade

        with sa.create_engine(url).begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                upgrade()  # second run -- must not raise

        db.expire_all()
        assert audit.verify_chain(db, check_seals=False).ok


# --------------------------------------------------------------------------
# CLI smoke tests (cron / CI entry points -- roadmap P2.11)
# --------------------------------------------------------------------------

def _run_cli(args, url):
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env.setdefault("SECRET_KEY", "test-only-secret-key-not-for-any-real-deployment")
    env.setdefault("OTP_HMAC_KEY", "test-only-otp-hmac-key")
    return subprocess.run(
        [sys.executable, "-m"] + args,
        cwd=str(pathlib.Path(audit.__file__).resolve().parent.parent),
        env=env, capture_output=True, text=True,
    )


def test_verify_cli_exit_codes():
    with _throwaway_db("head") as (db, url, _cfg):
        _log_a_few(db, 3)

        ok = _run_cli(["db.verify_audit_chain"], url)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "OK" in ok.stdout

        _drop_triggers(db)
        db.execute(text("DELETE FROM audit_logs WHERE seq = 2"))
        db.commit()
        broken = _run_cli(["db.verify_audit_chain"], url)
        assert broken.returncode == 1, broken.stdout + broken.stderr

        bad_flags = _run_cli(["db.verify_audit_chain", "--worm", "--no-seals"], url)
        assert bad_flags.returncode == 2


def test_seal_cli_smoke():
    with _throwaway_db("head") as (db, url, _cfg):
        _log_a_few(db, 2)
        day = _row_day(db)

        out = _run_cli(["db.seal_audit_day", "--date", day.isoformat(), "--no-mirror"], url)
        assert out.returncode == 0, out.stdout + out.stderr
        assert day.isoformat() in out.stdout

        conflict = _run_cli(["db.seal_audit_day", "--date", day.isoformat(), "--backfill"], url)
        assert conflict.returncode == 2
