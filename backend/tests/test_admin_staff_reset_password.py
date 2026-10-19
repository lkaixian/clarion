"""Admin credential recovery: POST /admin/staff/{id}/reset-password, POST /auth/mfa/reset/{id},
GET /admin/admins, and db/reset_admin_password.py --reset-mfa / --mfa-only.

Rules under test: the ACTING admin re-enters their own password (+ authenticator code once
enrolled); only same-facility targets; never yourself; a reset password never touches the target's
authenticator; the temporary password is never audited."""
import sys

import pytest

from app import mfa, models


def _step(admin, code=""):
    return {"password": admin.plaintext_password, "code": code}


def _login(test_client, user, password):
    return test_client.post("/auth/login", data={"username": user.email, "password": password})


def _enrol_admin(test_client, admin):
    """Drive a forced enrolment for `admin`; returns (secret, access_token)."""
    ch = _login(test_client, admin, admin.plaintext_password).json()
    assert ch["mfa_required"] and ch["mfa_enrol"]
    start = test_client.post("/auth/mfa/enrol/start", json={"mfa_token": ch["mfa_token"]}).json()
    secret = start["secret"]
    done = test_client.post("/auth/mfa/enrol/confirm",
                            json={"mfa_token": ch["mfa_token"], "code": mfa.code_at(secret, mfa.current_step())})
    assert done.status_code == 200, done.text
    return secret, done.json()["access_token"]


# ---------------------------------------------------------------- staff reset
def test_admin_resets_staff_password(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility="Main Hospital")
    clinician = make_user(role="clinician", facility="Main Hospital")
    old = clinician.plaintext_password

    r = test_client.post(f"/admin/staff/{clinician.id}/reset-password",
                         headers=auth_headers(admin), json=_step(admin))
    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == "no-store"
    body = r.json()
    assert body["email"] == clinician.email and len(body["temporary_password"]) >= 20

    assert _login(test_client, clinician, old).status_code == 401
    assert _login(test_client, clinician, body["temporary_password"]).status_code == 200


def test_wrong_stepup_password_changes_nothing(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility="Main Hospital")
    clinician = make_user(role="clinician", facility="Main Hospital")
    r = test_client.post(f"/admin/staff/{clinician.id}/reset-password",
                         headers=auth_headers(admin), json={"password": "not-my-password", "code": ""})
    assert r.status_code == 400
    assert _login(test_client, clinician, clinician.plaintext_password).status_code == 200


def test_scope_other_facility_and_self_are_404_other_admin_allowed(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility="Main Hospital")
    elsewhere = make_user(role="clinician", facility="Other Clinic")
    other_admin = make_user(role="admin", facility="Main Hospital")
    h = auth_headers(admin)
    url = "/admin/staff/{}/reset-password"
    assert test_client.post(url.format(elsewhere.id), headers=h, json=_step(admin)).status_code == 404
    assert test_client.post(url.format(admin.id), headers=h, json=_step(admin)).status_code == 404
    assert test_client.post(url.format(other_admin.id), headers=h, json=_step(admin)).status_code == 200


def test_non_admin_cannot_reset(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Main Hospital")
    other = make_user(role="receptionist", facility="Main Hospital")
    r = test_client.post(f"/admin/staff/{other.id}/reset-password",
                         headers=auth_headers(clinician), json=_step(clinician))
    assert r.status_code == 403


def test_reset_is_audited_without_the_password(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Main Hospital")
    staff = make_user(role="receptionist", facility="Main Hospital")
    pw = test_client.post(f"/admin/staff/{staff.id}/reset-password",
                          headers=auth_headers(admin), json=_step(admin)).json()["temporary_password"]
    rows = db_session.query(models.AuditLog).filter(models.AuditLog.action == "admin_reset_staff_password").all()
    assert rows and all(pw not in (r.detail or "") for r in rows)


# ------------------------------------------------- enrolled admin needs a code
def test_enrolled_admin_must_supply_a_current_code(test_client, make_user, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "admin")
    admin = make_user(role="admin", facility="Main Hospital")
    victim = make_user(role="clinician", facility="Main Hospital")
    secret, token = _enrol_admin(test_client, admin)
    h = {"Authorization": f"Bearer {token}"}
    url = f"/admin/staff/{victim.id}/reset-password"

    assert test_client.post(url, headers=h, json=_step(admin, "")).status_code == 400  # password alone: no
    assert test_client.post(url, headers=h, json=_step(admin, "000000")).status_code == 400
    code = mfa.code_at(secret, mfa.current_step() + 1)  # next step: the enrolment code is burnt
    assert test_client.post(url, headers=h, json=_step(admin, code)).status_code == 200


def test_password_reset_never_touches_the_targets_authenticator(test_client, make_user, auth_headers, db_session, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "admin")
    a = make_user(role="admin", facility="Main Hospital")
    b = make_user(role="admin", facility="Main Hospital")
    sa, ta = _enrol_admin(test_client, a)
    _enrol_admin(test_client, b)
    h = {"Authorization": f"Bearer {ta}"}
    code = mfa.code_at(sa, mfa.current_step() + 1)
    r = test_client.post(f"/admin/staff/{b.id}/reset-password", headers=h, json=_step(a, code))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    row = db_session.query(models.User).filter_by(id=b.id).first()
    assert row.mfa_secret_enc is not None and row.mfa_enabled_at is not None
    # temp password alone is only the first factor: sign-in still demands the authenticator
    ch = _login(test_client, b, r.json()["temporary_password"]).json()
    assert ch.get("mfa_required") and not ch.get("mfa_enrol") and "access_token" not in ch


# ------------------------------------------------------------- MFA reset
def test_mfa_reset_needs_stepup_and_blocks_self(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="F")
    other = make_user(role="admin", facility="F")
    h = auth_headers(admin)
    assert test_client.post(f"/auth/mfa/reset/{other.id}", headers=h,
                            json={"password": "nope", "code": ""}).status_code == 400
    assert test_client.post(f"/auth/mfa/reset/{admin.id}", headers=h, json=_step(admin)).status_code == 400
    assert test_client.post(f"/auth/mfa/reset/{other.id}", headers=h, json=_step(admin)).status_code == 200


def test_list_admins_excludes_self_and_other_facilities(test_client, make_user, auth_headers):
    me = make_user(role="admin", facility="Main Hospital")
    peer = make_user(role="admin", facility="Main Hospital")
    make_user(role="admin", facility="Other Clinic")
    ids = [a["id"] for a in test_client.get("/admin/admins", headers=auth_headers(me)).json()]
    assert ids == [peer.id]


# --------------------------------------------------- break-glass script
def _run_script(monkeypatch, *args):
    from db import reset_admin_password as script
    monkeypatch.setattr(sys, "argv", ["reset_admin_password.py", *args])
    return script.main()


def test_script_mfa_only_clears_authenticator_and_keeps_password(test_client, make_user, db_session, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "admin")
    admin = make_user(role="admin", facility="Main Hospital")
    _enrol_admin(test_client, admin)
    assert _run_script(monkeypatch, admin.email, "--mfa-only") == 0
    db_session.expire_all()
    row = db_session.query(models.User).filter_by(id=admin.id).first()
    assert row.mfa_secret_enc is None and row.mfa_enabled_at is None
    ch = _login(test_client, admin, admin.plaintext_password).json()   # same password still works
    assert ch["mfa_required"] and ch["mfa_enrol"]                      # and it is asked to enrol again


def test_script_reset_mfa_changes_password_too(test_client, make_user, db_session, monkeypatch):
    admin = make_user(role="admin", facility="Main Hospital")
    assert _run_script(monkeypatch, admin.email, "--reset-mfa") == 0
    assert _login(test_client, admin, admin.plaintext_password).status_code == 401


# ------------------------------------------------ review-driven hardening
def test_facility_less_admin_cannot_reset_anyones_mfa(test_client, make_user, auth_headers):
    nowhere = make_user(role="admin", facility=None)
    victim = make_user(role="admin", facility="Main Hospital")
    r = test_client.post(f"/auth/mfa/reset/{victim.id}", headers=auth_headers(nowhere), json=_step(nowhere))
    assert r.status_code == 400


def test_cannot_clear_mfa_while_a_temporary_password_is_outstanding(test_client, make_user, auth_headers, db_session):
    a = make_user(role="admin", facility="Main Hospital")
    b = make_user(role="admin", facility="Main Hospital")
    ha = auth_headers(a)
    assert test_client.post(f"/admin/staff/{b.id}/reset-password", headers=ha, json=_step(a)).status_code == 200
    # b now holds a temp password (must_change_password): clearing b's authenticator would be an enrol-hijack
    r = test_client.post(f"/auth/mfa/reset/{b.id}", headers=ha, json=_step(a))
    assert r.status_code == 409
    db_session.expire_all()


def test_admin_without_authenticator_is_not_resettable_when_mfa_is_required(test_client, make_user, auth_headers, monkeypatch):
    a = make_user(role="admin", facility="Main Hospital")
    b = make_user(role="admin", facility="Main Hospital")
    ha = auth_headers(a)                       # a signs in before the policy is switched on
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "admin")
    r = test_client.post(f"/admin/staff/{b.id}/reset-password", headers=ha, json=_step(a))
    assert r.status_code == 409                # b has no authenticator: enrol-hijack, server-side only


def test_mfa_reset_evicts_the_targets_live_access_token(test_client, make_user, auth_headers):
    a = make_user(role="admin", facility="F")
    victim = make_user(role="clinician", facility="F")
    hv = auth_headers(victim)
    assert test_client.get("/auth/sessions", headers=hv).status_code == 200
    assert test_client.post(f"/auth/mfa/reset/{victim.id}", headers=auth_headers(a), json=_step(a)).status_code == 200
    assert test_client.get("/auth/sessions", headers=hv).status_code == 401


def test_script_rejects_conflicting_flags(test_client, make_user, monkeypatch):
    admin = make_user(role="admin", facility="Main Hospital")
    assert _run_script(monkeypatch, admin.email, "--mfa-only", "--reset-mfa") == 2
