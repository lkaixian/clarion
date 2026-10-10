"""Forced first-login change asks only for the new password; a voluntary
change must still prove the current one."""
from app import auth, models


def test_forced_change_needs_no_current_password(test_client, db_session, make_user, auth_headers):
    user = make_user("clinician")
    user.must_change_password = True
    db_session.commit()

    r = test_client.post(
        "/auth/change-password", headers=auth_headers(user),
        json={"new_password": "Brand-new-Pass42!"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(user)
    assert user.must_change_password is False
    assert auth.verify_password("Brand-new-Pass42!", user.hashed_password)


def test_voluntary_change_still_requires_current_password(test_client, make_user, auth_headers):
    user = make_user("clinician")
    h = auth_headers(user)

    missing = test_client.post("/auth/change-password", headers=h,
                               json={"new_password": "Brand-new-Pass42!"})
    assert missing.status_code == 400

    wrong = test_client.post("/auth/change-password", headers=h,
                             json={"current_password": "nope", "new_password": "Brand-new-Pass42!"})
    assert wrong.status_code == 400
