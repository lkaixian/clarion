"""P4.5: the access-anomaly scan over audit_logs.

Runs against an isolated throwaway migrated SQLite DB, same pattern as
test_data_quality.py's own rule/scan tests (`_throwaway_db`/`fresh_db`) --
`run_scan`'s rules deliberately query `audit_logs` GLOBALLY (a real scan
needs the true full-table view, with no facility/actor scoping), so sharing
the suite-wide conftest session DB would make every assertion here hostage
to whatever timestamp every OTHER test's audit rows happen to carry (and,
per `run_scan`'s wall-clock clamp on `latest`, to whatever the real time
happens to be when the suite runs).

Rows are inserted directly into audit_logs (bypassing app.audit.log_access,
which always timestamps "now" and has its own hash-chain locking neither of
these tests need) so each test can place rows at an exact, controlled
instant with no dependency on a real `models.User`/`models.Patient` beyond
a bare patient row (AuditLog.actor is a plain string, not an FK).
"""
import contextlib
import os
import pathlib
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, security_analytics


@contextlib.contextmanager
def _throwaway_db(target: str = "head"):
    from alembic import command
    from alembic.config import Config

    fd, path = tempfile.mkstemp(suffix=".db", prefix="clarion_sec_")
    os.close(fd)
    url = "sqlite:///" + path.replace("\\", "/")
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = None
    try:
        cfg = Config(str(pathlib.Path(models.__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(cfg, target)
        engine = create_engine(url)
        db = sessionmaker(bind=engine)()
        try:
            yield db
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
    with _throwaway_db("head") as db:
        yield db


def _actor() -> str:
    return f"actor-{uuid.uuid4().hex[:8]}"


def _patient(db) -> models.Patient:
    p = models.Patient(full_name="Sec Test Patient", date_of_birth="1990-01-01")
    db.add(p)
    db.commit()
    return p


def _row(db, *, actor, patient, timestamp, seq, actor_role="clinician", actor_facility=None):
    row = models.AuditLog(
        id=models.gen_id(), patient_id=patient.id, actor=actor, actor_role=actor_role,
        actor_facility=actor_facility, action="view_record", timestamp=timestamp,
        seq=seq, prev_hash="0" * 64, row_hash=models.gen_id(),
    )
    db.add(row)
    return row


def _now_bucket() -> datetime:
    return datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0, tzinfo=None)


def test_distinct_patient_fanout_flags_a_burst(fresh_db):
    actor = _actor()
    now = _now_bucket()

    for i in range(21):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    result = security_analytics.run_scan(fresh_db)
    assert result.rules_failed == []

    alert = fresh_db.query(models.SecurityAlert).filter(
        models.SecurityAlert.rule == "distinct_patient_fanout",
    ).one()
    assert alert.actor == actor
    assert alert.severity == "warning"  # 21 patients: >= 20 warning, < 50 error
    assert "21 distinct patients" in alert.detail


def test_distinct_patient_fanout_ignores_normal_volume(fresh_db):
    actor = _actor()
    now = _now_bucket()

    for i in range(5):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    assert fresh_db.query(models.SecurityAlert).count() == 0


def test_fanout_keys_on_actor_and_facility_separately(fresh_db):
    """An actor touching two different (snapshotted) facilities within the
    same hour must produce two alerts, one per facility -- not one alert
    with whichever facility happened to be read back last."""
    actor = _actor()
    now = _now_bucket()

    for i in range(21):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 1, actor_facility="F1")
    for i in range(21):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 100, actor_facility="F2")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    alerts = fresh_db.query(models.SecurityAlert).filter(
        models.SecurityAlert.rule == "distinct_patient_fanout",
    ).all()
    assert {a.actor_facility for a in alerts} == {"F1", "F2"}
    assert all(a.severity == "warning" for a in alerts)


def test_repeat_scan_bumps_times_seen_instead_of_duplicating(fresh_db):
    """Same underlying hour bucket across two scan runs must be ONE alert
    row with times_seen incrementing, not two rows -- the whole point of
    keying on (rule, actor, actor_facility, window_start)."""
    actor = _actor()
    now = _now_bucket()

    for i in range(25):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    result2 = security_analytics.run_scan(fresh_db)

    rows = fresh_db.query(models.SecurityAlert).all()
    assert len(rows) == 1
    assert rows[0].times_seen == 2
    assert result2.new_alerts == 0


def test_off_hours_access_is_info_below_the_fanout_escalation(fresh_db):
    actor = _actor()
    # 2026-09-15T02:00 MYT == 2026-09-14T18:00 UTC
    off_hours_utc = datetime(2026, 9, 14, 18, 0)

    _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=off_hours_utc, seq=1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)

    alert = fresh_db.query(models.SecurityAlert).filter(
        models.SecurityAlert.rule == "off_hours_access",
    ).one()
    assert alert.severity == "info"
    assert "2026-09-15" in alert.detail  # the MYT calendar date, not the UTC one


def test_off_hours_access_escalates_to_warning_with_several_patients(fresh_db):
    actor = _actor()
    off_hours_utc = datetime(2026, 9, 14, 18, 0)

    for i in range(6):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=off_hours_utc, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)

    alert = fresh_db.query(models.SecurityAlert).filter(
        models.SecurityAlert.rule == "off_hours_access",
    ).one()
    assert alert.severity == "warning"


def test_daytime_access_is_not_flagged_off_hours(fresh_db):
    actor = _actor()
    # 2026-09-15T10:00 MYT == 2026-09-15T02:00 UTC -- well inside clinic hours
    daytime_utc = datetime(2026, 9, 15, 2, 0)

    _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=daytime_utc, seq=1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    assert fresh_db.query(models.SecurityAlert).count() == 0


def test_system_and_emergency_pseudo_actors_are_excluded(fresh_db):
    now = _now_bucket()
    for i in range(25):
        _row(fresh_db, actor="system", patient=_patient(fresh_db), timestamp=now, seq=i + 1)
    for i in range(25):
        _row(fresh_db, actor="emergency_responder:front-desk", patient=_patient(fresh_db), timestamp=now, seq=i + 26)
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    assert fresh_db.query(models.SecurityAlert).count() == 0


def test_alert_auto_resolves_once_its_window_rotates_out_of_the_lookback(fresh_db):
    """`run_scan` anchors both the lookback window and the auto-resolve
    cutoff on `latest` (the most recent audit_logs row), clamped to never
    exceed wall-clock now -- so a genuinely later row (not a simulated
    clock) is what rotates the old bucket out, exactly like a real cron
    catching up after a gap. `t0` is a fixed, comfortably-past date so the
    wall-clock clamp never interferes (see security_analytics.run_scan)."""
    actor = _actor()
    t0 = datetime(2026, 1, 1, 10, 30)

    for i in range(25):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=t0, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    alert = fresh_db.query(models.SecurityAlert).filter(
        models.SecurityAlert.rule == "distinct_patient_fanout",
    ).one()
    assert alert.resolved is False

    # 25h later -- past the 24h lookback -- pushes `latest` forward so the
    # t0 bucket falls out of both rules' window.
    _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=t0 + timedelta(hours=25),
         seq=26, actor_facility="F1")
    fresh_db.commit()

    security_analytics.run_scan(fresh_db)
    fresh_db.refresh(alert)
    assert alert.resolved is True
    assert alert.resolved_by == "system"


def test_a_throwing_rule_does_not_abort_the_whole_scan(fresh_db, monkeypatch):
    actor = _actor()
    now = _now_bucket()
    for i in range(21):
        _row(fresh_db, actor=actor, patient=_patient(fresh_db), timestamp=now, seq=i + 1, actor_facility="F1")
    fresh_db.commit()

    def _boom(rows, latest):
        raise RuntimeError("rule blew up")
        yield  # pragma: no cover

    boom = security_analytics.Rule("boom", _boom)
    monkeypatch.setattr(security_analytics, "RULES", security_analytics.RULES + [boom])

    result = security_analytics.run_scan(fresh_db)
    assert result.rules_failed and result.rules_failed[0][0] == "boom"
    assert result.new_alerts == 1  # the good rule still ran and committed
    assert fresh_db.query(models.SecurityAlert).filter_by(rule="distinct_patient_fanout").count() == 1
