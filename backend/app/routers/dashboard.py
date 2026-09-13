"""P3.8: Management Dashboard. Facility-local, computed
live off existing rows (QueueTicket, StaffClockEvent, ServiceRequest,
Appointment) -- no new tables, same "thin, reuse existing engines" call
P3.2 made. RBAC/page-gate: same management-tool split as reporting.py
(REPORTING_ROLES pattern), not granted to receptionist/pharmacist by
default (permissions.py's DEFAULT_ROLE_PAGES can still grant it).

 summarised data -> GET /dashboard/summary (also composes
the tender's operational health score). patient-flow prediction
-> GET /dashboard/flow-forecast.
"""
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from .reception import _malaysia_today
from .reception._common import MALAYSIA_TZ

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DASHBOARD_ROLES = ("admin", "records_officer", "clinician")


def _require_facility(current_user: models.User) -> str:
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")
    return current_user.facility


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# summary + operational health score
# ---------------------------------------------------------------------------

def _compute_summary(db: Session, facility: str) -> schemas.DashboardSummaryOut:
    _utc_start, today = _malaysia_today()

    patients_in_queue = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.facility_name == facility, models.QueueTicket.queue_date == today,
            models.QueueTicket.status == "waiting",
        ).count()
    )
    patients_attended_today = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.facility_name == facility, models.QueueTicket.queue_date == today,
            models.QueueTicket.status == "done",
        ).count()
    )

    physicians_total = (
        db.query(models.User).filter(models.User.role == "clinician", models.User.facility == facility).count()
    )
    physicians_on_duty = (
        db.query(models.StaffClockEvent.user_id)
        .join(models.User, models.User.id == models.StaffClockEvent.user_id)
        .filter(
            models.StaffClockEvent.facility_name == facility, models.StaffClockEvent.clock_out_at.is_(None),
            models.User.role == "clinician",
        ).distinct().count()
    )

    # Average time-to-called today, for tickets actually called so far --
    # not "time in system" (completed_at), which conflates wait time with
    # consultation length.
    called_today = (
        db.query(models.QueueTicket)
        .filter(
            models.QueueTicket.facility_name == facility, models.QueueTicket.queue_date == today,
            models.QueueTicket.called_at.isnot(None),
        ).all()
    )
    if called_today:
        avg_wait_minutes = round(
            sum((t.called_at - t.checked_in_at).total_seconds() for t in called_today) / len(called_today) / 60.0, 1
        )
    else:
        avg_wait_minutes = None

    # A physician-raised referral (ServiceRequest.source == "physician_order")
    # still awaiting a result -- same "ordered" status ancillary.py itself
    # uses; cancelled/signed_off requests are resolved.
    unresolved_referrals = (
        db.query(models.ServiceRequest)
        .filter(
            models.ServiceRequest.ordering_facility_name == facility,
            models.ServiceRequest.source == "physician_order", models.ServiceRequest.status == "ordered",
        ).count()
    )

    # ponytail: heuristic thresholds/weights, not a clinically-validated
    # index -- tune per deployment if this needs to mean something more
    # precise than "roughly how is the clinic doing right now".
    wait_score = _clamp(100 - (avg_wait_minutes or 0) * (100 / 45))  # 0 at a 45min average wait
    availability_score = 100.0 if physicians_total == 0 else _clamp(physicians_on_duty / physicians_total * 100)
    queue_score = _clamp(100 - patients_in_queue * 5)  # 0 at 20 waiting
    referral_score = _clamp(100 - unresolved_referrals * 10)  # 0 at 10 unresolved
    breakdown = {
        "wait_score": wait_score, "availability_score": availability_score,
        "queue_score": queue_score, "referral_score": referral_score,
    }
    health_score = round(
        wait_score * 0.40 + availability_score * 0.25 + queue_score * 0.20 + referral_score * 0.15, 1
    )

    return schemas.DashboardSummaryOut(
        facility_name=facility, date=today,
        patients_in_queue=patients_in_queue, patients_attended_today=patients_attended_today,
        physicians_on_duty=physicians_on_duty, physicians_total=physicians_total,
        avg_wait_minutes=avg_wait_minutes, unresolved_referrals=unresolved_referrals,
        health_score=health_score, health_score_breakdown=breakdown,
    )


@router.get("/summary", response_model=schemas.DashboardSummaryOut)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*DASHBOARD_ROLES)),
):
    return _compute_summary(db, _require_facility(current_user))


# ---------------------------------------------------------------------------
# patient-flow prediction
# ---------------------------------------------------------------------------

_FORECAST_WEEKS_BACK = 8
_EWMA_ALPHA = 0.3


def _ewma(values: List[float], alpha: float = _EWMA_ALPHA) -> float:
    """Exponentially-weighted moving average, most-recent-weighted --
    ponytail: the EWMA half of the roadmap's "EWMA/GBM" sizing note.
    Deliberately not gradient boosting: a real GBM needs a training
    pipeline and a new ML dependency (scikit-learn) for a clinic-scale
    forecast that a lightweight smoothed average already serves; revisit
    only if this measurably underperforms once there's enough real
    history to tell."""
    if not values:
        return 0.0
    smoothed = values[0]
    for v in values[1:]:
        smoothed = alpha * v + (1 - alpha) * smoothed
    return smoothed


def _same_weekday_history(db: Session, facility: str, target: date, weeks_back: int) -> List[float]:
    """QueueTicket counts for the `weeks_back` most recent PAST occurrences
    of `target`'s weekday (oldest first) -- captures day-of-week
    seasonality (a Monday historically busier than a Sunday) cheaply,
    without per-facility opening-hours config."""
    dates = [(target - timedelta(days=7 * w)).isoformat() for w in range(weeks_back, 0, -1)]
    counts = dict(
        db.query(models.QueueTicket.queue_date, func.count())
        .filter(models.QueueTicket.facility_name == facility, models.QueueTicket.queue_date.in_(dates))
        .group_by(models.QueueTicket.queue_date)
        .all()
    )
    return [float(counts.get(d, 0)) for d in dates]


def _scheduled_appointments(db: Session, facility: str, day: date) -> int:
    """Count of `scheduled` appointments falling on `day`, Malaysia-local.
    Matched in Python rather than a SQL date-range filter -- `scheduled_at`
    is a TZDateTime and this codebase isn't consistent about naive vs
    aware values reaching it, so an exact Malaysia-local `.date()` compare
    here is safer than trusting a raw SQL boundary comparison. Bounded to
    one facility's scheduled appointments -- fine at clinic scale."""
    rows = (
        db.query(models.Appointment.scheduled_at)
        .filter(models.Appointment.facility_name == facility, models.Appointment.status == "scheduled")
        .all()
    )
    count = 0
    for (scheduled_at,) in rows:
        if scheduled_at is None:
            continue
        local_date = scheduled_at.astimezone(MALAYSIA_TZ).date() if scheduled_at.tzinfo else scheduled_at.date()
        if local_date == day:
            count += 1
    return count


@router.get("/flow-forecast", response_model=schemas.DashboardFlowForecastOut)
def get_dashboard_flow_forecast(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*DASHBOARD_ROLES)),
):
    facility = _require_facility(current_user)
    _utc_start, today_str = _malaysia_today()
    today = date.fromisoformat(today_str)
    tomorrow = today + timedelta(days=1)

    today_so_far = (
        db.query(models.QueueTicket)
        .filter(models.QueueTicket.facility_name == facility, models.QueueTicket.queue_date == today_str)
        .count()
    )
    today_forecast_total = round(_ewma(_same_weekday_history(db, facility, today, _FORECAST_WEEKS_BACK)), 1)
    tomorrow_forecast_total = round(_ewma(_same_weekday_history(db, facility, tomorrow, _FORECAST_WEEKS_BACK)), 1)

    return schemas.DashboardFlowForecastOut(
        today_so_far=today_so_far,
        today_forecast_total=today_forecast_total,
        today_forecast_remaining=max(0.0, round(today_forecast_total - today_so_far, 1)),
        today_scheduled_appointments=_scheduled_appointments(db, facility, today),
        tomorrow_forecast_total=tomorrow_forecast_total,
        tomorrow_scheduled_appointments=_scheduled_appointments(db, facility, tomorrow),
        weeks_of_history_used=_FORECAST_WEEKS_BACK,
    )
