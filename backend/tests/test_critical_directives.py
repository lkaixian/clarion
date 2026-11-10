import pytest
"""Critical directives: append-only, patient-declared vs staff-recorded, emergency view, audit."""
import uuid

from app import models


def _fac():
    return f"Dir-{uuid.uuid4().hex[:8]}"


def _patient(db, name="Dir Patient", dob="1980-01-01"):
    p = models.Patient(full_name=name, date_of_birth=dob)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _known(db, patient, facility):
    """Make `facility` deal with the patient (admitted there, so also 'present' for the emergency flow)."""
    ward = models.Ward(facility_name=facility, ward_name="W", total_beds=2)
    db.add(ward)
    db.commit()
    db.refresh(ward)
    db.add(models.Admission(facility_name=facility, patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db.commit()


@pytest.fixture(autouse=True)
def _auto_based_on(test_client, monkeypatch):
    """Most tests just want to write; fill in `based_on` (the entry being replaced) like the UI does.
    Tests about conflicts pass `based_on` explicitly and are left alone."""
    put, post = test_client.put, test_client.post

    def current_id(headers, list_url, kind):
        r = test_client.get(list_url, headers=headers)
        cur = [d for d in r.json().get("current", []) if d["kind"] == kind] if r.status_code == 200 else []
        return cur[0]["id"] if cur else ""

    def w_put(url, **kw):
        body = kw.get("json") or {}
        if isinstance(body, dict) and "based_on" not in body and url.startswith("/profile/directives/"):
            kw["json"] = {**body, "based_on": current_id(kw["headers"], "/profile/directives", url.rsplit("/", 1)[1])}
        return put(url, **kw)

    def w_post(url, **kw):
        body = kw.get("json") or {}
        if isinstance(body, dict) and "based_on" not in body and url.endswith("/directives") and "kind" in body:
            kw["json"] = {**body, "based_on": current_id(kw["headers"], url, body["kind"])}
        return post(url, **kw)

    monkeypatch.setattr(test_client, "put", w_put)
    monkeypatch.setattr(test_client, "post", w_post)


def _setup(db, make_user, auth_headers, role="clinician"):
    fac = _fac()
    patient = _patient(db)
    _known(db, patient, fac)
    staff = make_user(role=role, facility=fac)
    login = make_user(role="patient", patient_id=patient.id)
    return fac, patient, staff, login, auth_headers(staff), auth_headers(login)


def _rows(db, pid):
    db.expire_all()
    return db.query(models.CriticalDirective).filter_by(patient_id=pid).all()


def _staff_body(**kw):
    return {"kind": "organ_donation", "value": "yes", "evidence_ref": "FORM-001", **kw}


def test_patient_writes_own_only_and_source_forced(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    r = test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "yes", "note": "kidneys"})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "patient" and r.json()["label"] == "patient-declared"
    assert r.json()["recorded_by_role"] == "patient"
    # evidence_ref / source are not accepted from a patient
    assert test_client.put("/profile/directives/organ_donation", headers=ph,
                           json={"value": "yes", "evidence_ref": "X"}).status_code == 422
    assert test_client.put("/profile/directives/organ_donation", headers=ph,
                           json={"value": "yes", "source": "staff"}).status_code == 422
    # there is no path to name another patient; staff cannot use the self-service route
    assert test_client.put("/profile/directives/organ_donation", headers=sh, json={"value": "no"}).status_code == 403
    assert len(_rows(db_session, patient.id)) == 1
    got = test_client.get("/profile/directives", headers=ph).json()
    assert [d["value"] for d in got["current"]] == ["yes"]


def test_patient_cannot_use_staff_route(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    other = _patient(db_session, "Other")
    assert test_client.post(f"/patients/{other.id}/directives", headers=ph, json=_staff_body()).status_code == 403
    assert test_client.get(f"/patients/{patient.id}/directives", headers=ph).status_code == 403


def test_guardian_acting_for_dependant_follows_existing_rules(test_client, db_session, make_user, auth_headers):
    fac, parent, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    child = _patient(db_session, "Child", dob="2018-01-01")
    db_session.add(models.PatientDependant(patient_id=parent.id, dependant_id=child.id, relation_code="1",
                                           created_by=login.id))
    db_session.commit()
    sw = test_client.post("/profiles/switch", headers=ph, json={"patient_id": child.id})
    assert sw.status_code == 200, sw.text
    ch = {"Authorization": f"Bearer {sw.json()['access_token']}"}
    assert test_client.put("/profile/directives/blood_transfusion", headers=ch, json={"value": "no"}).status_code == 201
    assert [r.kind for r in _rows(db_session, child.id)] == ["blood_transfusion"]
    assert _rows(db_session, parent.id) == []


def test_staff_needs_evidence_ref_and_roles(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    url = f"/patients/{patient.id}/directives"
    body = {"kind": "organ_donation", "value": "yes"}
    assert test_client.post(url, headers=sh, json=body).status_code == 422
    assert test_client.post(url, headers=sh, json={**body, "evidence_ref": "   "}).status_code == 422
    r = test_client.post(url, headers=sh, json=_staff_body(note="heart"))
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "staff" and r.json()["label"] == "recorded by staff (form FORM-001)"
    assert r.json()["recorded_by_role"] == "clinician" and r.json()["recorded_by_facility"] == fac
    # source cannot be chosen by the caller
    assert test_client.post(url, headers=sh, json=_staff_body(source="patient")).status_code == 422
    for role in ("admin", "records_officer", "clinician"):
        u = make_user(role=role, facility=fac)
        assert test_client.post(url, headers=auth_headers(u), json=_staff_body()).status_code == 201


def test_pharmacist_read_only(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    ph_user = make_user(role="pharmacist", facility=fac)
    h = auth_headers(ph_user)
    url = f"/patients/{patient.id}/directives"
    test_client.post(url, headers=sh, json=_staff_body())
    assert test_client.post(url, headers=h, json=_staff_body()).status_code == 403
    r = test_client.get(url, headers=h)
    assert r.status_code == 200 and len(r.json()["history"]) == 1


def test_patient_unknown_to_facility_is_404(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    stranger = make_user(role="clinician", facility=_fac())
    h = auth_headers(stranger)
    url = f"/patients/{patient.id}/directives"
    assert test_client.post(url, headers=h, json=_staff_body()).status_code == 404
    assert test_client.get(url, headers=h).status_code == 404
    assert test_client.post("/patients/nope/directives", headers=sh, json=_staff_body()).status_code == 404
    assert _rows(db_session, patient.id) == []


def test_append_only_current_is_newest(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "yes"})
    test_client.post(f"/patients/{patient.id}/directives", headers=sh, json=_staff_body(value="no"))
    assert len(_rows(db_session, patient.id)) == 2
    got = test_client.get(f"/patients/{patient.id}/directives", headers=sh).json()
    assert [d["value"] for d in got["current"]] == ["no"] and got["current"][0]["source"] == "staff"
    assert [d["value"] for d in got["history"]] == ["no", "yes"]  # the patient's own row is still there
    test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "undecided"})
    assert len(_rows(db_session, patient.id)) == 3
    cur = test_client.get("/profile/directives", headers=ph).json()["current"]
    assert [d["value"] for d in cur] == ["undecided"]


def test_validation(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    put = lambda kind, body: test_client.put(f"/profile/directives/{kind}", headers=ph, json=body).status_code  # noqa: E731
    assert put("blood_group", {"value": "yes"}) == 422
    assert put("organ_donation", {"value": "maybe"}) == 422
    assert put("organ_donation", {"value": ""}) == 422
    assert put("implanted_device", {"value": "x" * 301}) == 422
    assert put("organ_donation", {"value": "yes", "note": "n" * 501}) == 422
    assert put("implanted_device", {"value": 5}) == 422
    assert test_client.post(f"/patients/{patient.id}/directives", headers=sh,
                            json=_staff_body(kind="organ")).status_code == 422
    assert test_client.post(f"/patients/{patient.id}/directives", headers=sh,
                            json=_staff_body(evidence_ref="e" * 121)).status_code == 422
    assert put("implanted_device", {"value": "pace\x00maker\r\nModel\x07 X"}) == 201
    row = _rows(db_session, patient.id)[0]
    assert row.value == "pace maker Model X"
    assert put("advance_directive", {"value": ""}) == 201  # empty = cleared, allowed for free text


def test_emergency_payload_has_directives_with_label(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers, role="clinician")
    test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "yes", "note": "PRIVATE-NOTE"})
    test_client.put("/profile/directives/implanted_device", headers=ph, json={"value": "pacemaker"})
    test_client.put("/profile/directives/advance_directive", headers=ph, json={"value": "x"})
    test_client.put("/profile/directives/advance_directive", headers=ph, json={"value": ""})  # cleared -> hidden
    test_client.post(f"/patients/{patient.id}/directives", headers=sh,
                     json=_staff_body(kind="blood_transfusion", value="no", evidence_ref="BT-77"))
    card = test_client.post("/emergency/issue", headers=sh, json={"patient_id": patient.id})
    assert card.status_code == 200, card.text
    ref = card.json()["card_reference"]
    body = test_client.post("/emergency/scan", json={"card_reference": ref}, headers=sh).json()
    by_kind = {d["kind"]: d for d in body["directives"]}
    assert set(by_kind) == {"organ_donation", "implanted_device", "blood_transfusion"}
    assert by_kind["organ_donation"]["label"] == "patient-declared"
    assert by_kind["blood_transfusion"]["label"] == "recorded by staff (form BT-77)"
    assert set(by_kind["organ_donation"]) == {"kind", "value", "source", "label"}
    assert "PRIVATE-NOTE" not in str(body)
    # the unauthenticated public scan: yes/no/undecided kinds only, no free text, no form number
    pub = test_client.post("/emergency/scan", json={"card_reference": ref}).json()
    pk = {d["kind"]: d for d in pub["directives"]}
    assert set(pk) == {"organ_donation", "blood_transfusion"}
    assert pk["blood_transfusion"]["label"] == "recorded by staff"
    assert "BT-77" not in str(pub) and "pacemaker" not in str(pub) and "PRIVATE-NOTE" not in str(pub)


def test_bidi_and_zero_width_characters_are_stripped(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    r = test_client.put("/profile/directives/implanted_device", headers=ph, json={"value": "pace‮maker​"})
    assert r.json()["value"] == "pace maker"


def test_audit_rows_written_without_free_text(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    test_client.put("/profile/directives/implanted_device", headers=ph, json={"value": "SECRET-DEVICE"})
    test_client.post(f"/patients/{patient.id}/directives", headers=sh, json=_staff_body(note="SECRET-NOTE"))
    db_session.expire_all()
    rows = db_session.query(models.AuditLog).filter_by(patient_id=patient.id, action="write_critical_directive").all()
    assert sorted(r.detail for r in rows) == ["kind=implanted_device source=patient", "kind=organ_donation source=staff"]
    assert "SECRET" not in " ".join(r.detail for r in rows)


def test_stale_save_is_a_conflict_and_changes_nothing(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    first = test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "yes"}).json()
    # staff open the form on `first`, meanwhile the patient changes their mind
    test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "no"})
    r = test_client.post(f"/patients/{patient.id}/directives", headers=sh,
                         json=_staff_body(value="yes", based_on=first["id"]))
    assert r.status_code == 409 and "changed by someone else" in r.json()["detail"]
    assert [d.value for d in _rows(db_session, patient.id)].count("yes") == 1  # only the patient's first row


def test_same_version_cannot_win_twice(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    base = test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "yes"}).json()["id"]
    a = test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "no", "based_on": base})
    b = test_client.put("/profile/directives/organ_donation", headers=ph, json={"value": "undecided", "based_on": base})
    assert (a.status_code, b.status_code) == (201, 409)


def test_receptionist_can_read_but_not_record_staff_entries(test_client, db_session, make_user, auth_headers):
    fac, patient, staff, login, sh, ph = _setup(db_session, make_user, auth_headers)
    rec = auth_headers(make_user(role="receptionist", facility=fac))
    assert test_client.get(f"/patients/{patient.id}/directives", headers=rec).status_code == 200
    assert test_client.post(f"/patients/{patient.id}/directives", headers=rec,
                            json=_staff_body(based_on="")).status_code == 403
