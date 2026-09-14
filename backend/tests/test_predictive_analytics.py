"""P4.6 (app/predictive_analytics.py + its HTTP surface in
routers/reporting.py): EWMA forecast arithmetic, facility scoping (same
rule as test_reporting.py's own dataset tests), stock-depletion divide-
by-zero avoidance, and risk-stratification scoring/banding.
"""
from datetime import datetime, timedelta, timezone

from app import models, predictive_analytics as pa
from conftest import _facility, _make_patient
from test_reporting import _condition, _encounter


def _stock_item(db_session, facility, **overrides):
    item = models.MedicineInventoryItem(
        facility_name=facility,
        drug_name=overrides.pop("drug_name", "Paracetamol"),
        quantity_on_hand=overrides.pop("quantity_on_hand", 100),
        unit=overrides.pop("unit", "tablets"),
        **overrides,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _consume(db_session, facility, item, delta, at):
    ev = models.MedicineStockEvent(
        facility_name=facility, item_id=item.id, delta=delta, kind="consume", at=at,
    )
    db_session.add(ev)
    db_session.commit()
    return ev


# --------------------------------------------------------------------------
# _ewma_forecast -- pure arithmetic, no DB
# --------------------------------------------------------------------------

def test_ewma_forecast_empty_series():
    out = pa._ewma_forecast([])
    assert out["level"] == 0.0 and out["forecast"] == [0.0] * pa._FORECAST_DAYS


def test_ewma_forecast_flat_series_has_no_trend():
    out = pa._ewma_forecast([5] * 20)
    assert out["level"] == 5.0
    assert out["trend"] == 0.0
    assert all(f == 5.0 for f in out["forecast"])


def test_ewma_forecast_rising_series_has_positive_trend_and_projects_up():
    series = list(range(1, 21))  # 1..20, strictly increasing
    out = pa._ewma_forecast(series)
    assert out["trend"] > 0
    assert out["forecast"][-1] > out["forecast"][0] > out["level"]


# --------------------------------------------------------------------------
# forecast_visit_volume -- facility scoping + per-type buckets
# --------------------------------------------------------------------------

def test_forecast_visit_volume_scopes_by_facility_and_type(db_session):
    fac_a, fac_b = _facility("PredA"), _facility("PredB")
    pa_pt = _make_patient(db_session)
    now = datetime.now(timezone.utc)
    _encounter(db_session, pa_pt.id, fac_a, encounter_type="outpatient", started_at=now)
    _encounter(db_session, pa_pt.id, fac_a, encounter_type="emergency", started_at=now)
    _encounter(db_session, pa_pt.id, fac_b, encounter_type="outpatient", started_at=now)  # different facility

    result = pa.forecast_visit_volume(db_session, fac_a)
    assert set(result["series"]) >= {"all", "outpatient", "emergency"}
    assert sum(result["series"]["all"]["smoothed"][-1:] or [0]) >= 0  # shape sanity
    # Facility B's encounter must not inflate Facility A's series: with one
    # outpatient + one emergency for A on "today", the last smoothed value
    # for "all" reflects at most those two, never three.
    assert result["series"]["all"]["smoothed"][-1] <= 2.0 + 1e-9


# --------------------------------------------------------------------------
# forecast_disease_burden -- recency window + facility scoping
# --------------------------------------------------------------------------

def test_forecast_disease_burden_excludes_stale_and_other_facility(db_session):
    fac_a, fac_b = _facility("PredA"), _facility("PredB")
    patient = _make_patient(db_session)
    today = datetime.now(timezone.utc).date()
    _condition(db_session, patient.id, fac_a, name="Dengue Fever", diagnosed_at=today.isoformat())
    # Outside the history window -- must not appear.
    stale = (today - timedelta(days=pa._HISTORY_DAYS + 30)).isoformat()
    _condition(db_session, patient.id, fac_a, name="Old Diagnosis", diagnosed_at=stale)
    # Same-name diagnosis authored by a different facility -- must not count towards A.
    _condition(db_session, patient.id, fac_b, name="Dengue Fever", diagnosed_at=today.isoformat())

    result = pa.forecast_disease_burden(db_session, fac_a)
    assert "Dengue Fever" in result["diagnoses"]
    assert result["diagnoses"]["Dengue Fever"]["new_cases"] == 1
    assert "Old Diagnosis" not in result["diagnoses"]


# --------------------------------------------------------------------------
# forecast_stock_depletion -- divide-by-zero avoidance + at-risk flag
# --------------------------------------------------------------------------

def test_forecast_stock_depletion_no_consumption_is_not_at_risk(db_session):
    facility = _facility("PredStock")
    item = _stock_item(db_session, facility, quantity_on_hand=50, reorder_threshold=10)

    result = pa.forecast_stock_depletion(db_session, facility)
    row = next(r for r in result["items"] if r["item_id"] == item.id)
    assert row["days_to_threshold"] is None
    assert row["at_risk"] is False


def test_forecast_stock_depletion_flags_fast_consumption_as_at_risk(db_session):
    facility = _facility("PredStock")
    item = _stock_item(db_session, facility, quantity_on_hand=20, reorder_threshold=10)
    now = datetime.now(timezone.utc)
    # Consuming 7/day for the last 7 days -> avg rate ~7/84 days is tiny;
    # instead spread consumption across the WHOLE history window so the
    # average lands near 1/day and 10 units above threshold projects to a
    # single-digit day count, safely under _STOCK_AT_RISK_DAYS.
    for day in range(pa._HISTORY_DAYS):
        _consume(db_session, facility, item, delta=-3, at=now - timedelta(days=day))

    result = pa.forecast_stock_depletion(db_session, facility)
    row = next(r for r in result["items"] if r["item_id"] == item.id)
    assert row["avg_daily_consumption"] == 3.0
    assert row["days_to_threshold"] is not None
    assert row["at_risk"] is True


# --------------------------------------------------------------------------
# population_risk_stratification -- scoring, banding, facility scoping
# --------------------------------------------------------------------------

def test_population_risk_stratification_empty_cohort_is_safe(db_session):
    facility = _facility("PredEmpty")
    result = pa.population_risk_stratification(db_session, facility)
    assert result == {"cohort_size": 0, "by_band": {"low": 0, "medium": 0, "high": 0}, "high_risk_patients": []}


def test_population_risk_stratification_scores_high_and_low_correctly(db_session):
    facility, other_facility = _facility("PredRisk"), _facility("PredRiskOther")
    now = datetime.now(timezone.utc)

    high = _make_patient(db_session, full_name="High Risk", date_of_birth="1950-01-01")  # 70+ -> age band
    _encounter(db_session, high.id, facility, encounter_type="emergency", started_at=now)
    _encounter(db_session, high.id, facility, encounter_type="emergency", started_at=now - timedelta(days=5))
    _condition(db_session, high.id, facility, name="Diabetes", is_chronic=True, status="active")
    _condition(db_session, high.id, facility, name="Hypertension", is_chronic=True,
               critical_for_emergency=True, status="active")

    low = _make_patient(db_session, full_name="Low Risk", date_of_birth="1995-01-01")
    _encounter(db_session, low.id, facility, encounter_type="outpatient", started_at=now)

    # Known only to a different facility -- must not appear in this cohort at all.
    elsewhere = _make_patient(db_session, full_name="Elsewhere Patient", date_of_birth="1950-01-01")
    _encounter(db_session, elsewhere.id, other_facility, encounter_type="emergency", started_at=now)

    result = pa.population_risk_stratification(db_session, facility)
    assert result["cohort_size"] == 2
    assert result["by_band"]["high"] == 1
    assert result["by_band"]["low"] == 1
    assert {p["patient_id"] for p in result["high_risk_patients"]} == {high.id}
    assert result["high_risk_patients"][0]["chronic_count"] == 2
    assert result["high_risk_patients"][0]["critical_flag"] is True
    assert result["high_risk_patients"][0]["recent_ed_visits"] == 2


# --------------------------------------------------------------------------
# HTTP surface -- RBAC + facility gate (same shape as test_reporting.py)
# --------------------------------------------------------------------------

def test_predictive_endpoints_require_reporting_role(test_client, make_user, auth_headers):
    facility = _facility("PredHttp")
    receptionist = make_user(role="receptionist", facility=facility)
    admin = make_user(role="admin", facility=facility)

    for path in ("visit-volume", "disease-burden", "stock-depletion", "risk-stratification"):
        assert test_client.get(f"/reports/predictive/{path}", headers=auth_headers(receptionist)).status_code == 403
        assert test_client.get(f"/reports/predictive/{path}", headers=auth_headers(admin)).status_code == 200
