"""P3.8 Management Dashboard (routers/dashboard.py): summary KPIs +
operational health score and patient-flow forecast
plus the page-gate RBAC layer
(main.py's require_page_access("dashboard")).
"""
from datetime import date, datetime, timedelta, timezone

from app import models
from app.routers.reception import _malaysia_today
from conftest import _facility, _make_patient


def _queue_ticket(db_session, patient_id, facility, queue_date, checked_in_by, queue_number, **overrides):
    ticket = models.QueueTicket(
        patient_id=patient_id, facility_name=facility, queue_date=queue_date, queue_number=queue_number,
        source=overrides.pop("source", "manual"), status=overrides.pop("status", "waiting"),
        checked_in_by=checked_in_by,
        checked_in_at=overrides.pop("checked_in_at", datetime.now(timezone.utc)),
        **overrides,
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)
    return ticket


def test_dashboard_summary_counts_and_health_score(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)
    _utc_start, today = _malaysia_today()

    _queue_ticket(db_session, patient.id, facility, today, clinician.id, 1, status="waiting")
    _queue_ticket(db_session, patient.id, facility, today, clinician.id, 2, status="waiting")
    _queue_ticket(db_session, patient.id, facility, today, clinician.id, 3, status="done")

    # Clock the clinician in -- counts toward physicians_on_duty.
    db_session.add(models.StaffClockEvent(user_id=clinician.id, facility_name=facility))
    db_session.commit()

    resp = test_client.get("/dashboard/summary", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["patients_in_queue"] == 2
    assert body["patients_attended_today"] == 1
    assert body["physicians_on_duty"] == 1
    assert body["physicians_total"] == 1
    assert body["unresolved_referrals"] == 0
    assert 0 <= body["health_score"] <= 100
    assert set(body["health_score_breakdown"]) == {"wait_score", "availability_score", "queue_score", "referral_score"}


def test_dashboard_avg_wait_and_unresolved_referrals(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)
    _utc_start, today = _malaysia_today()

    checked_in = datetime.now(timezone.utc) - timedelta(minutes=20)
    _queue_ticket(
        db_session, patient.id, facility, today, clinician.id, 1,
        status="called", checked_in_at=checked_in, called_at=checked_in + timedelta(minutes=20),
    )

    item = models.ServiceCatalogItem(module="laboratory", name="FBC", unit_price_cents=1000)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    db_session.add(models.ServiceRequest(
        patient_id=patient.id, module="laboratory", catalog_item_id=item.id,
        source="physician_order", status="ordered", ordering_facility_name=facility,
    ))
    db_session.commit()

    resp = test_client.get("/dashboard/summary", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avg_wait_minutes"] == 20.0
    assert body["unresolved_referrals"] == 1


def test_dashboard_not_granted_to_receptionist_by_default(test_client, make_user, auth_headers):
    facility = _facility()
    receptionist = make_user(role="receptionist", facility=facility)
    resp = test_client.get("/dashboard/summary", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_flow_forecast_ewma_over_same_weekday_history(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)
    _utc_start, today_str = _malaysia_today()
    today = date.fromisoformat(today_str)

    one_week_ago = (today - timedelta(days=7)).isoformat()
    two_weeks_ago = (today - timedelta(days=14)).isoformat()
    for i in range(3):
        _queue_ticket(db_session, patient.id, facility, one_week_ago, clinician.id, i + 1)
    for i in range(2):
        _queue_ticket(db_session, patient.id, facility, two_weeks_ago, clinician.id, i + 1)
    _queue_ticket(db_session, patient.id, facility, today_str, clinician.id, 1)  # today_so_far == 1

    resp = test_client.get("/dashboard/flow-forecast", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["today_so_far"] == 1
    # EWMA(alpha=0.3) over 8 weeks of history where only the two most
    # recent same-weekday counts are non-zero (2, then 3): 0.3*3 + 0.7*(0.3*2) = 1.32
    assert body["today_forecast_total"] == 1.3
    assert body["today_forecast_remaining"] == 0.3
    assert body["weeks_of_history_used"] == 8


def test_flow_forecast_scheduled_appointments_counted_for_the_right_day(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)
    _utc_start, today_str = _malaysia_today()
    today = date.fromisoformat(today_str)

    db_session.add(models.Appointment(
        patient_id=patient.id, facility_name=facility,
        scheduled_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9),
        status="scheduled", created_by=clinician.id,
    ))
    db_session.add(models.Appointment(
        patient_id=patient.id, facility_name=facility,
        scheduled_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10),
        status="cancelled", created_by=clinician.id,  # not counted -- not "scheduled"
    ))
    db_session.commit()

    resp = test_client.get("/dashboard/flow-forecast", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    assert resp.json()["today_scheduled_appointments"] == 1
