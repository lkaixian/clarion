"""Retention-schedule scan (roadmap P2.10, the tender / PDPA s.10).

FLAG ONLY. Malaysian law has no right to erasure and clinical records must
be kept per Act 586 / MMC (7 yr adult, ~25 paediatric, 21 obstetric,
indefinite medico-legal -- see healthcare/Malaysia Health Regulation.md).
So this never deletes: it walks the record tables, computes each record's
last-activity date, and for anything past its category's `retain_years`
window it UPSERTs a `RetentionReviewItem` for an admin to review. Actual
disposal is a DBA partition-drop (P2.9), dispositioned back here.

`run_retention_scan(db)` is invoked by `db/retention_scan.py` (cron) and
`POST /admin/retention/scan`.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import models

# Malaysian defaults, seeded into retention_policies by seed.py; admin-editable.
DEFAULT_RETENTION_POLICIES = [
    ("patient", 7, "Act 586 reg + Limitation Act 1953 (6-yr civil claim); MMC 002/2006"),
    ("encounter", 7, "Act 586 / KKM JPR Perubatan -- 7 yr from last contact"),
    ("document", 7, "Act 586 -- clinical documents kept with the record"),
    ("condition", 7, "kept with the encounter record"),
    ("medication", 7, "kept with the encounter record"),
    ("allergy", 7, "kept with the encounter record"),
    ("paediatric", 25, "retain until age of majority (18) + 7 -- age-based, needs manual review"),
    ("obstetric", 21, "KKM JPR Perubatan -- 21 yr from delivery"),
    ("medicolegal", None, "indefinite -- forensic / litigation / coroner's case"),
    ("audit", 7, "audit_logs -- disposal is a MariaDB partition drop (P2.9), not a DELETE"),
]

# The scan walks `patient` / `encounter` / `document` (the categories with a
# real last-activity timestamp). The age-based / special categories
# (`paediatric`, `obstetric`, `medicolegal`) are config-only for now -- they
# need a per-record classifier a future pass adds.
#
# NOTE (security review 2026-09-08): `disposed=True` currently just suppresses
# re-flagging on the operator's say-so -- there is no check that the DBA
# partition-drop actually happened. A follow-up should periodically
# re-verify disposed items are truly gone.


@dataclass
class RetentionScanResult:
    run_at: datetime
    scanned: int
    flagged_new: int
    flagged_total: int

    def as_dict(self) -> dict:
        return {
            "run_at": self.run_at.isoformat(),
            "scanned": self.scanned,
            "flagged_new": self.flagged_new,
            "flagged_total": self.flagged_total,
        }


def _policy_years(db: Session) -> dict:
    rows = {p.category: p.retain_years for p in db.query(models.RetentionPolicy).all()}
    # fall back to the defaults for any category not yet in the table
    for cat, years, _ in DEFAULT_RETENTION_POLICIES:
        rows.setdefault(cat, years)
    return rows


def _aware(dt) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_retention_scan(db: Session) -> RetentionScanResult:
    now = datetime.now(timezone.utc)
    years = _policy_years(db)

    existing = {
        (r.entity_type, r.entity_id): r
        for r in db.query(models.RetentionReviewItem).all()
    }
    scanned = 0
    flagged_new = 0

    def flag(entity_type, entity_id, patient_id, category, last_activity):
        nonlocal flagged_new
        y = years.get(category)
        if y is None or last_activity is None:
            return
        retain_until = _aware(last_activity) + timedelta(days=round(365.2425 * y))  # ~year, leap-adjusted; flag-only so approximation is fine
        if retain_until >= now:
            return
        row = existing.get((entity_type, entity_id))
        if row is None:
            db.add(models.RetentionReviewItem(
                entity_type=entity_type, entity_id=entity_id, patient_id=patient_id,
                category=category, last_activity_at=_aware(last_activity),
                retain_until=retain_until, first_flagged_at=now, last_flagged_at=now,
            ))
            flagged_new += 1
        elif not row.disposed:
            row.last_flagged_at = now
            row.retain_until = retain_until
            row.last_activity_at = _aware(last_activity)

    # --- encounters: last_activity = started_at ---------------------------
    for e in db.query(models.Encounter).all():
        scanned += 1
        flag("encounter", e.id, e.patient_id, "encounter", e.started_at)

    # --- documents: last_activity = uploaded_at ------------------------
    for d in db.query(models.ClinicalDocument).all():
        scanned += 1
        flag("document", d.id, d.patient_id, "document", d.uploaded_at)

    # --- patients: last_activity = newest of (created_at, last encounter) --
    last_enc = {}
    for e in db.query(models.Encounter.patient_id, models.Encounter.started_at).all():
        pid, ts = e
        ts = _aware(ts)
        if ts and (pid not in last_enc or ts > last_enc[pid]):
            last_enc[pid] = ts
    for p in db.query(models.Patient).all():
        scanned += 1
        la = max(filter(None, [_aware(p.created_at), last_enc.get(p.id)]), default=None)
        flag("patient", p.id, p.id, "patient", la)

    db.commit()
    flagged_total = (
        db.query(models.RetentionReviewItem)
        .filter(models.RetentionReviewItem.disposed.is_(False))
        .count()
    )
    return RetentionScanResult(run_at=now, scanned=scanned, flagged_new=flagged_new,
                               flagged_total=flagged_total)
