"""One login, several roles: the active role is a token claim re-checked on every request, the
patient identity is only visible while acting as a patient, a lapsed responder window drops only
the responder role, and the paramedic tier is a responder account flagged by its admin."""
from datetime import datetime, timedelta, timezone

import base64
import uuid

from app import auth, models
from app.routers import emergency
from tests.conftest import _TEST_SIGNATURE_B64, _facility, _make_patient


def _known(db_session, patient, facility):
    """Make `facility` know the patient (an active admission), as the grant rule requires."""
    ward = models.Ward(facility_name=facility, ward_name=f"W{uuid.uuid4().hex[:4]}", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name=facility, patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()


def _login(test_client, user):
    r = test_client.post("/auth/login", data={"username": user.email, "password": user.plaintext_password})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(body):
    return {"Authorization": f"Bearer {body['access_token']}"}


def _switch(test_client, headers, role):
    return test_client.post("/auth/switch-role", headers=headers, json={"role": role})


def _nurse_who_is_a_patient(db_session, make_user, facility=None):
    patient = _make_patient(db_session)
    user = make_user(role="clinician", facility=facility or _facility(), patient_id=patient.id)
    db_session.add(models.UserRole(user_id=user.id, role="patient"))
    db_session.commit()
    db_session.refresh(user)
    return user, patient


def test_a_single_role_account_is_unchanged(test_client, make_user):
    user = make_user(role="clinician", facility=_facility())
    body = _login(test_client, user)
    assert body["user"]["roles"] == ["clinician"] and body["user"]["role"] == "clinician"
    me = test_client.get("/auth/me", headers=_bearer(body)).json()
    assert me["roles"] == ["clinician"]


def test_switching_role_changes_what_the_session_is(test_client, db_session, make_user):
    user, patient = _nurse_who_is_a_patient(db_session, make_user)
    body = _login(test_client, user)
    assert body["user"]["role"] == "clinician" and set(body["user"]["roles"]) == {"clinician", "patient"}
    assert body["user"]["patient_id"] is None  # a staff session never carries the person's own record

    sw = _switch(test_client, _bearer(body), "patient")
    assert sw.status_code == 200, sw.text
    as_patient = sw.json()
    assert as_patient["user"]["role"] == "patient" and as_patient["user"]["patient_id"] == patient.id
    me = test_client.get("/auth/me", headers=_bearer(as_patient)).json()
    assert me["role"] == "patient" and me["patient_id"] == patient.id

    own = test_client.get(f"/patients/{patient.id}", headers=_bearer(as_patient))
    assert own.status_code == 200  # own record, as a patient


def test_the_last_role_is_remembered_across_sign_ins(test_client, db_session, make_user):
    user, patient = _nurse_who_is_a_patient(db_session, make_user)
    assert _switch(test_client, _bearer(_login(test_client, user)), "patient").status_code == 200
    again = _login(test_client, user)
    assert again["user"]["role"] == "patient" and again["user"]["patient_id"] == patient.id
    # and a refresh may ask for a role explicitly
    r = test_client.post("/auth/refresh", json={"refresh_token": again["refresh_token"], "act_role": "clinician"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "clinician"


def test_a_role_the_account_does_not_hold_is_refused(test_client, make_user):
    user = make_user(role="clinician", facility=_facility())
    body = _login(test_client, user)
    assert _switch(test_client, _bearer(body), "admin").status_code == 403
    assert _switch(test_client, _bearer(body), "patient").status_code == 403


def test_a_token_for_a_role_that_was_taken_away_stops_working(test_client, db_session, make_user):
    user, patient = _nurse_who_is_a_patient(db_session, make_user)
    as_patient = _switch(test_client, _bearer(_login(test_client, user)), "patient").json()
    assert test_client.get("/auth/me", headers=_bearer(as_patient)).status_code == 200
    db_session.query(models.UserRole).filter_by(user_id=user.id, role="patient").delete()
    db_session.commit()
    assert test_client.get("/auth/me", headers=_bearer(as_patient)).status_code == 401


def test_a_lapsed_responder_window_drops_only_the_responder_role(db_session, make_user):
    patient = _make_patient(db_session)
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    both = make_user(role="patient", patient_id=patient.id, access_expires_at=past)
    db_session.add(models.UserRole(user_id=both.id, role="emergency_responder"))
    db_session.commit()
    db_session.refresh(both)
    assert auth.all_roles(both) == ["patient", "emergency_responder"]
    assert auth.usable_roles(both) == ["patient"] and not auth.access_expired(both)

    guard = make_user(role="emergency_responder", facility=_facility(), access_expires_at=past)
    assert auth.access_expired(guard)  # a responder-only account still lapses entirely


def test_a_responder_session_stays_restricted_even_on_a_multi_role_account(test_client, db_session, make_user):
    patient = _make_patient(db_session)
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    user = make_user(role="patient", patient_id=patient.id, facility=_facility(),
                     access_expires_at=future, responder_tier="community")
    db_session.add(models.UserRole(user_id=user.id, role="emergency_responder"))
    db_session.commit()
    db_session.refresh(user)
    body = _login(test_client, user)
    as_guard = _switch(test_client, _bearer(body), "emergency_responder").json()
    assert as_guard["user"]["role"] == "emergency_responder" and as_guard["user"]["patient_id"] is None
    assert test_client.get(f"/patients/{patient.id}", headers=_bearer(as_guard)).status_code == 403
    assert _switch(test_client, _bearer(as_guard), "patient").status_code == 200  # /auth/ stays reachable


def _card(db_session, patient):
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="Warfarin", dosage="5mg",
                                              frequency="daily", active=True, critical_for_emergency=True))
    ref = f"mr{abs(hash(patient.id)) % 10**8}"
    db_session.add(models.EmergencyToken(
        patient_id=patient.id, token=f"t{ref}", card_reference=ref, scope=["allergies", "medications"],
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)))
    db_session.commit()
    return ref


def _scan(test_client, ref, headers):
    return test_client.post("/emergency/scan", headers=headers, json={"card_reference": ref})


def test_a_paramedic_sees_medications_a_community_responder_does_not(test_client, db_session, make_user):
    patient = _make_patient(db_session)
    ref = _card(db_session, patient)
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    medic = make_user(role="emergency_responder", facility=_facility(), access_expires_at=future,
                      responder_tier="paramedic")
    guard = make_user(role="emergency_responder", facility=_facility(), access_expires_at=future,
                      responder_tier="community")
    m = _scan(test_client, ref, _bearer(_login(test_client, medic))).json()
    g = _scan(test_client, ref, _bearer(_login(test_client, guard))).json()
    assert m["tier"] == "paramedic" and m["medications"][0]["drug_name"] == "Warfarin"
    assert g["tier"] == "responder" and "medications" not in g
    assert _scan(test_client, ref, {}).json()["tier"] == "public"


def test_admin_creates_a_paramedic_account(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility=_facility())
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = test_client.post("/admin/responders", headers=auth_headers(admin),
                         json={"full_name": "Crew One", "email": f"crew-{id(admin)}@example.com",
                               "expires_at": exp, "tier": "paramedic"})
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "paramedic"
    bad = test_client.post("/admin/responders", headers=auth_headers(admin),
                           json={"full_name": "X", "email": "x@example.com", "expires_at": exp, "tier": "god"})
    assert bad.status_code == 422


def test_admin_grants_and_revokes_roles_with_the_guard_rails(test_client, db_session, make_user, auth_headers):
    fac = _facility()
    admin = make_user(role="admin", facility=fac)
    nurse = make_user(role="clinician", facility=fac)
    patient = _make_patient(db_session)
    h = auth_headers(admin)
    url = f"/admin/users/{nurse.id}/roles"
    unknown = test_client.post(url, headers=h, json={"role": "patient", "patient_id": patient.id})
    assert unknown.status_code == 403  # this facility has never dealt with that patient
    _known(db_session, patient, fac)

    assert test_client.post(url, headers=h, json={"role": "admin"}).status_code == 422
    assert test_client.post(url, headers=h, json={"role": "patient"}).status_code == 400  # needs patient_id
    assert test_client.post(url, headers=h, json={"role": "clinician"}).status_code == 409  # already primary
    assert test_client.post(url, headers=h, json={"role": "emergency_responder"}).status_code == 400  # needs expiry

    ok = test_client.post(url, headers=h, json={"role": "patient", "patient_id": patient.id})
    assert ok.status_code == 200 and ok.json()["roles"] == ["clinician", "patient"]
    assert test_client.post(url, headers=h, json={"role": "patient", "patient_id": patient.id}).status_code == 409

    other = make_user(role="clinician", facility=fac)  # that record already belongs to the nurse's login
    taken = test_client.post(f"/admin/users/{other.id}/roles", headers=h,
                             json={"role": "patient", "patient_id": patient.id})
    assert taken.status_code == 409

    assert test_client.delete(f"{url}/clinician", headers=h).status_code == 404  # primary is not removable
    assert test_client.delete(f"{url}/patient", headers=h).json()["roles"] == ["clinician"]
    db_session.expire_all()
    assert db_session.get(models.User, nurse.id).patient_id is None  # the link goes with the role


def test_a_patient_login_is_not_staffed_unless_the_facility_knows_the_patient(test_client, db_session, make_user,
                                                                                auth_headers):
    fac = _facility()
    admin = make_user(role="admin", facility=fac)
    patient = _make_patient(db_session)
    login = make_user(role="patient", patient_id=patient.id)  # facility-less patient login
    url = f"/admin/users/{login.id}/roles"
    assert test_client.post(url, headers=auth_headers(admin), json={"role": "pharmacist"}).status_code == 404
    _known(db_session, patient, fac)
    assert test_client.post(url, headers=auth_headers(admin), json={"role": "pharmacist"}).status_code == 200
    assert test_client.delete(f"{url}/pharmacist", headers=auth_headers(admin)).status_code == 200
    db_session.expire_all()
    assert db_session.get(models.User, login.id).facility is None  # back to a plain patient login


def test_an_admin_cannot_touch_another_facilitys_account(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility=_facility())
    stranger = make_user(role="clinician", facility=_facility())
    r = test_client.post(f"/admin/users/{stranger.id}/roles", headers=auth_headers(admin),
                         json={"role": "pharmacist"})
    assert r.status_code == 404


def test_account_lookups_by_role_see_extra_roles(db_session, make_user):
    fac = _facility()
    user = make_user(role="patient", facility=fac)
    db_session.add(models.UserRole(user_id=user.id, role="clinician"))
    db_session.commit()
    found = db_session.query(models.User).filter(models.user_has_role("clinician"),
                                                 models.User.facility == fac).all()
    assert [u.id for u in found] == [user.id]
    assert emergency._TIER_CEILING["paramedic"] > emergency._TIER_CEILING["responder"]


# ---- findings from the security review -------------------------------------------------------

def test_a_records_officer_cannot_reset_a_staff_login_through_its_patient_link(test_client, db_session, make_user,
                                                                               auth_headers):
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    officer = make_user(role="records_officer", facility=_facility())
    r = test_client.post(f"/auth/patients/{patient.id}/issue-account", headers=auth_headers(officer))
    assert r.status_code == 409
    assert _login(test_client, nurse)["user"]["role"] == "clinician"  # password unchanged


def test_the_emailed_reset_code_is_not_used_for_a_login_that_also_holds_staff_roles(test_client, db_session,
                                                                                   make_user, monkeypatch):
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    patient.national_id, patient.email = "900101-01-5555", "attacker@example.com"
    db_session.commit()
    sent = []
    from app.routers import auth_router
    monkeypatch.setattr(auth_router, "send_password_reset_otp_email", lambda *a, **k: sent.append(a) or True)
    r = test_client.post("/auth/request-password-reset-otp", json={"national_id": "900101-01-5555"})
    assert r.status_code == 200 and sent == []  # same generic answer, nothing mailed


def test_moving_from_a_low_trust_role_to_staff_needs_the_password(test_client, db_session, make_user):
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    as_patient = _switch(test_client, _bearer(_login(test_client, nurse)), "patient").json()
    h = _bearer(as_patient)
    ask = _switch(test_client, h, "clinician")
    assert ask.status_code == 428 and ask.json()["detail"]["reauth_required"] is True
    bad = test_client.post("/auth/switch-role", headers=h, json={"role": "clinician", "password": "nope"})
    assert bad.status_code == 400
    ok = test_client.post("/auth/switch-role", headers=h,
                          json={"role": "clinician", "password": nurse.plaintext_password})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "clinician"
    assert _switch(test_client, _bearer(ok.json()), "patient").status_code == 200  # going down needs nothing


def test_a_multi_role_session_can_change_its_password_and_use_account_settings(test_client, db_session, make_user):
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    h = _bearer(_login(test_client, nurse))
    r = test_client.post("/auth/change-password", headers=h,
                         json={"current_password": nurse.plaintext_password, "new_password": "A-brand-new-Passw0rd!x"})
    assert r.status_code == 200, r.text
    nurse.plaintext_password = "A-brand-new-Passw0rd!x"
    h = _bearer(_login(test_client, nurse))
    png = base64.b64decode(_TEST_SIGNATURE_B64)
    sig = test_client.post("/me/signature", headers=h, files={"file": ("s.png", png, "image/png")})
    assert sig.status_code == 200, sig.text
    st = test_client.post("/auth/mfa/setup/start", headers=h, json={"password": nurse.plaintext_password})
    assert st.status_code == 200, st.text  # the MFA helpers write through the session too


def test_mfa_is_judged_on_the_account_not_the_active_role(db_session, make_user, monkeypatch):
    monkeypatch.setenv("CLARION_MFA_REQUIRED_ROLES", "clinician")
    from app import mfa
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    patient_session = auth.RoleUser(nurse, "patient")
    assert not mfa.role_requires_mfa(patient_session.role)  # the active role alone would say no
    assert mfa.required_for(auth.real_user(patient_session)) is True


def test_a_multi_role_token_without_a_role_claim_is_refused(test_client, db_session, make_user):
    nurse, patient = _nurse_who_is_a_patient(db_session, make_user)
    bare = auth.create_access_token({"sub": nurse.id}, password_changed_at=nurse.password_changed_at)
    assert test_client.get("/auth/me", headers={"Authorization": f"Bearer {bare}"}).status_code == 401


def test_one_login_per_patient_record(db_session, make_user):
    import pytest
    from sqlalchemy.exc import IntegrityError
    patient = _make_patient(db_session)
    make_user(role="patient", patient_id=patient.id)
    with pytest.raises(IntegrityError):
        make_user(role="patient", patient_id=patient.id)
    db_session.rollback()
