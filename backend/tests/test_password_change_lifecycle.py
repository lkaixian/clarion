"""Code-review follow-up 2026-09-07 -- coverage the test-quality pass flagged
as missing on two security-critical auth mechanisms:

  1. An ACCESS token issued before a password change is rejected afterwards
     (the pwd_changed_at watermark in auth._resolve_current_user).
     test_refresh_tokens.py covered refresh-token revocation on password
     change but nothing asserted the access token itself stops working.
  2. must_change_password actually BLOCKS protected endpoints server-side
     (auth.get_current_user), while /auth/me and /auth/change-password stay
     reachable so the user can clear the flag. Previously only the DB flag
     being *set* was tested, never that it is *enforced*.
"""
from app import models


def test_access_token_is_rejected_after_password_change(test_client, make_user, auth_headers):
    user = make_user(role="clinician", facility="Facility A")
    headers = auth_headers(user)

    # Token works now.
    assert test_client.get("/auth/me", headers=headers).status_code == 200

    changed = test_client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": user.plaintext_password, "new_password": "BrandNewPass456!"},
    )
    assert changed.status_code == 200, changed.text

    # The SAME access token (issued before the change) must now be dead.
    assert test_client.get("/auth/me", headers=headers).status_code == 401
    assert test_client.get("/patients", headers=headers).status_code == 401


def test_must_change_password_blocks_protected_endpoints_but_not_the_escape_hatches(
    test_client, make_user, auth_headers, db_session
):
    user = make_user(role="clinician", facility="Facility A")
    db_session.query(models.User).filter_by(id=user.id).update({"must_change_password": True})
    db_session.commit()

    headers = auth_headers(user)

    # Every normal protected endpoint is 403 while the flag is set.
    blocked = test_client.get("/patients", headers=headers)
    assert blocked.status_code == 403

    # ...but /auth/me still works (the client needs it to discover the flag)
    me = test_client.get("/auth/me", headers=headers)
    assert me.status_code == 200

    # ...and /auth/change-password works, and clears the flag.
    changed = test_client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": user.plaintext_password, "new_password": "ClearsTheFlag789!"},
    )
    assert changed.status_code == 200, changed.text

    db_session.expire_all()  # the change happened in the request's own session
    row = db_session.query(models.User).filter_by(id=user.id).first()
    assert row.must_change_password is False


def test_wrong_current_password_is_400_not_401(test_client, make_user, auth_headers):
    """401 means "session expired" to every client (refresh/bounce to login); a
    wrong current password must not be confused with it."""
    user = make_user(role="clinician", facility="Facility A")
    resp = test_client.post(
        "/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": "definitely-wrong-123", "new_password": "ValidNewPassword789!"},
    )
    assert resp.status_code == 400, resp.text
