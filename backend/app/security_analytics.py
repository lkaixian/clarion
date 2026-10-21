"""Access-anomaly scan over the audit hash-chain (roadmap P4.5, tender
 "intelligent anomaly detection... no manual rule config" +
 "AI-driven audit-trail intelligence").

Same shape as ``app/data_quality.py``'s ``run_scan`` (a registry of
independent rules, each yielding ``Finding``s, UPSERTed into a table keyed
so a repeat sighting just bumps ``times_seen``/``last_seen_at``) -- see that
module's docstring for the pattern this mirrors. The differences:

- Rules here read ``audit_logs``, not clinical rows, and key on
  ``(actor, actor_facility, time bucket)`` instead of
  ``(entity_type, entity_id)`` -- ``actor_facility`` is part of the key, not
  just informational, because it is a per-row *snapshot* on ``AuditLog``
  (see that model's docstring): the same actor can legitimately show up
  with different facilities across rows (a transfer, multi-site staff), so
  an alert keyed on actor alone would pick one of those facilities
  arbitrarily depending on row order -- exactly the wrong facility's admin
  could then see it (or the right one never would). Keying on the pair
  means an actor touching two facilities in one window produces two
  alerts, one per facility, which is the correct shape for a
  facility-scoped admin's inbox.
- There is deliberately NO env-var rule-disable knob: explicitly
  asks for "no manual rule config", the opposite of the tender's wording that
  justified ``DATA_QUALITY_DISABLED_RULES``. Every threshold below is a
  hardcoded constant, same idiom as the existing M7c NFC-scan-anomaly check
  (">= 8 scans/hour") -- not a per-deployment setting.
- ``run_scan`` fetches ``audit_logs`` once and computes ``latest`` (the most
  recent row's own timestamp -- see below) once, then hands both to every
  rule, rather than each rule re-querying independently.
- ``latest`` is clamped to wall-clock ``now`` before it drives either the
  lookback window or the auto-resolve cutoff. Without the clamp, one
  badly-clock-skewed or bad-seed row with a future timestamp would push
  every other open alert's ``window_end`` outside the (falsely advanced)
  lookback and silently auto-resolve the entire open list in one scan.

Two rules ship this pass, matching the tender's own examples most literally:

- ``distinct_patient_fanout`` -- an actor touching an unusually large number
  of DISTINCT patients within one calendar hour (the clearest
  exfiltration-shaped signal available from audit_logs: routine clinical
  care is one-patient-at-a-time, browsing dozens of records in an hour is
  not).
- ``off_hours_access`` -- an actor touching patient records during
  Malaysia's quiet hours (00:00-05:00 MYT, UTC+8, no DST). NOT treated as
  automatically suspicious (CLARION is an emergency-first clinic; genuine
  after-hours care is expected) -- severity stays ``info`` unless the same
  actor also fanned out across several patients that night.

Deliberately NOT attempted this pass: a "new facility for this actor"
rule (flagging the first time an actor's audit rows are attributed to a
facility they've never used before) was drafted and cut -- keying novelty
off "has a SecurityAlert row for this (actor, facility) pair been created
before" floods a freshly-seeded or freshly-migrated database with a false
positive for every existing combination on the very first scan (everything
looks "new" once). A correct version needs an explicit backfill/baseline
step this pass didn't have room for; the ``RULES`` registry below is
designed so adding it later is a one-line addition, same as
``data_quality.py``'s.

Both rules load ``audit_logs`` rows for a bounded lookback window into
Python and bucket them there (not a SQL date-truncation function), because
that stays portable across SQLite and MariaDB without dialect-specific SQL.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterator, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models

_log = logging.getLogger("clarion.security_analytics")

# How far back each rule looks when re-deriving its buckets on every scan --
# generous enough that a delayed/missed scan still catches the prior
# window(s), cheap enough to load into memory (audit_logs is timestamp-
# indexed already).
_LOOKBACK = timedelta(hours=24)

# Pseudo-actors that are not a real staff account -- excluded from both
# rules (see models.AuditLog's class docstring for the actor string shapes).
_EXCLUDED_ACTORS = {"system"}
_EXCLUDED_ACTOR_PREFIXES = ("emergency_", "public_unverified:")

# Malaysia has no DST -- a fixed UTC+8 offset is exact, not an approximation.
_MYT_OFFSET = timedelta(hours=8)
_QUIET_HOURS_MYT = range(0, 5)  # 00:00-04:59 MYT

_FANOUT_WARNING_THRESHOLD = 20  # distinct patients/hour by one actor
_FANOUT_ERROR_THRESHOLD = 50
_OFF_HOURS_WARNING_PATIENT_COUNT = 5  # distinct patients that night to escalate info -> warning


@dataclass
class Finding:
    rule: str
    category: str          # patient_fanout | unusual_hour
    severity: str           # info | warning | error
    actor: str
    actor_role: Optional[str]
    actor_facility: Optional[str]
    window_start: datetime
    window_end: datetime
    detail: str


AuditRow = tuple  # (actor, actor_role, actor_facility, patient_id, timestamp)


@dataclass
class Rule:
    key: str
    fn: Callable[[list, datetime], Iterator[Finding]]


@dataclass
class ScanResult:
    run_at: datetime
    rules_run: int
    rules_failed: list      # [(rule_key, exception-repr)]
    findings: int
    new_alerts: int
    still_open: int
    auto_resolved: int

    def as_dict(self) -> dict:
        return {**asdict(self), "run_at": self.run_at.isoformat()}


def _is_real_staff_actor(actor: str) -> bool:
    return actor not in _EXCLUDED_ACTORS and not actor.startswith(_EXCLUDED_ACTOR_PREFIXES)


def _recent_patient_touching_rows(db: Session, since: datetime) -> list[AuditRow]:
    """Every audit_logs row at or after `since` that touched a specific
    patient -- fetched once per scan (by `run_scan`) and handed to every
    rule, rather than each rule re-querying independently."""
    return (
        db.query(
            models.AuditLog.actor, models.AuditLog.actor_role,
            models.AuditLog.actor_facility, models.AuditLog.patient_id,
            models.AuditLog.timestamp,
        )
        .filter(
            models.AuditLog.timestamp >= since,
            models.AuditLog.patient_id.isnot(None),
        )
        .all()
    )


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _distinct_patient_fanout(rows: list[AuditRow], latest: datetime) -> Iterator[Finding]:
    # ponytail: tumbling (not sliding) hourly buckets -- 19 patients at
    # 10:50-10:59 plus 19 more at 11:00-11:09 (38 in ~20 minutes, well past
    # the bar below) never trips either bucket. Upgrade path is a rolling
    # window keyed off each row's own timestamp instead of a truncated
    # hour; not attempted this pass -- meaningfully more bookkeeping for a
    # boundary case, not a correctness bug in the common case.
    buckets: dict[tuple[str, Optional[str], datetime], dict] = {}
    for actor, actor_role, actor_facility, patient_id, ts in rows:
        if not _is_real_staff_actor(actor):
            continue
        bucket_start = ts.replace(minute=0, second=0, microsecond=0)
        entry = buckets.setdefault(
            (actor, actor_facility, bucket_start),
            {"actor_role": actor_role, "patients": set()},
        )
        entry["patients"].add(patient_id)
        entry["actor_role"] = actor_role or entry["actor_role"]

    for (actor, actor_facility, bucket_start), entry in buckets.items():
        n = len(entry["patients"])
        if n < _FANOUT_WARNING_THRESHOLD:
            continue
        severity = "error" if n >= _FANOUT_ERROR_THRESHOLD else "warning"
        yield Finding(
            "distinct_patient_fanout", "patient_fanout", severity,
            actor, entry["actor_role"], actor_facility,
            bucket_start, bucket_start + timedelta(hours=1),
            f"{n} distinct patients accessed within a single hour",
        )


def _myt_midnight_utc(night: date) -> datetime:
    """The UTC instant of 00:00 MYT on `night` -- a fixed calculation
    independent of which rows exist, so it's a stable dedup key across
    repeated scans (unlike, say, "the earliest row's own timestamp", which
    would drift as more of the night's rows arrive).

    Deliberately naive (no tzinfo), matching every timestamp read back from
    audit_logs (see `_off_hours_access`'s comment on `ts`) -- this value is
    stored into SecurityAlert.window_start and compared against those
    DB-round-tripped values (the (rule, actor, actor_facility, window_start)
    dedup key in `run_scan`), so it has to be naive-UTC too or an
    aware/naive pair that represents the identical instant would still
    compare as a different, duplicate dict key."""
    return datetime.combine(night, time(0, 0)) - _MYT_OFFSET


def _off_hours_access(rows: list[AuditRow], latest: datetime) -> Iterator[Finding]:
    buckets: dict[tuple[str, Optional[str], date], dict] = {}
    for actor, actor_role, actor_facility, patient_id, ts in rows:
        if not _is_real_staff_actor(actor):
            continue
        # `ts` comes back from the DB as naive-UTC (SQLAlchemy's
        # DateTime(timezone=True) does not round-trip tzinfo through
        # SQLite or MariaDB/pymysql -- same caveat as everywhere else in
        # this codebase that reads a TZDateTime column back). Adding the
        # fixed MYT offset and reading .hour/.date() off the (still naive)
        # result is a deliberate shortcut for a no-DST timezone.
        myt = ts + _MYT_OFFSET
        if myt.hour not in _QUIET_HOURS_MYT:
            continue
        entry = buckets.setdefault(
            (actor, actor_facility, myt.date()),
            {"actor_role": actor_role, "patients": set()},
        )
        entry["patients"].add(patient_id)
        entry["actor_role"] = actor_role or entry["actor_role"]

    for (actor, actor_facility, night), entry in buckets.items():
        n = len(entry["patients"])
        severity = "warning" if n >= _OFF_HOURS_WARNING_PATIENT_COUNT else "info"
        window_start = _myt_midnight_utc(night)
        yield Finding(
            "off_hours_access", "unusual_hour", severity,
            actor, entry["actor_role"], actor_facility,
            window_start, window_start + timedelta(hours=5),
            f"{n} distinct patient(s) accessed during quiet hours "
            f"(00:00-05:00 MYT) on {night.isoformat()}",
        )


RULES: list[Rule] = [
    Rule("distinct_patient_fanout", _distinct_patient_fanout),
    Rule("off_hours_access", _off_hours_access),
]


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def run_scan(db: Session, *, _retry: bool = True) -> ScanResult:
    now = datetime.now(timezone.utc)
    # Anchored on the data's own most recent row, not wall-clock `now` --
    # a demo/test DB with no fresh activity between scans should not have
    # its alerts silently age out just because real time passed with no new
    # audit rows. Clamped to `now` (never later) so one row with a
    # clock-skewed or bad-seed future timestamp can't push the lookback
    # window forward and make every other open alert look stale enough to
    # auto-resolve in the same pass.
    latest = db.query(func.max(models.AuditLog.timestamp)).scalar()
    if latest is not None:
        # `latest` round-trips as naive-UTC (see _myt_midnight_utc's
        # docstring) -- strip `now`'s tzinfo too so this compares like with
        # like, matching every other naive-UTC comparison in this module.
        latest = min(latest, now.replace(tzinfo=None))
    rows = _recent_patient_touching_rows(db, latest - _LOOKBACK) if latest is not None else []

    by_key = {
        (a.rule, a.actor, a.actor_facility, a.window_start): a
        for a in db.query(models.SecurityAlert).all()
    }

    seen_keys: set = set()
    findings = 0
    new_alerts = 0
    rules_run = 0
    rules_failed: list = []

    for rule in RULES:
        try:
            rule_findings = list(rule.fn(rows, latest))
        except Exception as exc:  # noqa: BLE001 - one bad rule must not lose the whole scan
            _log.exception("security-analytics rule %s failed", rule.key)
            rules_failed.append((rule.key, repr(exc)))
            continue
        rules_run += 1
        for f in rule_findings:
            findings += 1
            key = (f.rule, f.actor, f.actor_facility, f.window_start)
            seen_keys.add(key)
            existing = by_key.get(key)
            if existing is None:
                row = models.SecurityAlert(
                    rule=f.rule, category=f.category, severity=f.severity,
                    actor=f.actor, actor_role=f.actor_role, actor_facility=f.actor_facility,
                    window_start=f.window_start, window_end=f.window_end, detail=f.detail,
                    first_seen_at=now, last_seen_at=now, times_seen=1,
                )
                db.add(row)
                by_key[key] = row
                new_alerts += 1
            else:
                existing.last_seen_at = now
                existing.times_seen = (existing.times_seen or 0) + 1
                existing.detail = f.detail
                existing.severity = f.severity
                existing.window_end = f.window_end
                existing.actor_role = f.actor_role or existing.actor_role

    # Auto-resolve open, system-owned alerts whose bucket did not recur this
    # scan (its lookback window no longer covers that bucket, or the actor's
    # behaviour in it stopped qualifying) -- same "stopped firing -> auto-
    # resolve" contract as data_quality.py, except there is no
    # "rule was skipped" case to protect against here (every rule always
    # runs, per the tender's "no manual rule config").
    auto_resolved = 0
    if latest is not None:
        for a in by_key.values():
            if a.resolved or (a.rule, a.actor, a.actor_facility, a.window_start) in seen_keys:
                continue
            if a.window_end < (latest - _LOOKBACK):
                # only auto-resolve buckets old enough to have fully rotated
                # out of every rule's lookback window -- otherwise a bucket
                # a rule simply hasn't reached yet in its own iteration would
                # look "stopped firing" and get closed prematurely.
                a.resolved = True
                a.resolved_by = "system"
                a.resolved_at = now
                auto_resolved += 1

    try:
        db.commit()
    except IntegrityError:
        # A concurrent scan (cron vs. the admin "scan now" button) inserted
        # one of the same (rule, actor, actor_facility, window_start) keys
        # first -- retry once, same as data_quality.py's run_scan. (A row
        # with actor_facility=None is the one case this backstop can't
        # fully cover -- SQL NULL isn't equal to itself in a UNIQUE
        # constraint, so two concurrent scans could each insert one; the
        # Python-level `by_key` check above is what actually prevents
        # duplicates in the normal single-scan-at-a-time case, this is only
        # a last-resort race guard.)
        db.rollback()
        if _retry:
            return run_scan(db, _retry=False)
        raise

    still_open = (
        db.query(models.SecurityAlert)
        .filter(models.SecurityAlert.resolved.is_(False))
        .count()
    )
    return ScanResult(
        run_at=now, rules_run=rules_run, rules_failed=rules_failed,
        findings=findings, new_alerts=new_alerts,
        still_open=still_open, auto_resolved=auto_resolved,
    )
