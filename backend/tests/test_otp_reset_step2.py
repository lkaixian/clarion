"""Code-review follow-up 2026-09-07 -- POST /auth/reset-password-with-otp
(step 2 of the email-OTP reset) had almost no coverage, despite a documented
bug history (commit 873595c "Fixing OTP Reset Password Loophole").
test_login_rate_limiting.py only exercised the step-1 REQUEST rate limit.

Covers: successful reset actually changes the password + clears the OTP,
5 wrong guesses invalidate the live OTP, an expired OTP is rejected and
cleared, and the failure responses are enumeration-identical.
"""
from datetime import datetime, timedelta, timezone

from app import auth, models


def _patient_with_login(db_session, nric="880808-08-8888", password="OldPass123456"):
    patient = models.Patient(full_name="OTP Test", date_of_birth="1988-08-08", national_id=nric)
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    user = models.User(
        email=f"otp-{patient.id}@example.com",
        hashed_password=auth.hash_password(password),
        full_name="OTP Test",
        role="patient",
        patient_id=patient.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return patient, user


def _arm_otp(db_session, user, code="123456", ttl_minutes=10):
    db_session.query(models.User).filter_by(id=user.id).update({
        "otp_code_hash": auth.hash_otp_code(code),
        "otp_expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=ttl_minutes),
        "otp_attempt_count": 0,
    })
    db_session.commit()


def test_successful_reset_changes_password_and_clears_otp(test_client, db_session):
    patient, user = _patient_with_login(db_session, nric="880808-08-0001")
    _arm_otp(db_session, user, code="654321")

    resp = test_client.post("/auth/reset-password-with-otp", json={
        "national_id": "880808-08-0001", "otp_code": "654321", "new_password": "FreshPass987654",
    })
    assert resp.status_code == 200, resp.text

    row = db_session.query(models.User).filter_by(id=user.id).first()
    assert row.otp_code_hash is None and row.otp_expires_at is None
    assert auth.verify_password("FreshPass987654", row.hashed_password)
    assert not auth.verify_password("OldPass123456", row.hashed_password)

    # The new password actually logs in.
    login = test_client.post("/auth/login", data={"username": user.email, "password": "FreshPass987654"})
    assert login.status_code == 200


def test_five_wrong_codes_invalidate_the_live_otp(test_client, db_session):
    patient, user = _patient_with_login(db_session, nric="880808-08-0002")
    _arm_otp(db_session, user, code="111111")

    for _ in range(auth.OTP_MAX_VERIFY_ATTEMPTS):
        r = test_client.post("/auth/reset-password-with-otp", json={
            "national_id": "880808-08-0002", "otp_code": "000000", "new_password": "Whatever123456",
        })
        assert r.status_code == 400

    row = db_session.query(models.User).filter_by(id=user.id).first()
    assert row.otp_code_hash is None  # burned

    # Even the CORRECT code no longer works -- must request a fresh one.
    r = test_client.post("/auth/reset-password-with-otp", json={
        "national_id": "880808-08-0002", "otp_code": "111111", "new_password": "Whatever123456",
    })
    assert r.status_code == 400


def test_expired_otp_is_rejected_and_cleared(test_client, db_session):
    patient, user = _patient_with_login(db_session, nric="880808-08-0003")
    _arm_otp(db_session, user, code="222222", ttl_minutes=-1)  # already expired

    r = test_client.post("/auth/reset-password-with-otp", json={
        "national_id": "880808-08-0003", "otp_code": "222222", "new_password": "Whatever123456",
    })
    assert r.status_code == 400
    row = db_session.query(models.User).filter_by(id=user.id).first()
    assert row.otp_code_hash is None


def test_unknown_nric_and_wrong_code_return_identical_errors(test_client, db_session):
    patient, user = _patient_with_login(db_session, nric="880808-08-0004")
    _arm_otp(db_session, user, code="333333")

    unknown = test_client.post("/auth/reset-password-with-otp", json={
        "national_id": "000000-00-0000", "otp_code": "333333", "new_password": "Whatever123456",
    })
    wrong_code = test_client.post("/auth/reset-password-with-otp", json={
        "national_id": "880808-08-0004", "otp_code": "999999", "new_password": "Whatever123456",
    })
    assert unknown.status_code == wrong_code.status_code == 400
    assert unknown.json() == wrong_code.json()
