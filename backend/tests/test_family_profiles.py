"""One patient login managing a child / elderly parent: add, switch, stay linked after the
dependant gets their own login, and nothing outside the link or the account settings opens up."""
import uuid

from app import models


def _patient(db_session, name="Parent One", dob="1985-05-05", **kw):
    p = models.Patient(full_name=name, date_of_birth=dob, **kw)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _parent(db_session, make_user):
    patient = _patient(db_session)
    return patient, make_user(role="patient", patient_id=patient.id)


def _add(test_client, auth_headers, user, **overrides):
    body = {"full_name": "Little Ali", "date_of_birth": "2019-03-03", "relation_code": "1", **overrides}
    return test_client.post("/profiles", headers=auth_headers(user), json=body)


def _switch(test_client, auth_headers, user, patient_id):
    resp = test_client.post("/profiles/switch", headers=auth_headers(user), json={"patient_id": patient_id})
    return resp


def _bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_add_a_child_and_a_parent_then_list_them(test_client, db_session, make_user, auth_headers):
    patient, user = _parent(db_session, make_user)
    child = _add(test_client, auth_headers, user)
    senior = _add(test_client, auth_headers, user, full_name="Hajjah Aminah", date_of_birth="1950-01-01", relation_code="3")
    assert child.status_code == 201 and senior.status_code == 201, (child.text, senior.text)
    assert child.json()["provisional"] is True and child.json()["relation_code"] == "1"

    row = db_session.get(models.Patient, senior.json()["patient_id"])
    assert row.senior_citizen_mode is True and row.provisional is True

    listing = test_client.get("/profiles", headers=auth_headers(user)).json()
    assert listing["active_patient_id"] == patient.id
    assert [p["is_self"] for p in listing["profiles"]] == [True, False, False]
    assert {p["full_name"] for p in listing["profiles"]} == {"Parent One", "Little Ali", "Hajjah Aminah"}


def test_bad_input_is_refused(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    assert _add(test_client, auth_headers, user, relation_code="2").status_code == 422        # spouse is not a carer link
    assert _add(test_client, auth_headers, user, date_of_birth="2999-01-01").status_code == 422
    assert _add(test_client, auth_headers, user, date_of_birth="not-a-date").status_code == 422
    assert _add(test_client, auth_headers, user, full_name=" ").status_code == 422


def test_a_login_can_hold_only_so_many_profiles(test_client, db_session, make_user, auth_headers):
    from app import guardianship
    _, user = _parent(db_session, make_user)
    for i in range(guardianship.MAX_PROFILES_PER_ACCOUNT):
        link_target = _patient(db_session, name=f"Kid {i}")
        db_session.add(models.PatientDependant(patient_id=user.patient_id, dependant_id=link_target.id, relation_code="1"))
    db_session.commit()
    assert _add(test_client, auth_headers, user).status_code == 400


def test_switching_acts_as_the_child_and_back(test_client, db_session, make_user, auth_headers):
    patient, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]

    acting = _switch(test_client, auth_headers, user, child_id)
    assert acting.status_code == 200, acting.text
    out = acting.json()["user"]
    assert out["acting_for"] is True and out["patient_id"] == child_id and out["full_name"] == "Little Ali"
    assert out["home_patient_id"] == patient.id and out["id"] == user.id

    headers = _bearer(acting)
    me = test_client.get("/auth/me", headers=headers).json()
    assert me["patient_id"] == child_id and me["acting_for"] is True
    assert test_client.get(f"/patients/{child_id}/audit-log", headers=headers).status_code == 200
    assert test_client.get(f"/patients/{patient.id}/audit-log", headers=headers).status_code == 403  # parent's own record: switch back first

    back = _switch(test_client, auth_headers, user, patient.id)  # a token is not needed to act as self again
    assert back.json()["user"]["acting_for"] is False
    assert test_client.get(f"/patients/{patient.id}/audit-log", headers=_bearer(back)).status_code == 200
    assert test_client.get(f"/patients/{child_id}/audit-log", headers=_bearer(back)).status_code == 403


def test_the_audit_trail_names_the_login_that_acted(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    headers = _bearer(_switch(test_client, auth_headers, user, child_id))
    test_client.get(f"/patients/{child_id}/audit-log", headers=headers)
    actions = {(r.actor, r.action) for r in db_session.query(models.AuditLog).filter_by(patient_id=child_id)}
    assert (user.id, "switch_profile") in actions and (user.id, "add_family_profile") in actions


def test_cannot_switch_into_someone_who_is_not_linked(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    stranger = _patient(db_session, name="Stranger")
    assert _switch(test_client, auth_headers, user, stranger.id).status_code == 403
    spouse = _patient(db_session, name="Spouse")
    db_session.add(models.PatientDependant(patient_id=user.patient_id, dependant_id=spouse.id, relation_code="spouse"))
    db_session.commit()
    assert _switch(test_client, auth_headers, user, spouse.id).status_code == 403


def test_authority_is_not_transitive(test_client, db_session, make_user, auth_headers):
    """Parent acts as the teenager; the teenager has their own dependant -- the parent still can't reach it."""
    _, parent = _parent(db_session, make_user)
    teen_id = _add(test_client, auth_headers, parent, full_name="Teen", date_of_birth="2008-01-01").json()["patient_id"]
    grandchild = _patient(db_session, name="Teens Baby")
    db_session.add(models.PatientDependant(patient_id=teen_id, dependant_id=grandchild.id, relation_code="1"))
    db_session.commit()
    acting = _switch(test_client, auth_headers, parent, teen_id)
    assert acting.status_code == 200
    again = test_client.post("/profiles/switch", headers=_bearer(acting), json={"patient_id": grandchild.id})
    assert again.status_code == 403
    forged = auth_headers(parent)  # a token for the parent that claims to act for the grandchild is refused too
    from app import auth
    token = auth.create_access_token({"sub": parent.id, "role": "patient", "act_as": grandchild.id})
    assert test_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert test_client.get(f"/patients/{grandchild.id}/audit-log", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_account_settings_stay_with_the_account_holder(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    headers = _bearer(_switch(test_client, auth_headers, user, child_id))
    resp = test_client.post("/auth/change-password", headers=headers,
                            json={"current_password": user.plaintext_password, "new_password": "BrandNewPass123!"})
    assert resp.status_code == 403 and "own profile" in resp.text


def test_removing_the_link_ends_access_immediately(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    created = _add(test_client, auth_headers, user).json()
    headers = _bearer(_switch(test_client, auth_headers, user, created["patient_id"]))
    assert test_client.get(f"/patients/{created['patient_id']}/audit-log", headers=headers).status_code == 200
    db_session.query(models.PatientDependant).filter_by(id=created["link_id"]).delete()
    db_session.commit()
    assert test_client.get(f"/patients/{created['patient_id']}/audit-log", headers=headers).status_code == 403
    assert test_client.get("/auth/me", headers=headers).status_code == 403


def test_the_link_survives_the_dependant_getting_their_own_login(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    created = _add(test_client, auth_headers, user, full_name="Grown Child", date_of_birth="2005-01-01").json()
    own_login = make_user(role="patient", patient_id=created["patient_id"])  # they register themselves later
    listing = test_client.get("/profiles", headers=auth_headers(user)).json()["profiles"]
    entry = [p for p in listing if p["patient_id"] == created["patient_id"]][0]
    assert entry["has_own_login"] is True  # still listed under the carer's login: the link did not go away
    guardians = test_client.get("/profiles/guardians", headers=auth_headers(own_login)).json()
    assert guardians[0]["full_name"] == "Parent One"
    # An adult with a login of their own has to approve the carer; after that the link works as before.
    assert _switch(test_client, auth_headers, user, created["patient_id"]).status_code == 403
    assert test_client.post(f"/profiles/guardians/{guardians[0]['link_id']}/approve",
                            headers=auth_headers(own_login)).status_code == 204
    assert _switch(test_client, auth_headers, user, created["patient_id"]).status_code == 200


def test_an_adult_can_remove_a_carer_but_a_minor_cannot(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    adult = _add(test_client, auth_headers, user, full_name="Adult Child", date_of_birth="1990-01-01").json()
    minor = _add(test_client, auth_headers, user, full_name="Kid", date_of_birth="2018-01-01").json()
    adult_login = make_user(role="patient", patient_id=adult["patient_id"])
    minor_login = make_user(role="patient", patient_id=minor["patient_id"])
    assert test_client.delete(f"/profiles/guardians/{minor['link_id']}", headers=auth_headers(minor_login)).status_code == 403
    assert test_client.delete(f"/profiles/guardians/{adult['link_id']}", headers=auth_headers(adult_login)).status_code == 204
    assert _switch(test_client, auth_headers, user, adult["patient_id"]).status_code == 403
    assert _switch(test_client, auth_headers, user, minor["patient_id"]).status_code == 200
    other = make_user(role="patient", patient_id=_patient(db_session, name="Other").id)  # not a party to the link
    assert test_client.delete(f"/profiles/guardians/{minor['link_id']}", headers=auth_headers(other)).status_code == 404


def test_staff_and_responder_logins_cannot_use_profiles(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician")
    assert test_client.get("/profiles", headers=auth_headers(staff)).status_code == 403


def test_refresh_keeps_the_selected_profile(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    login = test_client.post("/auth/login", data={"username": user.email, "password": user.plaintext_password})
    assert login.status_code == 200, login.text
    refreshed = test_client.post("/auth/refresh", json={"refresh_token": login.json()["refresh_token"], "act_as": child_id})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["user"]["acting_for"] is True and refreshed.json()["user"]["patient_id"] == child_id
    token_headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    assert test_client.get(f"/patients/{child_id}/audit-log", headers=token_headers).status_code == 200
    # an act_as the login has no right to is ignored, not honoured
    stranger = _patient(db_session, name="Nobody")
    again = test_client.post("/auth/refresh", json={"refresh_token": refreshed.json()["refresh_token"], "act_as": stranger.id})
    assert again.status_code == 200 and again.json()["user"]["acting_for"] is False
