"""The scanner's phone can report where it is: the patient and their emergency contact get a map link,
it is stored (and listed) for the patient and for staff who may see them, and a late fix can follow the
scan through a short-lived signed token. Coordinates are unverified by nature, so they are validated,
labelled "reported", and never change what the scanner may see."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import auth, contact_notify, jobs, models, sms_service
from app.routers import emergency

LOC = {"lat": 3.139003, "lng": 101.686855, "accuracy_m": 12.5}
URL = "https://maps.google.com/?q=3.139003,101.686855"


@pytest.fixture(autouse=True)
def _clean_jobs(db_session):
    def wipe():
        db_session.rollback()
        db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).delete()
        db_session.commit()
    wipe()
    yield
    wipe()


def _patient(db_session):
    p = models.Patient(
        full_name="Siti Aminah", date_of_birth="1958-02-02", blood_type="A+",
        emergency_contact_name="Hafiz", emergency_contact_relationship="son",
        emergency_contact_phone=f"012-{uuid.uuid4().int % 10**7:07d}")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _present(db_session, patient, facility):
    ward = models.Ward(facility_name=facility, ward_name=f"W{uuid.uuid4().hex[:4]}", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name=facility, patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()


def _card(test_client, db_session, make_user, auth_headers, patient, facility="Loc Hospital"):
    clinician = make_user(role="clinician", facility=facility)
    _present(db_session, patient, facility)
    resp = test_client.post("/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id})
    assert resp.status_code == 200, resp.text
    return resp.json()["card_reference"], clinician


def _scan(test_client, card, headers=None, location=None):
    body = {"card_reference": card}
    if location is not None:
        body["location"] = location
    resp = test_client.post("/emergency/scan", headers=headers or {}, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _drain(db_session):
    while jobs.run_pending(db_session):
        pass


def _sms(monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(text) or True)
    return sent


def test_a_located_scan_texts_the_contact_a_map_link_and_who_scanned(test_client, db_session, make_user,
                                                                     auth_headers, monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    medic = make_user(role="emergency_responder", facility="Crew Station", responder_tier="paramedic",
                      access_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3))
    r = _scan(test_client, card, auth_headers(medic), LOC)
    assert r["tier"] == "paramedic" and r["location_token"]
    _drain(db_session)
    assert len(sent) == 1
    assert "by a paramedic (Crew Station)" in sent[0] and URL in sent[0]
    row = db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).one()
    assert (row.lat, row.lng, row.accuracy_m, row.tier) == (LOC["lat"], LOC["lng"], 12.5, "paramedic")


def test_a_scan_without_a_location_is_unchanged(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    r = _scan(test_client, card)
    _drain(db_session)
    assert "maps.google.com" not in sent[0] and "an unidentified person" in sent[0]
    assert db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).count() == 0
    assert r["location_token"]  # a late fix can still follow


def test_a_responders_location_gets_through_after_a_bystanders_scan(test_client, db_session, make_user,
                                                                   auth_headers, monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card)  # a bystander first: this claims the 10-minute window
    guard = make_user(role="emergency_responder", facility="Crew Station",
                      access_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3))
    _scan(test_client, card, auth_headers(guard), LOC)  # the responder, with a position
    _drain(db_session)
    assert len(sent) == 2 and URL in sent[1] and "a responder" in sent[1]


def test_the_patients_own_account_is_told_where(test_client, db_session, make_user, auth_headers, monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    account = make_user(role="patient", patient_id=patient.id)
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card, auth_headers(clinician), LOC)
    note = db_session.query(models.Notification).filter_by(user_id=account.id, kind="card_scanned").one()
    assert URL in note.body and note.link == URL and note.urgent


def test_a_late_fix_follows_the_scan_with_the_signed_token(test_client, db_session, make_user, auth_headers,
                                                          monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    token = _scan(test_client, card)["location_token"]
    _drain(db_session)
    ok = test_client.post("/emergency/location", json={"token": token, "location": LOC})
    assert ok.status_code == 200, ok.text
    _drain(db_session)
    assert len(sent) == 2 and "new location" in sent[1] and URL in sent[1]
    assert db_session.query(models.ScanLocation).filter_by(patient_id=patient.id, tier="public").count() == 1


def test_only_a_real_one_use_token_from_a_still_valid_card_is_accepted(test_client, db_session, make_user,
                                                                     auth_headers, monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    login = auth.create_access_token({"sub": "someone", "role": "patient"})  # a real access token
    for junk in (login, "x" * 40, "not-a-token-at-all"):
        assert test_client.post("/emergency/location", json={"token": junk, "location": LOC}).status_code == 400

    token = _scan(test_client, card)["location_token"]
    assert patient.id not in token and "." not in token  # opaque: nothing readable, not a JWT
    assert test_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert test_client.post("/emergency/location", json={"token": token, "location": LOC}).status_code == 200
    again = test_client.post("/emergency/location", json={"token": token, "location": LOC})
    assert again.status_code == 400  # one use

    expired = _scan(test_client, card)["location_token"]
    db_session.query(models.ScanLocationGrant).filter_by(token_hash=emergency._loc_hash(expired)).update(
        {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    db_session.commit()
    assert test_client.post("/emergency/location", json={"token": expired, "location": LOC}).status_code == 400

    live = _scan(test_client, card)["location_token"]
    assert test_client.post(f"/emergency/revoke/{card}", headers=auth_headers(clinician)).status_code == 200
    assert test_client.post("/emergency/location", json={"token": live, "location": LOC}).status_code == 400


def test_an_identified_scans_token_only_works_for_that_scanner(test_client, db_session, make_user, auth_headers,
                                                              monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    medic = make_user(role="emergency_responder", facility="Crew A", responder_tier="paramedic",
                      access_expires_at=future)
    other = make_user(role="emergency_responder", facility="Crew B", access_expires_at=future)
    token = _scan(test_client, card, auth_headers(medic))["location_token"]
    body = {"token": token, "location": LOC}
    assert test_client.post("/emergency/location", json=body).status_code == 400  # anonymous replay
    assert test_client.post("/emergency/location", json=body, headers=auth_headers(other)).status_code == 400
    ok = test_client.post("/emergency/location", json=body, headers=auth_headers(medic))
    assert ok.status_code == 200
    row = db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).one()
    assert row.tier == "paramedic" and row.actor_facility == "Crew A"  # recorded at scan time, not claimed now


def test_bystanders_cannot_use_up_the_slots_a_responder_needs(db_session):
    patient = _patient(db_session)
    loc = {"lat": 3.1, "lng": 101.6}
    results = [contact_notify.queue(db_session, patient, location=loc, priority=True, update=True, pub=True)
               for _ in range(3)]
    assert results == ["queued", "queued", "throttled"]  # unidentified senders: 2 per number per hour
    identified = [contact_notify.queue(db_session, patient, location=loc, priority=True, who="a paramedic")
                  for _ in range(contact_notify.MAX_PER_DESTINATION_PER_HOUR)]
    assert identified[:2] == ["queued", "queued"] and identified[-1] == "throttled"  # still bounded overall
    assert identified.count("queued") == contact_notify.MAX_PER_DESTINATION_PER_HOUR - 2


def test_a_public_late_fix_adds_at_most_one_location_text_per_window(test_client, db_session, make_user,
                                                                    auth_headers, monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    t1 = _scan(test_client, card)["location_token"]
    assert test_client.post("/emergency/location", json={"token": t1, "location": LOC}).status_code == 200
    db_session.query(models.Patient).filter_by(id=patient.id).update({"emergency_contact_notified_at": None})
    db_session.commit()
    t2 = _scan(test_client, card)["location_token"]
    assert test_client.post("/emergency/location", json={"token": t2, "location": LOC}).status_code == 200
    _drain(db_session)
    assert sum("new location" in t for t in sent) == 1  # the second bystander's fix is stored, not texted
    assert db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).count() == 2


def test_a_burst_of_positions_cannot_push_out_the_genuine_one(test_client, db_session, make_user, auth_headers,
                                                              monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    account = make_user(role="patient", patient_id=patient.id)
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    for i in range(emergency._MAX_LOCATIONS_PER_PATIENT_PER_10_MIN):
        db_session.add(models.ScanLocation(patient_id=patient.id, lat=1.0 + i / 1000, lng=2.0, tier="public"))
    db_session.commit()
    _scan(test_client, card, auth_headers(clinician), LOC)
    assert db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).count() == \
        emergency._MAX_LOCATIONS_PER_PATIENT_PER_10_MIN  # nothing new stored
    note = db_session.query(models.Notification).filter_by(user_id=account.id, kind="card_scanned").one()
    assert note.link is None and "maps.google.com" not in note.body  # the usual notice, but no position in it
    _drain(db_session)
    assert all("maps.google.com" not in t for t in sent)  # and no link sent for a position we did not keep


def test_a_poor_fix_is_called_approximate_and_an_unidentified_scanner_is_labelled(test_client, db_session, make_user,
                                                                                  auth_headers, monkeypatch):
    sent = _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card, None, {**LOC, "accuracy_m": 800})
    _drain(db_session)
    assert "approximate" in sent[0] and "unidentified person (position unverified)" in sent[0]
    db_session.query(models.Patient).filter_by(id=patient.id).update({"emergency_contact_notified_at": None})
    db_session.commit()
    _scan(test_client, card, None, {**LOC, "accuracy_m": 10})
    _drain(db_session)
    assert "approximate" not in sent[1]


def test_retention_covers_every_patient_not_just_the_one_being_written(test_client, db_session, make_user,
                                                                       auth_headers, monkeypatch):
    _sms(monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(days=models.SCAN_LOCATION_KEEP_DAYS + 1)
    other = _patient(db_session)
    other_account = make_user(role="patient", patient_id=other.id)
    db_session.add(models.ScanLocation(patient_id=other.id, lat=1.0, lng=1.0, tier="public", created_at=old))
    db_session.add(models.Notification(user_id=other_account.id, kind="card_scanned", title="x",
                                       link=URL, created_at=old))
    db_session.add(models.Job(kind=contact_notify.JOB_KIND, status="done", payload='{"loc": [1, 2]}',
                              created_at=datetime.now(timezone.utc) - timedelta(days=2)))
    db_session.commit()
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card, None, LOC)  # a located scan of a DIFFERENT patient triggers the purge
    assert db_session.query(models.ScanLocation).filter_by(patient_id=other.id).count() == 0
    assert db_session.query(models.Notification).filter_by(user_id=other_account.id).count() == 0
    assert db_session.query(models.Job).filter(models.Job.payload == '{"loc": [1, 2]}').count() == 0


def test_a_dropped_location_text_leaves_an_audit_row(test_client, db_session, make_user, auth_headers, monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    for _ in range(contact_notify.MAX_PER_DESTINATION_PER_HOUR):
        contact_notify.queue(db_session, patient, priority=True)  # the number's hourly cap is spent
    _scan(test_client, card, auth_headers(clinician), LOC)
    rows = db_session.query(models.AuditLog).filter_by(patient_id=patient.id,
                                                       action="emergency_contact_alert_throttled").count()
    assert rows == 1


def test_every_login_of_the_patient_gets_the_notice(test_client, db_session, make_user, auth_headers, monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    first = make_user(role="clinician", facility="Loc Hospital", patient_id=patient.id)
    db_session.add(models.UserRole(user_id=first.id, role="patient"))  # a nurse who is also this patient
    db_session.commit()
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card, auth_headers(clinician), LOC)
    assert db_session.query(models.Notification).filter_by(user_id=first.id, kind="card_scanned").count() == 1


@pytest.mark.parametrize("bad", [
    {"lat": 91, "lng": 10}, {"lat": 10, "lng": 181}, {"lat": 0, "lng": 0},
    {"lat": "x", "lng": 1}, {"lat": 1, "lng": 1, "accuracy_m": -5}, {"lat": 1, "lng": 1, "extra": 1},
])
def test_nonsense_coordinates_are_refused(test_client, db_session, make_user, auth_headers, bad):
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    r = test_client.post("/emergency/scan", json={"card_reference": card, "location": bad})
    assert r.status_code == 422


def test_a_location_never_widens_what_the_scanner_sees(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    r = _scan(test_client, card, None, LOC)
    assert r["tier"] == "public" and "emergency_contact" not in r and "family_notification" not in r


def test_who_may_list_the_scan_locations(test_client, db_session, make_user, auth_headers, monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    owner = make_user(role="patient", patient_id=patient.id)
    stranger_patient = _patient(db_session)
    stranger = make_user(role="patient", patient_id=stranger_patient.id)
    card, clinician = _card(test_client, db_session, make_user, auth_headers, patient)
    _scan(test_client, card, None, LOC)
    url = f"/emergency/locations/{patient.id}"
    mine = test_client.get(url, headers=auth_headers(owner))
    assert mine.status_code == 200 and mine.json()[0]["lat"] == LOC["lat"]
    assert test_client.get(url, headers=auth_headers(clinician)).status_code == 200  # present at their facility
    assert test_client.get(url, headers=auth_headers(stranger)).status_code == 403
    away = make_user(role="clinician", facility="Elsewhere Clinic")
    assert test_client.get(url, headers=auth_headers(away)).status_code == 403
    assert test_client.get(url).status_code == 401


def test_old_locations_are_purged_when_a_new_one_arrives(test_client, db_session, make_user, auth_headers,
                                                         monkeypatch):
    _sms(monkeypatch)
    patient = _patient(db_session)
    card, _ = _card(test_client, db_session, make_user, auth_headers, patient)
    db_session.add(models.ScanLocation(
        patient_id=patient.id, lat=1.0, lng=1.0, tier="public",
        created_at=datetime.now(timezone.utc) - timedelta(days=models.SCAN_LOCATION_KEEP_DAYS + 1)))
    db_session.commit()
    _scan(test_client, card, None, LOC)
    rows = db_session.query(models.ScanLocation).filter_by(patient_id=patient.id).all()
    assert [r.lat for r in rows] == [LOC["lat"]]
