"""Time-boxed community responder accounts (guard / volunteer): POST /admin/responders,
the emergency-only route allowlist in auth.get_current_user, the hard expiry
(every request / login / refresh), and per-read attribution in the audit log."""
import uuid
from datetime import datetime, timedelta, timezone

from app import models


def _naive_utc(**delta):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(**delta)


def _iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _admin(make_user, facility="Guard Hospital"):
    return make_user(role="admin", facility=facility)


def _create(test_client, auth_headers, admin, **overrides):
    body = {"full_name": "Guard Ali", "email": f"guard-{uuid.uuid4().hex[:8]}@example.com",
            "expires_at": _iso(days=7), **overrides}
    return test_client.post("/admin/responders", headers=auth_headers(admin), json=body)


def _responder_token(test_client, db_session, created):
    """Log the new responder in. The forced first-login password change is
    cleared directly (it has its own tests); everything else goes through the
    real login endpoint."""
    row = db_session.query(models.User).filter_by(id=created["id"]).first()
    row.must_change_password = False
    db_session.commit()
    resp = test_client.post("/auth/login", data={"username": created["email"], "password": created["temporary_password"]})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"], resp.json().get("refresh_token")


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_creates_a_time_boxed_responder_with_a_one_time_password(test_client, make_user, auth_headers, db_session):
    admin = _admin(make_user)
    resp = _create(test_client, auth_headers, admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["temporary_password"] and body["must_change_password"] is True and body["active"] is True
    assert body["facility"] == "Guard Hospital"
    row = db_session.query(models.User).filter_by(id=body["id"]).first()
    assert row.role == "emergency_responder" and row.access_expires_at is not None
    assert body["temporary_password"] not in (row.hashed_password or "")


def test_expiry_must_be_in_the_future_and_within_the_cap(test_client, make_user, auth_headers):
    admin = _admin(make_user)
    assert _create(test_client, auth_headers, admin, expires_at=_iso(hours=-1)).status_code == 400
    too_far = _create(test_client, auth_headers, admin, expires_at=_iso(days=400))
    assert too_far.status_code == 400 and "at most" in too_far.json()["detail"]
    assert _create(test_client, auth_headers, admin, expires_at=_iso(days=89)).status_code == 200


def test_expiry_without_a_timezone_is_refused_and_output_is_utc_aware(test_client, make_user, auth_headers):
    admin = _admin(make_user)
    naive = (datetime.now() + timedelta(days=3)).replace(microsecond=0).isoformat()  # no offset
    resp = _create(test_client, auth_headers, admin, expires_at=naive)
    assert resp.status_code == 400 and "timezone" in resp.json()["detail"]

    ok = _create(test_client, auth_headers, admin, expires_at="2099-01-01T00:00:00+08:00")
    assert ok.status_code == 400  # still capped, and the offset was understood
    good = _create(test_client, auth_headers, admin, expires_at=_iso(days=3)).json()
    assert good["access_expires_at"].endswith(("Z", "+00:00"))  # an unambiguous instant for the UI


def test_duplicate_email_is_a_clean_400(test_client, make_user, auth_headers):
    admin = _admin(make_user)
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    assert _create(test_client, auth_headers, admin, email=email).status_code == 200
    assert _create(test_client, auth_headers, admin, email=email).status_code == 400


def test_only_an_admin_can_manage_responders_and_register_cannot_make_one(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Guard Hospital")
    assert _create(test_client, auth_headers, clinician).status_code == 403
    assert test_client.get("/admin/responders", headers=auth_headers(clinician)).status_code == 403

    admin = _admin(make_user)
    resp = test_client.post("/auth/register", headers=auth_headers(admin), json={
        "email": f"x-{uuid.uuid4().hex[:6]}@example.com", "password": "LongEnoughPass123!",
        "full_name": "No Expiry", "role": "emergency_responder"})
    assert resp.status_code == 400 and "/admin/responders" in resp.json()["detail"]


def test_responders_are_scoped_to_the_admins_facility(test_client, make_user, auth_headers):
    admin_a = _admin(make_user, "Facility A")
    admin_b = _admin(make_user, "Facility B")
    created = _create(test_client, auth_headers, admin_a).json()

    assert [r["id"] for r in test_client.get("/admin/responders", headers=auth_headers(admin_a)).json()] == [created["id"]]
    assert test_client.get("/admin/responders", headers=auth_headers(admin_b)).json() == []
    other = test_client.patch(f"/admin/responders/{created['id']}", headers=auth_headers(admin_b),
                              json={"expires_at": _iso(days=3)})
    assert other.status_code == 404
    assert test_client.post(f"/admin/responders/{created['id']}/revoke", headers=auth_headers(admin_b)).status_code == 404


def test_a_responder_can_only_reach_the_emergency_routes(test_client, make_user, auth_headers, db_session):
    created = _create(test_client, auth_headers, _admin(make_user)).json()
    token, _ = _responder_token(test_client, db_session, created)
    h = _bearer(token)

    assert test_client.get("/auth/me", headers=h).status_code == 200
    keys = test_client.get("/emergency/tag-keys", headers=h)
    assert keys.status_code == 200
    # The device must stop using cached keys when the account's window ends.
    assert keys.json()["valid_until"].endswith("Z")

    for path in ("/patients", "/admin/responders", "/admin/staff", "/pharmacy/inventory"):
        assert test_client.get(path, headers=h).status_code == 403, path

    # /booking/categories asks for no role at all (any signed-in user passes), so
    # only the allowlist in get_current_user keeps a responder out of it.
    staff = make_user(role="clinician", facility="Guard Hospital")
    assert test_client.get("/booking/categories", headers=auth_headers(staff)).status_code == 200
    blocked = test_client.get("/booking/categories", headers=h)
    assert blocked.status_code == 403 and "limited to emergency" in blocked.json()["detail"]


def test_expired_account_is_cut_off_on_requests_login_and_refresh(test_client, make_user, auth_headers, db_session):
    created = _create(test_client, auth_headers, _admin(make_user)).json()
    token, refresh = _responder_token(test_client, db_session, created)
    assert test_client.get("/auth/me", headers=_bearer(token)).status_code == 200

    row = db_session.query(models.User).filter_by(id=created["id"]).first()
    row.access_expires_at = _naive_utc(minutes=-1)
    db_session.commit()

    r = test_client.get("/auth/me", headers=_bearer(token))
    assert r.status_code == 401 and "expired" in r.json()["detail"]
    login = test_client.post("/auth/login", data={"username": created["email"], "password": created["temporary_password"]})
    assert login.status_code == 403 and "access period" in login.json()["detail"]
    assert "login_refused_access_expired" in [
        a.action for a in db_session.query(models.AuditLog).filter_by(actor=created["id"])]
    if refresh:
        assert test_client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_revoke_ends_access_immediately_and_patch_can_revive_it(test_client, make_user, auth_headers, db_session):
    admin = _admin(make_user)
    created = _create(test_client, auth_headers, admin).json()
    token, _ = _responder_token(test_client, db_session, created)

    out = test_client.post(f"/admin/responders/{created['id']}/revoke", headers=auth_headers(admin))
    assert out.status_code == 200 and out.json()["active"] is False
    assert test_client.get("/auth/me", headers=_bearer(token)).status_code == 401

    back = test_client.patch(f"/admin/responders/{created['id']}", headers=auth_headers(admin),
                             json={"expires_at": _iso(days=2)})
    assert back.status_code == 200 and back.json()["active"] is True
    actions = [a.action for a in db_session.query(models.AuditLog).filter_by(actor=admin.id)]
    assert {"create_responder_account", "revoke_responder_account", "update_responder_expiry"} <= set(actions)


def test_a_responders_scan_is_attributed_to_their_account(test_client, make_user, auth_headers, db_session):
    patient = models.Patient(full_name="Scan Patient", date_of_birth="1980-01-01", blood_type="O+")
    db_session.add(patient)
    db_session.commit()
    clinician = make_user(role="clinician", facility="Issuer Hospital")
    ward = models.Ward(facility_name="Issuer Hospital", ward_name="W", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.add(models.Admission(facility_name="Issuer Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    card = test_client.post("/emergency/issue", headers=auth_headers(clinician),
                            json={"patient_id": patient.id}).json()["card_reference"]

    created = _create(test_client, auth_headers, _admin(make_user)).json()
    token, _ = _responder_token(test_client, db_session, created)
    resp = test_client.post("/emergency/scan", headers=_bearer(token),
                            json={"card_reference": card, "responder_name": "Guard Ali", "responder_org": "Estate security"})
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) >= {"full_name", "blood_type"}  # emergency-tier payload only

    rows = [r for r in db_session.query(models.AuditLog).filter_by(patient_id=patient.id)
            if r.action == "emergency_access"]
    assert rows[-1].actor == created["id"]  # the account, not a typed-in name
    assert rows[-1].actor_role == "emergency_responder"
    assert rows[-1].detail.startswith("verified")
