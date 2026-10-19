"""TOTP MFA + session management (app/mfa.py, routers/auth_security.py)."""
import pytest

from app import auth, mfa, models


@pytest.fixture(autouse=True)
def _mfa_for_clinicians(monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "clinician")


def _login(client, user, password=None):
    return client.post("/auth/login", data={
        "username": user.email, "password": password or user.plaintext_password})


def _enrol(client, user):
    """Drive a forced enrolment; returns (secret, token_json_with_codes)."""
    ch = _login(client, user).json()
    assert ch["mfa_required"] and ch["mfa_enrol"] and "access_token" not in ch
    start = client.post("/auth/mfa/enrol/start", json={"mfa_token": ch["mfa_token"]}).json()
    secret = start["secret"]
    code = mfa.code_at(secret, mfa.current_step())
    done = client.post("/auth/mfa/enrol/confirm", json={"mfa_token": ch["mfa_token"], "code": code})
    assert done.status_code == 200, done.text
    return secret, done.json()


def test_no_policy_means_no_challenge(test_client, make_user, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "")
    u = make_user(role="clinician", facility="F")
    assert "access_token" in _login(test_client, u).json()


def test_forced_enrolment_then_verify_flow(test_client, make_user):
    u = make_user(role="clinician", facility="F")
    secret, done = _enrol(test_client, u)
    assert done["access_token"] and len(done["recovery_codes"]) == 8

    # Enrolled now: login is a verify challenge, no token.
    ch = _login(test_client, u).json()
    assert ch["mfa_required"] and not ch["mfa_enrol"] and "access_token" not in ch

    # Same TOTP step as enrolment consumed -> replay rejected.
    replay = mfa.code_at(secret, mfa.current_step())
    r = test_client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": replay})
    assert r.status_code in (401, 429)  # burnt code, or the account lockout fired first
    assert "access_token" not in r.json()

    # Next step is acceptable (inside the +/-1 window).
    nxt = mfa.code_at(secret, mfa.current_step() + 1)
    ok = test_client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": nxt})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_recovery_code_works_once(test_client, make_user):
    u = make_user(role="clinician", facility="F")
    _, done = _enrol(test_client, u)
    code = done["recovery_codes"][0]
    ch = _login(test_client, u).json()
    assert test_client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": code}).status_code == 200
    ch2 = _login(test_client, u).json()
    assert test_client.post("/auth/mfa/verify", json={"mfa_token": ch2["mfa_token"], "code": code}).status_code == 401


def test_wrong_codes_lock_the_account(test_client, make_user):
    u = make_user(role="clinician", facility="F")
    _enrol(test_client, u)
    ch = _login(test_client, u).json()
    statuses = [
        test_client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": "000000"}).status_code
        for _ in range(auth.LOGIN_MAX_ATTEMPTS + 1)
    ]
    assert statuses[0] == 401 and statuses[-1] == 429


def test_challenge_token_is_not_an_access_token(test_client, make_user):
    u = make_user(role="clinician", facility="F")
    ch = _login(test_client, u).json()
    r = test_client.get("/auth/me", headers={"Authorization": f"Bearer {ch['mfa_token']}"})
    assert r.status_code in (401, 429)  # burnt code, or the account lockout fired first
    assert "access_token" not in r.json()


def test_challenge_token_tampering_and_expiry():
    tok = mfa.make_challenge("user-1", "verify", now=1_000_000)
    assert mfa.read_challenge(tok, now=1_000_100)[:2] == ("user-1", "verify")
    assert mfa.read_challenge(tok, now=1_000_000 + mfa.CHALLENGE_TTL_SECONDS + 5) is None
    assert mfa.read_challenge(tok.replace("user-1", "user-2"), now=1_000_100) is None
    assert mfa.read_challenge("garbage") is None


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, secret "12345678901234567890", T=59 -> 94287082 (8 digits);
    # our 6-digit code is its last six digits.
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert mfa.code_at(secret, 59 // 30) == "287082"


def test_optional_mfa_can_be_enabled_and_disabled_by_a_non_required_role(test_client, make_user, auth_headers):
    u = make_user(role="pharmacist", facility="F")
    h = auth_headers(u)
    assert test_client.post("/auth/mfa/setup/start", headers=h, json={"password": "wrong"}).status_code == 400
    start = test_client.post("/auth/mfa/setup/start", headers=h, json={"password": u.plaintext_password}).json()
    code = mfa.code_at(start["secret"], mfa.current_step())
    conf = test_client.post("/auth/mfa/setup/confirm", headers=h, json={"mfa_token": "x", "code": code})
    assert conf.status_code == 200 and len(conf.json()["recovery_codes"]) == 8
    assert test_client.get("/auth/mfa/status", headers=h).json()["enabled"] is True

    ch = _login(test_client, u).json()  # enrolled -> challenged even without a role policy
    assert ch["mfa_required"]

    nxt = mfa.code_at(start["secret"], mfa.current_step() + 1)
    verified = test_client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": nxt}).json()
    h2 = {"Authorization": f"Bearer {verified['access_token']}"}
    later = mfa.code_at(start["secret"], mfa.current_step() + 1)  # same step already used
    r = test_client.post("/auth/mfa/disable", headers=h2, json={"password": u.plaintext_password, "code": later})
    assert r.status_code == 400  # replayed step (400, not 401: never read as "session expired")


def test_required_role_cannot_disable_mfa(test_client, make_user):
    u = make_user(role="clinician", facility="F")
    _, done = _enrol(test_client, u)
    h = {"Authorization": f"Bearer {done['access_token']}"}
    r = test_client.post("/auth/mfa/disable", headers=h,
                         json={"password": u.plaintext_password, "code": done["recovery_codes"][0]})
    assert r.status_code == 403


def test_sessions_list_and_revoke(test_client, make_user, auth_headers):
    u = make_user(role="pharmacist", facility="F")
    a = auth_headers(u)  # login #1
    test_client.cookies.clear()
    auth_headers(u)      # login #2 (another device)
    listed = test_client.get("/auth/sessions", headers=a).json()
    assert len(listed) >= 2 and all("ip" in s for s in listed)

    one = listed[0]["id"]
    assert test_client.delete(f"/auth/sessions/{one}", headers=a).status_code == 200
    assert len(test_client.get("/auth/sessions", headers=a).json()) == len(listed) - 1

    r = test_client.post("/auth/sessions/revoke-others", headers=a)
    assert r.status_code == 200
    assert len(test_client.get("/auth/sessions", headers=a).json()) <= 1  # only this device survives


def test_admin_can_reset_a_users_mfa(test_client, make_user, auth_headers, db_session):
    victim = make_user(role="clinician", facility="F")
    _enrol(test_client, victim)
    admin = make_user(role="admin", facility="F")
    r = test_client.post(f"/auth/mfa/reset/{victim.id}", headers=auth_headers(admin),
                         json={"password": admin.plaintext_password, "code": ""})
    assert r.status_code == 200
    db_session.expire_all()
    row = db_session.query(models.User).filter_by(id=victim.id).first()
    assert row.mfa_secret_enc is None and row.mfa_enabled_at is None
    # They are asked to enrol again.
    assert _login(test_client, victim).json()["mfa_enrol"] is True


def test_secret_blob_is_bound_to_its_owner():
    blob = mfa.encrypt_secret("JBSWY3DPEHPK3PXP", "user-a")
    assert blob.startswith("v1:")
    assert mfa.decrypt_secret(blob, "user-a") == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ValueError):
        mfa.decrypt_secret(blob, "user-b")  # copied into another user's row


def test_password_change_invalidates_an_inflight_challenge(test_client, make_user, db_session):
    from datetime import datetime, timezone
    u = make_user(role="clinician", facility="F")
    ch = _login(test_client, u).json()
    row = db_session.query(models.User).filter_by(id=u.id).first()
    row.password_changed_at = datetime.now(timezone.utc)
    db_session.commit()
    r = test_client.post("/auth/mfa/enrol/start", json={"mfa_token": ch["mfa_token"]})
    assert r.status_code in (401, 429)  # burnt code, or the account lockout fired first
    assert "access_token" not in r.json()


def test_refresh_from_before_mfa_policy_is_not_honoured(test_client, make_user, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "")
    u = make_user(role="clinician", facility="F")
    r = _login(test_client, u)
    assert r.status_code == 200 and "access_token" in r.json()
    # Policy turns on after this session was minted without a second factor.
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "clinician")
    assert test_client.post("/auth/refresh").status_code == 401


def test_session_revoke_follows_the_rotation_chain(test_client, make_user, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "")
    u = make_user(role="pharmacist", facility="F")
    tok = _login(test_client, u).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    shown = test_client.get("/auth/sessions", headers=h).json()[0]["id"]

    # The device refreshes (as it does every 15 min): the shown id is now an
    # already-revoked ancestor of the live token.
    assert test_client.post("/auth/refresh").status_code == 200
    assert test_client.delete(f"/auth/sessions/{shown}", headers=h).status_code == 200
    assert test_client.post("/auth/refresh").status_code == 401  # the live successor died too


def test_revoke_others_without_knowing_the_current_session_is_refused(test_client, make_user, auth_headers):
    u = make_user(role="pharmacist", facility="F")
    h = auth_headers(u)
    test_client.cookies.clear()
    assert test_client.post("/auth/sessions/revoke-others", headers=h).status_code == 400


# ---- email second factor ------------------------------------------------------

def _capture_email(monkeypatch):
    sent = []
    from app.routers import auth_security
    monkeypatch.setattr(auth_security, "send_mfa_email_code",
                        lambda to, name, code: sent.append((to, code)) or True)
    return sent


def test_email_code_completes_login_once(test_client, make_user, monkeypatch):
    sent = _capture_email(monkeypatch)
    u = make_user(role="clinician", facility="F")
    ch = _login(test_client, u).json()
    assert ch["email_available"] and ch["email_hint"].startswith(u.email[0] + "***@")

    r = test_client.post("/auth/mfa/email/send", json={"mfa_token": ch["mfa_token"]})
    assert r.status_code == 200 and sent[0][0] == u.email
    code = sent[0][1]
    bad = test_client.post("/auth/mfa/email/verify", json={"mfa_token": ch["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = test_client.post("/auth/mfa/email/verify", json={"mfa_token": ch["mfa_token"], "code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    again = test_client.post("/auth/mfa/email/verify", json={"mfa_token": ch["mfa_token"], "code": code})
    assert again.status_code == 401  # single use


def test_email_code_not_offered_to_excluded_role(test_client, make_user, monkeypatch):
    sent = _capture_email(monkeypatch)
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "clinician,admin")
    admin = make_user(role="admin", facility="F")
    ch = _login(test_client, admin).json()
    assert ch["email_available"] is False
    assert test_client.post("/auth/mfa/email/send", json={"mfa_token": ch["mfa_token"]}).status_code == 400
    assert test_client.post("/auth/mfa/email/verify",
                            json={"mfa_token": ch["mfa_token"], "code": "123456"}).status_code == 400
    assert sent == []


def test_email_code_expires_and_wrong_codes_burn_it(test_client, make_user, monkeypatch, db_session):
    sent = _capture_email(monkeypatch)
    u = make_user(role="clinician", facility="F")
    ch = _login(test_client, u).json()
    test_client.post("/auth/mfa/email/send", json={"mfa_token": ch["mfa_token"]})
    code = sent[0][1]
    for _ in range(5):  # OTP_MAX_VERIFY_ATTEMPTS wrong tries invalidate the code
        test_client.post("/auth/mfa/email/verify", json={"mfa_token": ch["mfa_token"], "code": "111111"})
    r = test_client.post("/auth/mfa/email/verify", json={"mfa_token": ch["mfa_token"], "code": code})
    assert r.status_code in (401, 429)  # burnt code, or the account lockout fired first
    assert "access_token" not in r.json()
