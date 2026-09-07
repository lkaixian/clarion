"""P2.5 (Security Audit M4) — short-lived access token + long-lived
refresh token (HttpOnly cookie for the web client, JSON body field for a
native client), with rotation and reuse-detection, plus real server-side
logout and password-change-revokes-everywhere.
"""
from app import models


def test_login_sets_httponly_refresh_cookie_and_returns_short_lived_access_token(
    test_client, make_user
):
    user = make_user(role="clinician", facility="Facility A")
    resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]  # native-client field -- web client must never store this

    cookie = resp.cookies.get("clarion_refresh_token")
    assert cookie is not None
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=strict" in set_cookie_header or "samesite=strict" in set_cookie_header.lower()
    # Path defaults to "/" (REFRESH_COOKIE_PATH). It used to be "/auth", which
    # a browser never sends on the documented `/api/auth/refresh` proxy path
    # -- silent refresh was dead in that topology (code-review follow-up
    # 2026-09-07). HttpOnly + SameSite=Strict remain the CSRF defense.
    assert "Path=/;" in set_cookie_header or set_cookie_header.rstrip().endswith("Path=/")


def test_refresh_token_row_created_and_matches_neither_plaintext_stored(
    test_client, make_user, db_session
):
    """The plaintext must never be persisted -- only its HMAC hash."""
    user = make_user(role="clinician", facility="Facility A")
    resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    plaintext = resp.json()["refresh_token"]

    rows = db_session.query(models.RefreshToken).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].token_hash != plaintext
    assert plaintext not in rows[0].token_hash


def test_refresh_endpoint_mints_new_access_token_via_cookie(test_client, make_user):
    user = make_user(role="clinician", facility="Facility A")
    test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    # NOTE: does not compare the new access token against the login one --
    # create_access_token's `exp` claim has second-level granularity and
    # HS256 is deterministic, so two tokens minted for the same user within
    # the same wall-clock second are legitimately byte-identical. The
    # meaningful invariant is that the refresh call itself succeeds and
    # resolves to the same account, not that the JWT bytes differ.
    refresh_resp = test_client.post("/auth/refresh")  # cookie carried automatically by TestClient
    assert refresh_resp.status_code == 200
    new_body = refresh_resp.json()
    assert new_body["access_token"]
    assert new_body["user"]["email"] == user.email


def test_refresh_endpoint_works_via_body_for_native_clients(test_client, make_user):
    user = make_user(role="clinician", facility="Facility A")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    refresh_token = login_resp.json()["refresh_token"]

    # A bare `TestClient` still carries the cookie set by login() above
    # automatically; clear it so this test genuinely exercises the
    # body-only (native-client) path rather than accidentally passing via
    # the cookie instead.
    test_client.cookies.clear()

    resp = test_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_refresh_token_is_single_use_rotation(test_client, make_user):
    """Using a refresh token revokes it and issues a new one -- the SAME
    token can't be used twice."""
    user = make_user(role="clinician", facility="Facility A")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    old_refresh = login_resp.json()["refresh_token"]
    test_client.cookies.clear()

    first = test_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200

    test_client.cookies.clear()
    second = test_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert second.status_code == 401


def test_immediate_concurrent_reuse_is_graced_not_a_compromise(test_client, make_user, db_session):
    """Code-review follow-up 2026-09-07: presenting a just-rotated token
    again WITHIN REFRESH_REUSE_GRACE_SECONDS (the second browser tab racing
    the first around access-token expiry) fails only that request -- it must
    NOT revoke the whole chain. The legitimate new token stays live."""
    user = make_user(role="clinician", facility="Facility A")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    original_refresh = login_resp.json()["refresh_token"]
    test_client.cookies.clear()

    first = test_client.post("/auth/refresh", json={"refresh_token": original_refresh})
    new_refresh = first.json()["refresh_token"]
    test_client.cookies.clear()

    replay = test_client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert replay.status_code == 401  # this request fails...

    # ...but the chain is intact -- the token the legit client holds still works.
    test_client.cookies.clear()
    legit_followup = test_client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert legit_followup.status_code == 200


def test_delayed_reuse_of_rotated_token_revokes_the_whole_chain(test_client, make_user, db_session):
    """Security-critical: reuse of an already-rotated token OUTSIDE the
    concurrent-tab grace window is still a compromise signal -- every
    refresh token for that user is revoked, not just the one reused."""
    from datetime import datetime, timedelta

    from app import auth

    user = make_user(role="clinician", facility="Facility A")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    original_refresh = login_resp.json()["refresh_token"]
    test_client.cookies.clear()

    first = test_client.post("/auth/refresh", json={"refresh_token": original_refresh})
    new_refresh = first.json()["refresh_token"]
    test_client.cookies.clear()

    # Age the revoked row past the grace window.
    old_hash = auth._hash_refresh_token(original_refresh)
    stale = datetime.utcnow() - timedelta(seconds=auth.REFRESH_REUSE_GRACE_SECONDS + 60)
    db_session.query(models.RefreshToken).filter_by(token_hash=old_hash).update({"revoked_at": stale})
    db_session.commit()

    replay = test_client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert replay.status_code == 401

    test_client.cookies.clear()
    legit_followup = test_client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert legit_followup.status_code == 401

    all_rows = db_session.query(models.RefreshToken).filter_by(user_id=user.id).all()
    assert all(row.revoked_at is not None for row in all_rows)


def test_logout_revokes_the_refresh_token(test_client, make_user, db_session):
    user = make_user(role="clinician", facility="Facility A")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = test_client.post("/auth/logout")
    assert logout_resp.status_code == 200

    test_client.cookies.clear()
    after_logout = test_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert after_logout.status_code == 401


def test_logout_is_idempotent_and_never_errors(test_client):
    """No cookie, no body -- must still succeed (the caller's intent, 'make
    sure I'm logged out', is already satisfied)."""
    resp = test_client.post("/auth/logout")
    assert resp.status_code == 200


def test_password_change_revokes_all_refresh_tokens(test_client, make_user, db_session):
    """Security Audit M4: changing a password must now log out every
    device, not just invalidate the (already short-lived) access token."""
    user = make_user(role="clinician", facility="Facility A", password="OldPassword123!")
    login_resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": "OldPassword123!"}
    )
    refresh_token = login_resp.json()["refresh_token"]
    access_token = login_resp.json()["access_token"]

    change_resp = test_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"current_password": "OldPassword123!", "new_password": "BrandNewPassword456!"},
    )
    assert change_resp.status_code == 200, change_resp.text

    test_client.cookies.clear()
    refresh_after = test_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_after.status_code == 401

    row = db_session.query(models.RefreshToken).filter_by(user_id=user.id).first()
    assert row.revoked_at is not None
