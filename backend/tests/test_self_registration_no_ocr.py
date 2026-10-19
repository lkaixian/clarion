"""Self-registration without the NRIC photo/OCR step (default): the code goes to the email
already on file, then the caller sets a password."""
from app import models
from conftest import _make_patient

import random


def _nric():
    return f"900101-01-{random.randint(1000, 9999)}"


def _patient(db, email="real.owner@example.com"):
    from datetime import date
    global NRIC
    NRIC = _nric()
    return _make_patient(db, full_name="Aminah Binti Test", national_id=NRIC,
                         date_of_birth=date(1990, 1, 1), email=email)


def _capture(monkeypatch):
    sent = []
    from app.routers import self_registration as sr
    monkeypatch.setattr(sr, "send_self_registration_otp_email",
                        lambda to, code, name: sent.append((to, code)) or True)
    return sent


def test_code_goes_to_email_on_file_never_to_the_caller_choice(test_client, db_session, monkeypatch):
    sent = _capture(monkeypatch)
    _patient(db_session)
    assert test_client.get("/auth/self-register/config").json() == {"photo_check": False}
    r = test_client.post("/auth/self-register/start", json={
        "national_id": NRIC, "full_name": "Aminah Binti Test", "email": "attacker@evil.example.org"})
    assert r.status_code == 200, r.text
    assert "email_hint" not in r.json()
    assert sent[0][0] == "real.owner@example.com"


def test_three_steps_to_an_account(test_client, db_session, monkeypatch):
    sent = _capture(monkeypatch)
    p = _patient(db_session)
    test_client.post("/auth/self-register/start", json={"national_id": NRIC, "full_name": "Aminah Binti Test"})
    v = test_client.post("/auth/self-register/verify-otp", json={"national_id": NRIC, "otp_code": sent[0][1]})
    assert v.status_code == 200 and v.json()["next_step"] == "complete"
    c = test_client.post("/auth/self-register/complete", json={
        "national_id": NRIC, "new_password": "Str0ng!Passw0rd#1", "completion_token": v.json()["completion_token"]})
    assert c.status_code == 200 and c.json()["access_token"]
    assert db_session.query(models.User).filter_by(patient_id=p.id).count() == 1


def test_no_email_on_file_is_a_clear_dead_end(test_client, db_session, monkeypatch):
    _capture(monkeypatch)
    _patient(db_session, email=None)
    r = test_client.post("/auth/self-register/start", json={"national_id": NRIC, "full_name": "Aminah Binti Test"})
    assert r.status_code == 400 and "no email" in r.json()["detail"].lower()


def test_wrong_code_does_not_open_complete(test_client, db_session, monkeypatch):
    _capture(monkeypatch)
    _patient(db_session)
    test_client.post("/auth/self-register/start", json={"national_id": NRIC, "full_name": "Aminah Binti Test"})
    assert test_client.post("/auth/self-register/verify-otp",
                            json={"national_id": NRIC, "otp_code": "000000"}).status_code == 400
    c = test_client.post("/auth/self-register/complete", json={"national_id": NRIC, "new_password": "Str0ng!Passw0rd#1"})
    assert c.status_code == 400


def test_verified_attempt_expires_and_is_single_use(test_client, db_session, monkeypatch):
    from datetime import datetime, timedelta, timezone
    sent = _capture(monkeypatch)
    p = _patient(db_session)
    body = {"national_id": NRIC, "full_name": "Aminah Binti Test"}
    test_client.post("/auth/self-register/start", json=body)
    test_client.post("/auth/self-register/verify-otp", json={"national_id": NRIC, "otp_code": sent[0][1]})
    # a repeat /start by someone who only knows NRIC+name must not reset the verified step
    test_client.post("/auth/self-register/start", json=body)
    row = db_session.query(models.SelfRegistrationAttempt).filter_by(patient_id=p.id).one()
    assert row.status == "otp_verified"
    row.photo_verification_deadline = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db_session.commit()
    done = {"national_id": NRIC, "new_password": "Str0ng!Passw0rd#1"}
    assert test_client.post("/auth/self-register/complete", json=done).status_code == 400  # expired
    assert db_session.query(models.User).filter_by(patient_id=p.id).count() == 0


def test_unknown_nric_and_existing_account_do_not_leak_on_nric_alone(test_client, db_session, monkeypatch):
    _capture(monkeypatch)
    unknown = test_client.post("/auth/self-register/start",
                               json={"national_id": "800202-02-9999", "full_name": "Nobody Here"})
    assert unknown.status_code == 400
    p = _patient(db_session)
    db_session.add(models.User(email=f"u-{p.id}@clarion.local", hashed_password="x", full_name=p.full_name,
                               role="patient", patient_id=p.id))
    db_session.commit()
    wrong = test_client.post("/auth/self-register/start", json={"national_id": NRIC, "full_name": "Somebody Else"})
    assert wrong.status_code == 400  # not 409: the account's existence is not told to a wrong name
    right = test_client.post("/auth/self-register/start", json={"national_id": NRIC, "full_name": "Aminah Binti Test"})
    assert right.status_code == 409
