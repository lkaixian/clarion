"""Security Audit findings M1/M2 — per-IP rate limits on POST /auth/login
and the OTP/self-registration endpoints (previously all @limiter.exempt,
with zero per-IP protection), plus the M1 lockout-counter-never-resets bug
in auth_router.login().
"""
from datetime import datetime, timedelta

from app import models
from app.auth import LOGIN_MAX_ATTEMPTS


def test_login_is_rate_limited_per_ip(test_client, make_user):
    """POST /auth/login used to be @limiter.exempt (no per-IP limit at
    all). Enough requests against DIFFERENT, non-existent identifiers must
    now trip the 20/minute per-IP limit with a 429 -- distinct from the
    401s a real password-spraying run would otherwise get indefinitely."""
    statuses = []
    for i in range(25):
        resp = test_client.post(
            "/auth/login", data={"username": f"nonexistent-{i}@example.com", "password": "whatever"}
        )
        statuses.append(resp.status_code)
    assert 401 in statuses  # unknown identifiers still get the generic failure...
    assert 429 in statuses  # ...but the per-IP limit eventually engages


def test_lockout_counter_resets_after_lock_lapses_not_on_next_wrong_guess(
    test_client, make_user, db_session
):
    """Security Audit M1: previously, once a lock LAPSED, login_failed_count
    stayed at its old (>= LOGIN_MAX_ATTEMPTS) value -- so a SINGLE further
    wrong guess re-triggered the >= MAX check immediately and re-locked the
    account for another full LOGIN_LOCKOUT_MINUTES, letting an attacker who
    merely knows the identifier keep it locked out forever with one request
    every LOGIN_LOCKOUT_MINUTES. A lapsed lock must instead be a fresh
    start: one more wrong guess should NOT re-lock; it should take a full
    new run of LOGIN_MAX_ATTEMPTS wrong guesses."""
    user = make_user(role="clinician", facility="Facility A")

    # Manually put the account into an already-lapsed lock state (as if
    # LOGIN_MAX_ATTEMPTS wrong guesses happened a while ago and the
    # cooldown has since passed).
    user.login_failed_count = LOGIN_MAX_ATTEMPTS
    user.login_locked_until = datetime.utcnow() - timedelta(minutes=1)
    db_session.add(user)
    db_session.commit()

    # One further wrong guess, post-lapse.
    resp = test_client.post("/auth/login", data={"username": user.email, "password": "WRONG"})
    assert resp.status_code == 401  # not 429 -- must NOT be locked out again immediately

    db_session.expire_all()
    refreshed = db_session.query(models.User).filter_by(id=user.id).first()
    assert refreshed.login_failed_count == 1  # reset-then-incremented-once, not accumulated
    assert refreshed.login_locked_until is None  # still not re-locked after just one guess

    # The CORRECT password must still work right after -- the account was
    # never really re-locked.
    good = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    assert good.status_code == 200


def test_lockout_still_engages_after_a_full_new_run_of_wrong_guesses_post_lapse(
    test_client, make_user, db_session
):
    """Companion to the above -- the reset isn't a free pass forever; a
    FULL new run of LOGIN_MAX_ATTEMPTS wrong guesses after the lapse must
    still re-lock the account."""
    user = make_user(role="clinician", facility="Facility A")
    user.login_failed_count = LOGIN_MAX_ATTEMPTS
    user.login_locked_until = datetime.utcnow() - timedelta(minutes=1)
    db_session.add(user)
    db_session.commit()

    for _ in range(LOGIN_MAX_ATTEMPTS - 1):
        resp = test_client.post("/auth/login", data={"username": user.email, "password": "WRONG"})
        assert resp.status_code == 401

    final = test_client.post("/auth/login", data={"username": user.email, "password": "WRONG"})
    assert final.status_code == 401  # the LOGIN_MAX_ATTEMPTS-th wrong guess itself still 401s

    db_session.expire_all()
    refreshed = db_session.query(models.User).filter_by(id=user.id).first()
    assert refreshed.login_locked_until is not None
    assert refreshed.login_locked_until > datetime.utcnow()

    locked_out = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    assert locked_out.status_code == 429


def test_password_reset_otp_request_is_rate_limited_per_ip(test_client):
    statuses = [
        test_client.post("/auth/request-password-reset-otp", json={"national_id": f"99010101{i:04d}"}).status_code
        for i in range(15)
    ]
    assert 429 in statuses


def test_normalized_national_id_kept_in_sync_by_model_validator(db_session):
    """Security Audit M2's indexed lookup only works if
    normalized_national_id is actually populated -- this must hold for ANY
    Patient construction, not just the one endpoint that happens to set it
    today (see models.Patient._sync_normalized_national_id)."""
    patient = models.Patient(
        full_name="Validator Test", date_of_birth="1990-01-01", national_id="990101-01-2345",
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    assert patient.normalized_national_id == "990101012345"

    # Blank/None national_id must stay NULL, never "" (multiple ""s would
    # collide on the unique constraint).
    patient2 = models.Patient(full_name="No NRIC", date_of_birth="1990-01-01")
    db_session.add(patient2)
    db_session.commit()
    assert patient2.normalized_national_id is None
