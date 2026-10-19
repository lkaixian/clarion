"""Pending registration claims: several emails may claim one NRIC; the first verified wins,
the rest are rejected and their (inbox-proven) emails are flagged."""
import random
from datetime import date

from app import models
from conftest import _make_patient

NAME = "Aminah Binti Test"
PW = "Str0ng!Passw0rd#1"


def _setup(db, email="owner@example.com"):
    nric = f"900101-01-{random.randint(1000, 9999)}"
    return _make_patient(db, full_name=NAME, national_id=nric, date_of_birth=date(1990, 1, 1), email=email), nric


def _mail(monkeypatch):
    sent = []
    from app.routers import self_registration as sr
    monkeypatch.setattr(sr, "send_self_registration_otp_email", lambda to, code, name: sent.append((to, code)) or True)
    return sent


def _claim(client, nric, email, sent, name=NAME):
    r = client.post("/auth/self-register/claim/start", json={
        "national_id": nric, "full_name": name, "email": email})
    assert r.status_code == 200, r.text
    return sent[-1][1]


def _verify(client, nric, email, code, pw=PW):
    return client.post("/auth/self-register/claim/verify-otp", json={
        "national_id": nric, "email": email, "otp_code": code, "password": pw})


def test_other_email_stays_pending_and_cannot_sign_in(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session)
    r = _verify(test_client, nric, "me@example.com", _claim(test_client, nric, "me@example.com", sent))
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert db_session.query(models.User).filter_by(patient_id=p.id).count() == 0
    assert test_client.post("/auth/login", data={"username": nric, "password": PW}).status_code == 401


def test_first_verified_wins_rest_rejected_and_flagged(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session)
    _verify(test_client, nric, "scam1@example.com", _claim(test_client, nric, "scam1@example.com", sent))
    _claim(test_client, nric, "scam2@example.com", sent)  # never proves the inbox
    r = _verify(test_client, nric, "owner@example.com", _claim(test_client, nric, "owner@example.com", sent))
    assert r.status_code == 200 and r.json()["status"] == "approved"  # the record's own inbox
    assert r.json()["session"]["access_token"]
    st = {c.email: c.status for c in db_session.query(models.RegistrationClaim).filter_by(patient_id=p.id)}
    assert st == {"scam1@example.com": "rejected", "scam2@example.com": "rejected", "owner@example.com": "approved"}
    flagged = {f.email for f in db_session.query(models.FlaggedEmail).filter_by(patient_id=p.id)}
    assert flagged == {"scam1@example.com"}  # unverified inbox is not blacklisted; winner never is
    assert test_client.post("/auth/login", data={"username": nric, "password": PW}).status_code == 200


def test_verified_account_rejects_new_claims(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    _, nric = _setup(db_session)
    _verify(test_client, nric, "owner@example.com", _claim(test_client, nric, "owner@example.com", sent))
    r = test_client.post("/auth/self-register/claim/start", json={
        "national_id": nric, "full_name": NAME, "email": "late@example.com" })
    assert r.status_code == 409


def test_flagged_email_is_refused_later(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session)
    _verify(test_client, nric, "scamtest@example.com", _claim(test_client, nric, "scamtest@example.com", sent))
    _verify(test_client, nric, "owner@example.com", _claim(test_client, nric, "owner@example.com", sent))
    p2, nric2 = _setup(db_session, email=None)  # a different, still unverified patient
    r = test_client.post("/auth/self-register/claim/start", json={
        "national_id": nric2, "full_name": NAME, "email": "SCAMTEST@example.com" })
    assert r.status_code == 403 and "flagged" in r.json()["detail"]


def test_wrong_name_and_wrong_code_are_refused(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    _, nric = _setup(db_session)
    r = test_client.post("/auth/self-register/claim/start", json={
        "national_id": nric, "full_name": "SOMEONE ELSE", "email": "x@example.com" })
    assert r.status_code == 400
    _claim(test_client, nric, "x@example.com", sent)
    assert _verify(test_client, nric, "x@example.com", "000000").status_code == 400


def test_staff_approve_flags_the_others(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session, email=None)
    for e in ("a@example.com", "b@example.com"):
        _verify(test_client, nric, e, _claim(test_client, nric, e, sent))
    admin = make_user(role="admin")
    h = auth_headers(admin)
    rows = test_client.get(f"/auth/patients/{p.id}/registration-claims", headers=h).json()
    a = next(c for c in rows if c["email"] == "a@example.com")
    assert test_client.post(f"/auth/patients/{p.id}/registration-claims/{a['id']}/approve", headers=h).status_code == 200
    assert {f.email for f in db_session.query(models.FlaggedEmail).filter_by(patient_id=p.id)} == {"b@example.com"}
    assert test_client.post("/auth/login", data={"username": nric, "password": PW}).status_code == 200


def test_claims_endpoints_are_staff_only(test_client, db_session, make_user, auth_headers):
    p, _ = _setup(db_session)
    h = auth_headers(make_user(role="clinician"))
    assert test_client.get(f"/auth/patients/{p.id}/registration-claims", headers=h).status_code == 403


def test_restart_cannot_overwrite_password_or_revive_rejected(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session, email=None)
    # victim starts, an attacker who knows NRIC+name re-starts the same email: the password is only
    # ever set by whoever proves the inbox, so the attacker's start changes nothing.
    _claim(test_client, nric, "v@example.com", sent)
    code = _claim(test_client, nric, "v@example.com", sent)
    assert _verify(test_client, nric, "v@example.com", code, pw="Victim!Passw0rd#9").status_code == 200
    assert test_client.post("/auth/login", data={"username": nric, "password": PW}).status_code == 401
    # a decided (rejected) claim cannot be restarted
    c = db_session.query(models.RegistrationClaim).filter_by(patient_id=p.id).one()
    c.status = "rejected"; db_session.commit()
    r = test_client.post("/auth/self-register/claim/start", json={"national_id": nric, "full_name": NAME, "email": "v@example.com"})
    assert r.status_code == 403


def test_unverified_claims_do_not_fill_the_cap(test_client, db_session, monkeypatch):
    sent = _mail(monkeypatch)
    p, nric = _setup(db_session, email=None)
    for i in range(12):
        db_session.add(models.RegistrationClaim(patient_id=p.id, email=f"junk{i}@example.com", password_hash=""))
    db_session.commit()
    _claim(test_client, nric, "real@example.com", sent)  # still allowed: junk is unverified


def test_no_record_still_creates_a_pending_account(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = _mail(monkeypatch)
    nric = f"950505-14-{random.randint(1000, 9999)}"
    code = _claim(test_client, nric, "new@example.com", sent, name="  nur   aisyah ")
    p = db_session.query(models.Patient).filter_by(normalized_national_id=nric.replace("-", "")).one()
    assert p.provisional and p.full_name == "NUR AISYAH" and p.date_of_birth == "1995-05-05"
    r = _verify(test_client, nric, "new@example.com", code)
    assert r.json()["status"] == "pending"  # nobody has vouched for this identity yet
    h = auth_headers(make_user(role="records_officer"))
    cid = test_client.get(f"/auth/patients/{p.id}/registration-claims", headers=h).json()[0]["id"]
    assert test_client.post(f"/auth/patients/{p.id}/registration-claims/{cid}/approve", headers=h).status_code == 200
    db_session.refresh(p)
    assert not p.provisional
    assert test_client.post("/auth/login", data={"username": nric, "password": PW}).status_code == 200


def test_unparseable_nric_without_a_record_is_refused(test_client, db_session, monkeypatch):
    _mail(monkeypatch)
    r = test_client.post("/auth/self-register/claim/start", json={"national_id": "12345", "full_name": "X Y", "email": "q@example.com"})
    assert r.status_code == 400
