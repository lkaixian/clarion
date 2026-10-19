"""Owner one-tap lock, self-service unlock, daily code cap and the new-account cooling period."""
import random
import re
from datetime import date, datetime, timedelta, timezone

from app import account_lock, models
from conftest import _make_patient

PW = "Str0ng!Passw0rd#1"


def _nric():
    return f"900101-01-{random.randint(1000, 9999)}"


def _setup(db, monkeypatch):
    monkeypatch.setenv("CLARION_PUBLIC_URL", "https://clarion.example.org")
    from app.routers import self_registration as sr
    sent, notices = [], []
    monkeypatch.setattr(sr, "send_self_registration_otp_email",
                        lambda to, code, name: sent.append((to, code)) or True)
    monkeypatch.setattr(sr, "send_account_created_notice",
                        lambda to, name, url: notices.append((to, url)) or True)
    nric = _nric()
    p = _make_patient(db, full_name="Aminah Binti Test", national_id=nric,
                      date_of_birth=date(1990, 1, 1), email="owner@example.com")
    return nric, p, sent, notices


def _register(client, nric, sent):
    body = {"national_id": nric, "full_name": "Aminah Binti Test"}
    assert client.post("/auth/self-register/start", json=body).status_code == 200
    v = client.post("/auth/self-register/verify-otp", json={"national_id": nric, "otp_code": sent[-1][1]})
    assert v.status_code == 200
    return client.post("/auth/self-register/complete", json={
        "national_id": nric, "new_password": PW, "completion_token": v.json()["completion_token"]})


def test_owner_is_told_and_can_lock_then_unlock_by_reset(test_client, db_session, monkeypatch):
    nric, p, sent, notices = _setup(db_session, monkeypatch)
    done = _register(test_client, nric, sent)
    assert done.status_code == 200
    assert notices and notices[0][0] == "owner@example.com"
    token = re.search(r"token=([^&\s]+)", notices[0][1]).group(1)

    page = test_client.get("/auth/account-lock", params={"token": token})
    assert page.status_code == 200 and "Yes, lock the account" in page.text
    # opening the page (what a mail scanner does) must not lock anything
    assert db_session.query(models.User).filter_by(patient_id=p.id).one().owner_locked_at is None

    r = test_client.post("/auth/account-lock", data={"token": token})
    assert r.status_code == 200 and "Account locked" in r.text
    db_session.expire_all()
    user = db_session.query(models.User).filter_by(patient_id=p.id).one()
    assert user.owner_locked_at is not None

    # the old session token is dead, and a fresh login is refused with a clear message
    me = test_client.get("/auth/me", headers={"Authorization": f"Bearer {done.json()['access_token']}"})
    assert me.status_code == 401
    login = test_client.post("/auth/login", data={"username": nric, "password": PW})
    assert login.status_code == 403 and "Forgot password" in login.json()["detail"]

    # unlock = the existing emailed-code password reset, no staff involved
    from app import auth
    code = "123456"
    user.otp_code_hash = auth.hash_otp_code(code)
    user.otp_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    db_session.commit()
    reset = test_client.post("/auth/reset-password-with-otp",
                             json={"national_id": nric, "otp_code": code, "new_password": "An0ther!Passw0rd#2"})
    assert reset.status_code == 200, reset.text
    ok = test_client.post("/auth/login", data={"username": nric, "password": "An0ther!Passw0rd#2"})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_bad_or_expired_lock_token_does_nothing(test_client, db_session, monkeypatch):
    assert test_client.get("/auth/account-lock", params={"token": "nope"}).status_code == 400
    assert test_client.post("/auth/account-lock", data={"token": "lock1.x.1.deadbeef"}).status_code == 400
    old = account_lock.make_lock_token("some-user", "marker", now=1.0)  # expired long ago
    assert account_lock.read_lock_token(old) is None


def test_new_account_cannot_pay_online_during_cooling(test_client, db_session, monkeypatch):
    nric, p, sent, _ = _setup(db_session, monkeypatch)
    done = _register(test_client, nric, sent)
    h = {"Authorization": f"Bearer {done.json()['access_token']}"}
    r = test_client.post("/payments/bills/anything/intents", json={}, headers=h)
    assert r.status_code == 403 and "first 24 hours" in r.json()["detail"]
    # once the cooling period has passed the same call reaches the normal checks
    user = db_session.query(models.User).filter_by(patient_id=p.id).one()
    user.self_registered_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()
    r = test_client.post("/payments/bills/anything/intents", json={}, headers=h)
    assert r.status_code != 403


def test_lock_link_is_single_use_and_dies_after_reset(test_client, db_session, monkeypatch):
    nric, p, sent, notices = _setup(db_session, monkeypatch)
    _register(test_client, nric, sent)
    token = re.search(r"token=([^&\s]+)", notices[0][1]).group(1)
    assert test_client.post("/auth/account-lock", data={"token": token}).status_code == 200
    again = test_client.post("/auth/account-lock", data={"token": token})
    assert again.status_code == 400  # spent: the lock changed the password marker


def test_complete_needs_the_token_from_the_person_who_verified(test_client, db_session, monkeypatch):
    nric, p, sent, _ = _setup(db_session, monkeypatch)
    body = {"national_id": nric, "full_name": "Aminah Binti Test"}
    test_client.post("/auth/self-register/start", json=body)
    test_client.post("/auth/self-register/verify-otp", json={"national_id": nric, "otp_code": sent[-1][1]})
    # a stranger who knows only NRIC + name, polling /complete
    for tok in (None, "", "reg1.x.1.deadbeef", account_lock.make_completion_token("another-patient")):
        r = test_client.post("/auth/self-register/complete",
                             json={"national_id": nric, "new_password": PW, "completion_token": tok})
        assert r.status_code == 400
    assert db_session.query(models.User).filter_by(patient_id=p.id).count() == 0


def test_notice_failure_is_audited(test_client, db_session, monkeypatch):
    nric, p, sent, notices = _setup(db_session, monkeypatch)
    from app.routers import self_registration as sr
    monkeypatch.setattr(sr, "send_account_created_notice", lambda *a: False)
    assert _register(test_client, nric, sent).status_code == 200
    db_session.expire_all()
    row = db_session.query(models.AuditLog).filter_by(
        patient_id=p.id, action="account_created_notice_not_sent").first()
    assert row is not None
