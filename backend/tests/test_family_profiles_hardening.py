"""Family profiles, security-review hardening: approval for adults with their own login, only the
self-service relation codes grant access, a carer can't repoint the owner's email or touch the
account media routes, guardian authority doesn't chain, consent is labelled, tokens die with a
password change."""
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
    return test_client.post("/profiles/switch", headers=auth_headers(user), json={"patient_id": patient_id})


def _bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _consent(test_client, headers, patient_id=None, purpose="research"):
    body = {"purpose": purpose, "granted": True}
    if patient_id:
        body["patient_id"] = patient_id
    return test_client.post("/pdpa/consent", headers=headers, json=body)


def test_a_typed_ic_number_is_never_stored_so_no_one_can_squat_an_identity(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    resp = _add(test_client, auth_headers, user, national_id="190303101234")
    assert resp.status_code == 201
    row = db_session.get(models.Patient, resp.json()["patient_id"])
    assert row.national_id is None and row.normalized_national_id is None


def test_an_adult_with_their_own_login_must_approve_before_a_carer_can_act(test_client, db_session, make_user, auth_headers):
    _, carer = _parent(db_session, make_user)
    adult = _add(test_client, auth_headers, carer, full_name="Grown Child", date_of_birth="1990-01-01").json()
    adult_login = make_user(role="patient", patient_id=adult["patient_id"])  # they register themselves later

    entry = [p for p in test_client.get("/profiles", headers=auth_headers(carer)).json()["profiles"]
             if p["patient_id"] == adult["patient_id"]][0]
    assert entry["pending_approval"] is True and entry["has_own_login"] is True
    blocked = _switch(test_client, auth_headers, carer, adult["patient_id"])
    assert blocked.status_code == 403 and "approval" in blocked.json()["detail"]

    waiting = test_client.get("/profiles/guardians", headers=auth_headers(adult_login)).json()[0]
    assert waiting["pending"] is True and waiting["approved"] is False
    stranger = make_user(role="patient", patient_id=_patient(db_session, name="Other").id)
    assert test_client.post(f"/profiles/guardians/{waiting['link_id']}/approve", headers=auth_headers(stranger)).status_code == 404
    assert test_client.post(f"/profiles/guardians/{waiting['link_id']}/approve", headers=auth_headers(adult_login)).status_code == 204
    assert _switch(test_client, auth_headers, carer, adult["patient_id"]).status_code == 200


def test_a_minor_and_an_adult_without_a_login_need_no_approval(test_client, db_session, make_user, auth_headers):
    _, carer = _parent(db_session, make_user)
    kid = _add(test_client, auth_headers, carer).json()
    make_user(role="patient", patient_id=kid["patient_id"])  # even with a login of their own, a minor needs no approval
    mum = _add(test_client, auth_headers, carer, full_name="Old Mum", date_of_birth="1948-01-01", relation_code="3").json()
    assert _switch(test_client, auth_headers, carer, kid["patient_id"]).status_code == 200
    assert _switch(test_client, auth_headers, carer, mum["patient_id"]).status_code == 200


def test_only_the_self_service_relation_codes_grant_access(test_client, db_session, make_user, auth_headers):
    """A link a clinic made for its own reasons (no code, sibling, financial dependant) is not a carer grant."""
    _, user = _parent(db_session, make_user)
    for code in (None, "11", "5", "6"):
        other = _patient(db_session, name=f"Linked {code}")
        db_session.add(models.PatientDependant(patient_id=user.patient_id, dependant_id=other.id, relation_code=code))
        db_session.commit()
        assert _switch(test_client, auth_headers, user, other.id).status_code == 403, code
    listed = test_client.get("/profiles", headers=auth_headers(user)).json()["profiles"]
    assert len(listed) == 1  # none of them is offered as a profile either


def test_a_carer_cannot_repoint_the_email_that_receives_the_owners_reset_codes(test_client, db_session, make_user, auth_headers):
    patient, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    acting = _bearer(_switch(test_client, auth_headers, user, child_id))
    resp = test_client.patch(f"/patients/{child_id}/profile", headers=acting, json={"email": "carer@example.com"})
    assert resp.status_code == 403 and db_session.get(models.Patient, child_id).email is None
    own = test_client.patch(f"/patients/{patient.id}/profile", headers=auth_headers(user), json={"email": "me@example.com"})
    assert own.status_code == 200


def test_account_media_routes_are_closed_while_acting(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    acting = _bearer(_switch(test_client, auth_headers, user, child_id))
    assert test_client.put("/me/profile", headers=acting, json={"bio": "x"}).status_code == 403
    assert test_client.delete("/me/signature", headers=acting).status_code == 403


def test_guardian_authority_does_not_chain_through_the_profile_being_acted_for(test_client, db_session, make_user, auth_headers):
    """A acts for D; D is the recorded guardian of a minor X. A must not reach X's consent ledger."""
    _, a = _parent(db_session, make_user)
    d_id = _add(test_client, auth_headers, a, full_name="Teen D", date_of_birth="2007-01-01").json()["patient_id"]
    x = _patient(db_session, name="Tiny X", dob="2020-01-01")
    db_session.add(models.PatientDependant(patient_id=d_id, dependant_id=x.id, relation_code="1"))
    db_session.commit()
    acting = _bearer(_switch(test_client, auth_headers, a, d_id))
    assert _consent(test_client, acting, patient_id=x.id).status_code == 403
    assert test_client.get(f"/pdpa/consent?patient_id={x.id}", headers=acting).status_code == 403


def test_consent_given_while_acting_is_recorded_as_a_guardian_not_the_patient(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    acting = _bearer(_switch(test_client, auth_headers, user, child_id))
    assert _consent(test_client, acting).status_code == 200
    row = (db_session.query(models.ConsentRecord).filter_by(patient_id=child_id)
           .order_by(models.ConsentRecord.created_at.desc()).first())
    assert row.source == "guardian" and row.recorded_by == user.id


def test_a_password_change_ends_every_acting_token(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    child_id = _add(test_client, auth_headers, user).json()["patient_id"]
    acting = _bearer(_switch(test_client, auth_headers, user, child_id))
    assert test_client.get("/auth/me", headers=acting).status_code == 200
    changed = test_client.post("/auth/change-password", headers=auth_headers(user),
                               json={"current_password": user.plaintext_password, "new_password": "BrandNewPass123!x"})
    assert changed.status_code == 200, changed.text
    assert test_client.get("/auth/me", headers=acting).status_code == 401


def test_a_refresh_without_act_as_returns_to_the_own_profile(test_client, db_session, make_user, auth_headers):
    _, user = _parent(db_session, make_user)
    _add(test_client, auth_headers, user)
    login = test_client.post("/auth/login", data={"username": user.email, "password": user.plaintext_password}).json()
    refreshed = test_client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200 and refreshed.json()["user"]["acting_for"] is False
