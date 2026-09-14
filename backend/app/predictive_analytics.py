"""P4.6 (predictive analytics + population-health
stratification, the "Reporting" module -- see healthcare/Compliance
Matrix.md). Sits next to reporting_engine.py (P3.6), same Design Decision:
facility-local only, no cross-facility aggregation -- every query here
filters on the caller's own `current_user.facility`, same columns
reporting_engine.py's own dataset queries already use
(`Encounter.facility_name`, `Condition.authored_by_facility`, etc.).

Deliberately NOT a real ML/forecasting library. Compliance Matrix's own
note for the shared "engine family" names two options, "EWMA /
gradient-boosted" -- this uses the lighter one. A demo environment has
weeks, not years, of history and no held-out data to validate a fitted
model against, so a gradient-boosted model here would be decoration, not
substance. `_ewma_forecast` is a dozen lines of arithmetic (level + trend,
exponentially weighted, projected forward linearly) -- no numpy/
statsmodels/scikit-learn dependency added for it.

Population risk stratification is the same call: a
deterministic, documented scoring rule over real coded fields (chronic
condition count, an emergency-critical flag, age, recent ED-visit
frequency), not a fitted clustering model -- there's no real
outcome-labelled dataset in this environment to train or validate one
against. Same reasoning P4.4 already used to skip diagnosis-based
screening (see AGENTS.md's P4.4 entry): honest partial credit on the
clause, not a fabricated model dressed up as a real one.

Every query here runs in Python over a bounded, date-filtered fetch (same
"filter/group in Python, not SQL, fine at clinic scale" precedent as
reporting_engine.py's own docstring) rather than a SQL GROUP BY DATE(),
which returns a string on SQLite and a real date on MariaDB -- one more
entry in this codebase's recurring dialect-portability list, sidestepped
by not relying on it at all.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import models

_HISTORY_DAYS = 84  # 12 weeks -- enough signal for a weekly EWMA without demanding years of history
_FORECAST_DAYS = 14
_EWMA_ALPHA = 0.3  # a single named constant, not a knob anyone needs to tune for a demo
_TOP_N_DIAGNOSES = 8
_ED_LOOKBACK_DAYS = 180
_STOCK_AT_RISK_DAYS = 14


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Lenient ISO-date parse for the free-text date columns (date_of_birth
    / diagnosed_at). Duplicated from data_quality.py's identical private
    helper rather than imported -- same call as app/pacs.py's
    `_is_on_prem_host` duplication: the two modules are conceptually
    unrelated, and it's a handful of lines."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _naive_utc_cutoff(days_ago: int) -> datetime:
    """A `now - days_ago` cutoff with tzinfo stripped -- every TZDateTime
    column in this codebase round-trips as naive-UTC from both SQLite and
    MariaDB (SQLAlchemy's DateTime(timezone=True) isn't actually enforced
    as aware by either driver on read), so a cutoff compared against one
    -- whether as a SQL filter parameter or, as in
    population_risk_stratification below, a raw Python `>=` -- has to be
    naive too, or it either mismatches the driver's bind encoding or raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`
    outright. Same fix as security_analytics.py's identical naive-vs-aware
    hazard (see that module's `_myt_midnight_utc` / `latest.replace
    (tzinfo=None)`, and the [[p4-5-security-alerts-landed]] memory note
    that this class of bug is a recurring one in this codebase)."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(tzinfo=None)


def _daily_series(dates: List[date], since: date, until: date) -> List[int]:
    """Dense, zero-filled day-by-day count series between since/until
    inclusive, oldest first -- what `_ewma_forecast` expects."""
    counts: Dict[date, int] = defaultdict(int)
    for d in dates:
        if d is not None:
            counts[d] += 1
    out = []
    d = since
    while d <= until:
        out.append(counts.get(d, 0))
        d += timedelta(days=1)
    return out


def _ewma_forecast(series: List[int], alpha: float = _EWMA_ALPHA, horizon: int = _FORECAST_DAYS) -> dict:
    """Simple exponential smoothing for `level`, plus a second EWMA (same
    alpha) over the level's successive differences for `trend` -- NOT
    textbook Holt's linear-trend method (that feeds the trend term back
    into the level update itself: `level = alpha*v + (1-alpha)*(prev_level
    + prev_trend)`). This simpler version can't diverge and degrades
    cleanly to trend=0 on a flat series, at the cost of lagging a real
    Holt smoother on a sudden trend shift -- a fine trade for the level of
    signal a demo dataset has. `series` is oldest-first; projects `horizon`
    days forward, clamped at 0 (never a negative visit/case/stock count).
    Returns the smoothed historical series alongside the projection so a
    chart can show both without the caller re-deriving anything."""
    if not series:
        return {"level": 0.0, "trend": 0.0, "smoothed": [], "forecast": [0.0] * horizon}
    level = float(series[0])
    trend = 0.0
    smoothed = [level]
    for v in series[1:]:
        prev_level = level
        level = alpha * v + (1 - alpha) * level
        trend = alpha * (level - prev_level) + (1 - alpha) * trend
        smoothed.append(level)
    forecast = [round(max(0.0, level + trend * i), 2) for i in range(1, horizon + 1)]
    return {
        "level": round(level, 2), "trend": round(trend, 3),
        "smoothed": [round(x, 2) for x in smoothed], "forecast": forecast,
    }


def forecast_visit_volume(db: Session, facility: str) -> dict:
    """: forecast patient visit volumes. One series per
    encounter_type (outpatient/inpatient/emergency/transfer) plus an
    "all" total, each its own EWMA projection."""
    since_dt = _naive_utc_cutoff(_HISTORY_DAYS)
    rows = (
        db.query(models.Encounter.started_at, models.Encounter.encounter_type)
        .filter(models.Encounter.facility_name == facility, models.Encounter.started_at >= since_dt)
        .all()
    )
    since, until = _today() - timedelta(days=_HISTORY_DAYS - 1), _today()
    by_type: Dict[str, List[date]] = defaultdict(list)
    all_dates: List[date] = []
    for started_at, encounter_type in rows:
        if started_at is None:
            continue
        d = started_at.date()
        all_dates.append(d)
        by_type[encounter_type or "unknown"].append(d)

    series = {"all": _ewma_forecast(_daily_series(all_dates, since, until))}
    for encounter_type, dates in by_type.items():
        series[encounter_type] = _ewma_forecast(_daily_series(dates, since, until))
    return {"history_days": _HISTORY_DAYS, "forecast_days": _FORECAST_DAYS, "series": series}


def forecast_disease_burden(db: Session, facility: str) -> dict:
    """: forecast disease burden trends. Top diagnoses by
    recent new-case volume, each with its own EWMA trend -- a rising trend
    on an already-common diagnosis is the actionable signal, not the raw
    count alone."""
    rows = (
        db.query(models.Condition.name, models.Condition.diagnosed_at)
        .filter(models.Condition.authored_by_facility == facility)
        .all()
    )
    since, until = _today() - timedelta(days=_HISTORY_DAYS - 1), _today()
    by_name: Dict[str, List[date]] = defaultdict(list)
    for name, diagnosed_at in rows:
        d = _parse_iso_date(diagnosed_at)
        if d is not None and since <= d <= until:
            by_name[name].append(d)

    ranked = sorted(by_name.items(), key=lambda kv: len(kv[1]), reverse=True)[:_TOP_N_DIAGNOSES]
    diagnoses = {
        name: {"new_cases": len(dates), **_ewma_forecast(_daily_series(dates, since, until))}
        for name, dates in ranked
    }
    return {"history_days": _HISTORY_DAYS, "forecast_days": _FORECAST_DAYS, "diagnoses": diagnoses}


def forecast_stock_depletion(db: Session, facility: str) -> dict:
    """: forecast pharmacy stock depletion. Average daily
    consumption over the history window projects days-until-reorder-
    threshold per item; items with no consumption in the window have no
    projectable rate and are reported as such rather than divided by zero."""
    since_dt = _naive_utc_cutoff(_HISTORY_DAYS)
    items = (
        db.query(models.MedicineInventoryItem)
        .filter(models.MedicineInventoryItem.facility_name == facility)
        .all()
    )
    events = (
        db.query(models.MedicineStockEvent.item_id, models.MedicineStockEvent.delta)
        .filter(
            models.MedicineStockEvent.facility_name == facility,
            models.MedicineStockEvent.kind == "consume",
            models.MedicineStockEvent.at >= since_dt,
        )
        .all()
    )
    consumed: Dict[str, float] = defaultdict(float)
    for item_id, delta in events:
        consumed[item_id] += abs(delta)  # consume deltas are negative -- see routers/pharmacy.py::adjust_stock

    out = []
    for item in items:
        daily_rate = consumed.get(item.id, 0.0) / _HISTORY_DAYS
        threshold = item.reorder_threshold or 0
        if daily_rate <= 0:
            days_to_threshold = None
        else:
            days_to_threshold = round(max(0.0, item.quantity_on_hand - threshold) / daily_rate, 1)
        out.append({
            "item_id": item.id, "drug_name": item.drug_name, "unit": item.unit,
            "quantity_on_hand": item.quantity_on_hand, "reorder_threshold": item.reorder_threshold,
            "avg_daily_consumption": round(daily_rate, 2), "days_to_threshold": days_to_threshold,
            "at_risk": days_to_threshold is not None and days_to_threshold <= _STOCK_AT_RISK_DAYS,
        })
    out.sort(key=lambda r: (r["days_to_threshold"] is None, r["days_to_threshold"]))
    return {"history_days": _HISTORY_DAYS, "at_risk_within_days": _STOCK_AT_RISK_DAYS, "items": out}


@dataclass
class _PatientRisk:
    patient_id: str
    patient_name: str
    score: int
    chronic_count: int
    critical_flag: bool
    age: Optional[int]
    recent_ed_visits: int
    band: str


def _age(dob: Optional[str]) -> Optional[int]:
    d = _parse_iso_date(dob)
    if d is None:
        return None
    today = _today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def _risk_band(score: int) -> str:
    # ponytail: fixed thresholds on a naive additive score, not a fitted
    # model -- see the module docstring. Upgrade path: replace with a real
    # model once there's outcome-labelled data (readmissions, ED
    # recurrence) large enough to validate one against.
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def population_risk_stratification(db: Session, facility: str) -> dict:
    """: cluster patients by risk profile, surface high-risk
    cohort summaries. Scoped to patients this facility has authored
    conditions for or seen encounters for -- same facility-local rule as
    every other query in this module.

    Cohort membership itself is NOT time-windowed (any encounter/condition
    ever, at this facility, counts) -- only the recent-ED-visit sub-metric
    is (`_ED_LOOKBACK_DAYS`). Deliberate: "every patient this facility has
    a relationship with" is the natural population for a risk registry,
    not "patients seen in the last N days" -- narrow that if the product
    ask ever becomes "currently active patients" specifically."""
    encounter_rows = (
        db.query(models.Encounter.patient_id, models.Encounter.encounter_type, models.Encounter.started_at)
        .filter(models.Encounter.facility_name == facility)
        .all()
    )
    ed_since = _naive_utc_cutoff(_ED_LOOKBACK_DAYS)
    patient_ids: set = set()
    ed_visits: Dict[str, int] = defaultdict(int)
    for patient_id, encounter_type, started_at in encounter_rows:
        patient_ids.add(patient_id)
        if encounter_type == "emergency" and started_at is not None and started_at >= ed_since:
            ed_visits[patient_id] += 1

    condition_rows = (
        db.query(models.Condition.patient_id, models.Condition.is_chronic, models.Condition.critical_for_emergency)
        .filter(models.Condition.authored_by_facility == facility, models.Condition.status == "active")
        .all()
    )
    chronic_count: Dict[str, int] = defaultdict(int)
    critical_flag: Dict[str, bool] = defaultdict(bool)
    for patient_id, is_chronic, is_critical in condition_rows:
        patient_ids.add(patient_id)
        if is_chronic:
            chronic_count[patient_id] += 1
        if is_critical:
            critical_flag[patient_id] = True

    if not patient_ids:
        return {"cohort_size": 0, "by_band": {"low": 0, "medium": 0, "high": 0}, "high_risk_patients": []}

    patients = {
        p.id: p for p in db.query(models.Patient).filter(models.Patient.id.in_(patient_ids)).all()
    }

    by_band = {"low": 0, "medium": 0, "high": 0}
    high_risk: List[_PatientRisk] = []
    for patient_id in patient_ids:
        patient = patients.get(patient_id)
        if patient is None:
            continue
        age = _age(patient.date_of_birth)
        c_count = chronic_count.get(patient_id, 0)
        recent_ed = ed_visits.get(patient_id, 0)
        score = (
            c_count
            + (2 if critical_flag.get(patient_id) else 0)
            + (1 if age is not None and age >= 65 else 0)
            + (1 if recent_ed >= 2 else 0)
        )
        band = _risk_band(score)
        by_band[band] += 1
        if band == "high":
            high_risk.append(_PatientRisk(
                patient_id=patient_id, patient_name=patient.full_name, score=score,
                chronic_count=c_count, critical_flag=critical_flag.get(patient_id, False),
                age=age, recent_ed_visits=recent_ed, band=band,
            ))

    high_risk.sort(key=lambda r: r.score, reverse=True)
    return {
        "cohort_size": len(patient_ids),
        "by_band": by_band,
        "high_risk_patients": [
            {
                "patient_id": r.patient_id, "patient_name": r.patient_name, "score": r.score,
                "chronic_count": r.chronic_count, "critical_flag": r.critical_flag,
                "age": r.age, "recent_ed_visits": r.recent_ed_visits,
            }
            for r in high_risk
        ],
    }
