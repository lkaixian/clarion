"""P4.5 admin API: /admin/security-alerts list/summary/scan/
acknowledge/resolve/explain. Same structure as test_data_quality.py's own
admin-API section -- alert rows are hand-built here (not derived from a real
scan) so RBAC/facility-scoping/lifecycle can be tested independently of the
rule logic itself (see test_security_analytics.py for that).
"""
from datetime import datetime, timezone

from app import models

_uniq = [0]


def _mk_alert(db, **over):
    _uniq[0] += 1
    now = datetime.now(timezone.utc)
    kw = dict(
        rule="off_hours_access", category="unusual_hour", severity="info",
        actor=f"sec-test-{_uniq[0]}", actor_role="clinician", actor_facility=None,
        window_start=now, window_end=now, detail="1 distinct patient(s) accessed during quiet hours",
        times_seen=1,
    )
    kw.update(over)
    a = models.SecurityAlert(**kw)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_admin_security_alerts_endpoints(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Hospital Sejahtera")
    clinician = make_user(role="clinician", facility="Hospital Sejahtera")
    H = auth_headers(admin)

    open_a = _mk_alert(db_session, actor_facility="Hospital Sejahtera")
    ack_a = _mk_alert(db_session, actor_facility="Hospital Sejahtera", severity="error", category="patient_fanout")
    created = [open_a.id, ack_a.id]
    try:
        assert test_client.get("/admin/security-alerts", headers=auth_headers(clinician)).status_code == 403

        r = test_client.post(f"/admin/security-alerts/{ack_a.id}/acknowledge", headers=H)
        assert r.status_code == 200 and r.json()["acknowledged"] is True

        open_ids = {a["id"] for a in test_client.get("/admin/security-alerts?status=open", headers=H).json()}
        assert open_a.id in open_ids and ack_a.id not in open_ids

        errs = test_client.get("/admin/security-alerts?status=all&severity=error", headers=H).json()
        assert all(a["severity"] == "error" for a in errs) and ack_a.id in {a["id"] for a in errs}

        cats = test_client.get("/admin/security-alerts?status=all&category=patient_fanout", headers=H).json()
        assert {a["id"] for a in cats} == {ack_a.id}

        s = test_client.get("/admin/security-alerts/summary", headers=H).json()
        assert set(s) == {"open_total", "acknowledged", "by_category", "by_severity"}

        r = test_client.post(f"/admin/security-alerts/{open_a.id}/resolve", headers=H)
        assert r.status_code == 200 and r.json()["resolved"] is True

        assert test_client.post("/admin/security-alerts/nope/resolve", headers=H).status_code == 404
        assert test_client.get("/admin/security-alerts?status=weird", headers=H).status_code == 400
    finally:
        for aid in created:
            row = db_session.query(models.SecurityAlert).filter_by(id=aid).first()
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def test_admin_list_is_facility_scoped_by_actor_facility(test_client, make_user, auth_headers, db_session):
    admin_a = make_user(role="admin", facility="Facility A")
    platform_admin = make_user(role="admin", facility=None)
    H_a = auth_headers(admin_a)

    alert_a = _mk_alert(db_session, actor_facility="Facility A")
    alert_b = _mk_alert(db_session, actor_facility="Facility B")
    created = [alert_a.id, alert_b.id]
    try:
        seen_by_a = {a["id"] for a in test_client.get("/admin/security-alerts?status=all", headers=H_a).json()}
        assert alert_a.id in seen_by_a
        assert alert_b.id not in seen_by_a  # a facility admin only sees their own staff's alerts

        seen_by_platform = {a["id"] for a in test_client.get(
            "/admin/security-alerts?status=all", headers=auth_headers(platform_admin)).json()}
        assert {alert_a.id, alert_b.id} <= seen_by_platform
    finally:
        for aid in created:
            row = db_session.query(models.SecurityAlert).filter_by(id=aid).first()
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def test_cross_facility_mutations_404_not_leak(test_client, make_user, auth_headers, db_session):
    """A facility-scoped admin must not be able to acknowledge, resolve, or
    request an AI explanation for another facility's alert (or one with no
    actor_facility recorded) even if they somehow have its id -- same
    facility scope as list/summary, enforced in _get_security_alert_or_404.
    404, not 403, so the response doesn't confirm the row exists."""
    admin_a = make_user(role="admin", facility="Facility A")
    H_a = auth_headers(admin_a)

    alert_b = _mk_alert(db_session, actor_facility="Facility B")
    alert_none = _mk_alert(db_session, actor_facility=None)
    created = [alert_b.id, alert_none.id]
    try:
        for alert_id in (alert_b.id, alert_none.id):
            assert test_client.post(f"/admin/security-alerts/{alert_id}/acknowledge", headers=H_a).status_code == 404
            assert test_client.post(f"/admin/security-alerts/{alert_id}/resolve", headers=H_a).status_code == 404
            assert test_client.post(f"/admin/security-alerts/{alert_id}/explain", headers=H_a).status_code == 404

        db_session.refresh(alert_b)
        db_session.refresh(alert_none)
        assert alert_b.acknowledged is False and alert_b.resolved is False and alert_b.ai_explanation is None
        assert alert_none.acknowledged is False and alert_none.resolved is False
    finally:
        for aid in created:
            row = db_session.query(models.SecurityAlert).filter_by(id=aid).first()
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def test_explain_generates_and_caches_narrative(test_client, make_user, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ai.audit_intelligence.generate_text",
        lambda *a, **kw: "Worth checking whether this actor was on shift.",
    )
    admin = make_user(role="admin", facility="Hospital Sejahtera")
    alert = _mk_alert(db_session, actor_facility="Hospital Sejahtera")
    try:
        r = test_client.post(f"/admin/security-alerts/{alert.id}/explain", headers=auth_headers(admin))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ai_explanation"] == "Worth checking whether this actor was on shift."

        db_session.refresh(alert)
        assert alert.ai_explanation == "Worth checking whether this actor was on shift."
    finally:
        db_session.delete(db_session.query(models.SecurityAlert).filter_by(id=alert.id).first())
        db_session.commit()


def test_explain_degrades_to_none_when_local_llm_unavailable(test_client, make_user, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr("app.ai.audit_intelligence.generate_text", lambda *a, **kw: None)
    admin = make_user(role="admin", facility="Hospital Sejahtera")
    alert = _mk_alert(db_session, actor_facility="Hospital Sejahtera")
    try:
        r = test_client.post(f"/admin/security-alerts/{alert.id}/explain", headers=auth_headers(admin))
        assert r.status_code == 200, r.text
        assert r.json()["ai_explanation"] is None
    finally:
        db_session.delete(db_session.query(models.SecurityAlert).filter_by(id=alert.id).first())
        db_session.commit()
