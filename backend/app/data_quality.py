"""Batch data-quality validators (roadmap P2.12, the tender).

`run_scan(db)` walks a registry of independent rules -- each one queries for
rows that violate an invariant and yields `Finding`s -- then UPSERTs them
into `data_quality_alerts` keyed on `(rule, entity_type, entity_id)`:

  - a new violation  -> a new alert row;
  - a repeat sighting -> bumps `last_seen_at` / `times_seen`, nothing else;
  - a violation that stopped firing -> auto-resolved (`resolved_by='system'`),
    unless an admin had already acknowledged/resolved it by hand.

Invoked by `db/data_quality_scan.py` on a cron and ad hoc from
`GET /admin/data-quality` machinery. Read-heavy, write-light -- safe to run
against production.

Configurable (tender wording): set `DATA_QUALITY_DISABLED_RULES` to a
comma-separated list of rule keys to skip. `run_scan(..., disabled=...)`
takes the same as an explicit arg (tests, one-off runs).

`detail` strings deliberately never carry a diagnosis / drug / allergen
value -- they name the field and the *shape* of the problem only, the same
"no clinical values in a second store" rule audit_logs follows (M8).
"""
import logging
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Callable, Iterator, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas

_log = logging.getLogger("clarion.data_quality")

# --- reference sets: the read-time audit of what is actually in the DB -----
# `encounter_type` has a real write-time gate (schemas.VALID_ENCOUNTER_TYPES) --
# reuse it, don't re-declare. `gender` / `blood_type` have NO write-time
# validator today (schemas.PatientCreate accepts any string), so these two
# sets are the SOLE gate; when P4.1 adds coded demographics they should move
# to schemas.py and be enforced on write. `status` / `severity` are defaulted
# on the model but not constrained.
_VALID_ENCOUNTER_TYPES = schemas.VALID_ENCOUNTER_TYPES
_VALID_CONDITION_STATUS = {"active", "resolved"}
_VALID_ALLERGY_SEVERITY = {"mild", "moderate", "severe", "unknown"}
_VALID_GENDER = {"male", "female", "other", "unknown", "prefer_not_to_say"}
_VALID_BLOOD_TYPES = {
    "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-",
    "A POSITIVE", "A NEGATIVE", "B POSITIVE", "B NEGATIVE",
    "AB POSITIVE", "AB NEGATIVE", "O POSITIVE", "O NEGATIVE",
    "UNKNOWN",
}
_MAX_PLAUSIBLE_AGE_YEARS = 120

_NAME_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


@dataclass
class Finding:
    rule: str
    category: str          # missing | duplicate | coding | anomaly
    severity: str          # info | warning | error
    entity_type: str       # patient | condition | medication | allergy | encounter
    entity_id: str
    patient_id: Optional[str]
    detail: str


@dataclass
class Rule:
    key: str          # the CONFIG key -- what DATA_QUALITY_DISABLED_RULES lists
    fn: Callable[[Session], Iterator[Finding]]
    emits: tuple      # the Finding.rule strings this rule can produce (== the
                      # DataQualityAlert.rule values). One rule fn can emit
                      # several (the date rules cover 3 fields; anomaly_dates
                      # covers 5), so the config key and the alert rule are
                      # deliberately different namespaces -- `emits` bridges
                      # them for the "don't auto-resolve a disabled rule's
                      # alerts" check. `category` / `severity` live on each
                      # Finding, not here -- one source of truth.


@dataclass
class ScanResult:
    run_at: datetime
    rules_run: int
    rules_skipped: list
    rules_failed: list          # [(rule_key, exception-repr)] -- a rule that threw
    findings: int
    new_alerts: int
    still_open: int
    auto_resolved: int

    def as_dict(self) -> dict:
        return {**asdict(self), "run_at": self.run_at.isoformat()}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _normalize_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", _NAME_PUNCT_RE.sub(" ", value)).strip().lower()


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    """A lenient ISO-date parse for the String date columns
    (date_of_birth / diagnosed_at / start_date). Returns None on anything
    that is not a clean `YYYY-MM-DD` (optionally with a time part)."""
    if not value or not isinstance(value, str):
        return None
    head = value.strip()[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _blank(value: Optional[str]) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _today() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------
# rules -- each yields Finding(); severity/category come from the registry
# --------------------------------------------------------------------------

def _missing_patient_demographics(db: Session) -> Iterator[Finding]:
    for p in db.query(models.Patient).all():
        if _blank(p.gender):
            yield Finding("patient_missing_gender", "missing", "info", "patient", p.id, p.id,
                          "patient has no gender recorded")
        if _blank(p.blood_type):
            yield Finding("patient_missing_blood_type", "missing", "warning", "patient", p.id, p.id,
                          "patient has no blood_type recorded (matters on the emergency card)")


def _missing_condition_name(db: Session) -> Iterator[Finding]:
    for c in db.query(models.Condition).all():
        if _blank(c.name):  # _blank() also catches whitespace-only, unlike a SQL `== ''`
            yield Finding("condition_blank_name", "missing", "error", "condition", c.id, c.patient_id,
                          "condition row has a blank name")


def _missing_medication_directions(db: Session) -> Iterator[Finding]:
    for m in db.query(models.MedicationStatement).filter(models.MedicationStatement.active.is_(True)).all():
        if _blank(m.dosage):
            yield Finding("medication_missing_dosage", "missing", "warning", "medication", m.id, m.patient_id,
                          "active medication has no dosage")
        if _blank(m.frequency):
            yield Finding("medication_missing_frequency", "missing", "warning", "medication", m.id, m.patient_id,
                          "active medication has no frequency")


def _missing_encounter_reason(db: Session) -> Iterator[Finding]:
    for e in db.query(models.Encounter).all():
        if _blank(e.reason):
            yield Finding("encounter_missing_reason", "missing", "info", "encounter", e.id, e.patient_id,
                          f"{e.encounter_type} encounter has no reason recorded")


def _coding_patient_gender(db: Session) -> Iterator[Finding]:
    for p in db.query(models.Patient).filter(models.Patient.gender.isnot(None)).all():
        if p.gender and p.gender.strip() and p.gender.strip().lower() not in _VALID_GENDER:
            yield Finding("patient_invalid_gender", "coding", "warning", "patient", p.id, p.id,
                          f"gender={p.gender!r} is not one of {sorted(_VALID_GENDER)}")


def _coding_patient_blood_type(db: Session) -> Iterator[Finding]:
    for p in db.query(models.Patient).filter(models.Patient.blood_type.isnot(None)).all():
        bt = (p.blood_type or "").strip().upper()
        if bt and bt not in _VALID_BLOOD_TYPES:
            yield Finding("patient_invalid_blood_type", "coding", "warning", "patient", p.id, p.id,
                          f"blood_type={p.blood_type!r} is not a recognised ABO/Rh group")


def _coding_condition_status(db: Session) -> Iterator[Finding]:
    for c in db.query(models.Condition).filter(models.Condition.status.isnot(None)).all():
        if c.status and c.status not in _VALID_CONDITION_STATUS:
            yield Finding("condition_invalid_status", "coding", "error", "condition", c.id, c.patient_id,
                          f"status={c.status!r} is not one of {sorted(_VALID_CONDITION_STATUS)}")


def _coding_allergy_severity(db: Session) -> Iterator[Finding]:
    for a in db.query(models.AllergyIntolerance).filter(models.AllergyIntolerance.severity.isnot(None)).all():
        if a.severity and a.severity not in _VALID_ALLERGY_SEVERITY:
            yield Finding("allergy_invalid_severity", "coding", "warning", "allergy", a.id, a.patient_id,
                          f"severity={a.severity!r} is not one of {sorted(_VALID_ALLERGY_SEVERITY)}")


def _coding_encounter_type(db: Session) -> Iterator[Finding]:
    for e in db.query(models.Encounter).all():
        if e.encounter_type not in _VALID_ENCOUNTER_TYPES:
            yield Finding("encounter_invalid_type", "coding", "error", "encounter", e.id, e.patient_id,
                          f"encounter_type={e.encounter_type!r} is not one of {sorted(_VALID_ENCOUNTER_TYPES)}")


def _coding_unparseable_dates(db: Session) -> Iterator[Finding]:
    for p in db.query(models.Patient).all():
        if not _blank(p.date_of_birth) and _parse_iso_date(p.date_of_birth) is None:
            yield Finding("patient_unparseable_dob", "coding", "error", "patient", p.id, p.id,
                          f"date_of_birth={p.date_of_birth!r} is not an ISO date")
    for c in db.query(models.Condition).all():
        if not _blank(c.diagnosed_at) and _parse_iso_date(c.diagnosed_at) is None:
            yield Finding("condition_unparseable_diagnosed_at", "coding", "warning", "condition", c.id, c.patient_id,
                          f"diagnosed_at={c.diagnosed_at!r} is not an ISO date")
    for m in db.query(models.MedicationStatement).all():
        if not _blank(m.start_date) and _parse_iso_date(m.start_date) is None:
            yield Finding("medication_unparseable_start_date", "coding", "warning", "medication", m.id, m.patient_id,
                          f"start_date={m.start_date!r} is not an ISO date")


def _duplicate_patients(db: Session) -> Iterator[Finding]:
    """Exact-NRIC duplicates are already impossible (unique
    `normalized_national_id`). This finds the *probable* duplicates that slip
    past that: same normalised name + same date_of_birth, where at least one
    of the pair has no NRIC on file (so they were never de-duped)."""
    buckets: dict[tuple, list] = defaultdict(list)
    for p in db.query(models.Patient).all():
        key = (_normalize_name(p.full_name), (p.date_of_birth or "").strip()[:10])
        if key[0] and key[1]:
            buckets[key].append(p)
    for (_name, _dob), group in buckets.items():
        if len(group) < 2:
            continue
        if not any(g.normalized_national_id is None for g in group):
            continue  # every row has a distinct NRIC -> genuinely different people
        n = len(group)
        for p in group:
            yield Finding("patient_probable_duplicate", "duplicate", "warning", "patient", p.id, p.id,
                          f"{n} patient records share this name + date_of_birth and at least "
                          f"one has no NRIC on file -- review for a merge")


def _duplicate_conditions_on_patient(db: Session) -> Iterator[Finding]:
    buckets: dict[tuple, list] = defaultdict(list)
    for c in db.query(models.Condition).filter(models.Condition.status == "active").all():
        buckets[(c.patient_id, _normalize_name(c.name))].append(c)
    for (patient_id, name), group in buckets.items():
        if name and len(group) > 1:
            n = len(group)
            for c in group:
                yield Finding("condition_duplicate_on_patient", "duplicate", "info", "condition", c.id, patient_id,
                              f"{n} active condition rows on this patient have the same name")


def _anomaly_dates(db: Session) -> Iterator[Finding]:
    today = _today()
    floor = date(today.year - _MAX_PLAUSIBLE_AGE_YEARS, today.month, today.day) \
        if (today.month, today.day) != (2, 29) else date(today.year - _MAX_PLAUSIBLE_AGE_YEARS, 2, 28)
    # `detail` describes the SHAPE of the problem, never the stored date -- a
    # full DOB is PDPA PII and an event date is a clinical value; neither
    # belongs in a second store (same M8 rule audit_logs follows).
    dob_by_patient: dict[str, Optional[date]] = {}
    for p in db.query(models.Patient).all():
        dob = _parse_iso_date(p.date_of_birth)
        dob_by_patient[p.id] = dob
        if dob is None:
            continue
        if dob > today:
            yield Finding("patient_dob_in_future", "anomaly", "error", "patient", p.id, p.id,
                          f"date_of_birth is {(dob - today).days} days in the future")
        elif dob < floor:
            yield Finding("patient_implausible_age", "anomaly", "warning", "patient", p.id, p.id,
                          f"date_of_birth implies an age over {_MAX_PLAUSIBLE_AGE_YEARS}")

    for c in db.query(models.Condition).all():
        dx = _parse_iso_date(c.diagnosed_at)
        if dx is None:
            continue
        if dx > today:
            yield Finding("condition_diagnosed_in_future", "anomaly", "warning", "condition", c.id, c.patient_id,
                          "diagnosed_at is in the future")
        dob = dob_by_patient.get(c.patient_id)
        if dob is not None and dx < dob:
            yield Finding("condition_diagnosed_before_birth", "anomaly", "error", "condition", c.id, c.patient_id,
                          "diagnosed_at precedes the patient's date_of_birth")

    for m in db.query(models.MedicationStatement).all():
        sd = _parse_iso_date(m.start_date)
        if sd is not None and sd > today:
            yield Finding("medication_start_in_future", "anomaly", "warning", "medication", m.id, m.patient_id,
                          "start_date is in the future")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

RULES: list[Rule] = [
    Rule("missing_patient_demographics", _missing_patient_demographics,
         ("patient_missing_gender", "patient_missing_blood_type")),
    Rule("missing_condition_name", _missing_condition_name,
         ("condition_blank_name",)),
    Rule("missing_medication_directions", _missing_medication_directions,
         ("medication_missing_dosage", "medication_missing_frequency")),
    Rule("missing_encounter_reason", _missing_encounter_reason,
         ("encounter_missing_reason",)),
    Rule("coding_patient_gender", _coding_patient_gender,
         ("patient_invalid_gender",)),
    Rule("coding_patient_blood_type", _coding_patient_blood_type,
         ("patient_invalid_blood_type",)),
    Rule("coding_condition_status", _coding_condition_status,
         ("condition_invalid_status",)),
    Rule("coding_allergy_severity", _coding_allergy_severity,
         ("allergy_invalid_severity",)),
    Rule("coding_encounter_type", _coding_encounter_type,
         ("encounter_invalid_type",)),
    Rule("coding_unparseable_dates", _coding_unparseable_dates,
         ("patient_unparseable_dob", "condition_unparseable_diagnosed_at",
          "medication_unparseable_start_date")),
    Rule("duplicate_patients", _duplicate_patients,
         ("patient_probable_duplicate",)),
    Rule("duplicate_conditions_on_patient", _duplicate_conditions_on_patient,
         ("condition_duplicate_on_patient",)),
    Rule("anomaly_dates", _anomaly_dates,
         ("patient_dob_in_future", "patient_implausible_age", "condition_diagnosed_in_future",
          "condition_diagnosed_before_birth", "medication_start_in_future")),
]

# Finding.rule -> the config key of the Rule that produces it.
_FINDING_RULE_TO_KEY = {fr: r.key for r in RULES for fr in r.emits}


def _disabled_from_env() -> set:
    raw = os.environ.get("DATA_QUALITY_DISABLED_RULES", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def run_scan(db: Session, *, disabled: Optional[set] = None, _retry: bool = True) -> ScanResult:
    now = datetime.now(timezone.utc)
    skip = set(disabled) if disabled is not None else _disabled_from_env()

    # One query for every existing alert, keyed for O(1) lookup -- a dirty DB
    # can produce hundreds of findings and a per-finding SELECT would be that
    # many round-trips.
    by_key = {
        (a.rule, a.entity_type, a.entity_id): a
        for a in db.query(models.DataQualityAlert).all()
    }

    seen_keys: set = set()
    ran_keys: set = set(skip)  # config keys NOT scanned this run (start with skipped)
    findings = 0
    new_alerts = 0
    rules_run = 0
    rules_failed: list = []

    for rule in RULES:
        if rule.key in skip:
            continue
        try:
            rule_findings = list(rule.fn(db))
        except Exception as exc:  # noqa: BLE001 - one bad rule must not lose the whole scan
            _log.exception("data-quality rule %s failed", rule.key)
            rules_failed.append((rule.key, repr(exc)))
            ran_keys.add(rule.key)  # treat as "not scanned" -> don't auto-resolve its alerts
            continue
        rules_run += 1
        for f in rule_findings:
            findings += 1
            key = (f.rule, f.entity_type, f.entity_id)
            seen_keys.add(key)
            existing = by_key.get(key)
            if existing is None:
                row = models.DataQualityAlert(
                    rule=f.rule, category=f.category, severity=f.severity,
                    entity_type=f.entity_type, entity_id=f.entity_id, patient_id=f.patient_id,
                    detail=f.detail, first_seen_at=now, last_seen_at=now, times_seen=1,
                )
                db.add(row)
                by_key[key] = row
                new_alerts += 1
            else:
                existing.last_seen_at = now
                existing.times_seen = (existing.times_seen or 0) + 1
                existing.detail = f.detail
                existing.severity = f.severity
                existing.category = f.category
                existing.patient_id = f.patient_id
                if existing.resolved and existing.resolved_by == "system":
                    # it started firing again -- reopen an auto-resolved alert
                    existing.resolved = False
                    existing.resolved_by = None
                    existing.resolved_at = None

    # auto-resolve: open, system-owned alerts whose finding did not recur AND
    # whose rule actually ran this pass (a skipped/failed rule's alerts are
    # left alone). `ran_keys` holds the config keys we did NOT scan.
    auto_resolved = 0
    for a in by_key.values():
        if a.resolved or (a.rule, a.entity_type, a.entity_id) in seen_keys:
            continue
        if _FINDING_RULE_TO_KEY.get(a.rule, a.rule) in ran_keys:
            continue
        a.resolved = True
        a.resolved_by = "system"
        a.resolved_at = now
        auto_resolved += 1

    try:
        db.commit()
    except IntegrityError:
        # A concurrent scan (cron vs the /admin/data-quality/scan button)
        # inserted one of the same (rule, entity) keys first. Roll back and
        # re-run once -- the scan is deterministic, so the retry sees the
        # committed rows and updates instead of inserting.
        db.rollback()
        if _retry:
            return run_scan(db, disabled=disabled, _retry=False)
        raise

    still_open = (
        db.query(models.DataQualityAlert)
        .filter(models.DataQualityAlert.resolved.is_(False))
        .count()
    )
    return ScanResult(
        run_at=now, rules_run=rules_run, rules_skipped=sorted(skip),
        rules_failed=rules_failed, findings=findings, new_alerts=new_alerts,
        still_open=still_open, auto_resolved=auto_resolved,
    )
