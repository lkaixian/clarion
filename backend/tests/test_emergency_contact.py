"""Emergency contact: shown to a scanner only by role, and alerted on every scan -- in the
CLARION app if the contact is a registered patient, otherwise by SMS -- through the retrying
job queue so a dead network or gateway delays the alert instead of losing it."""
import uuid
from datetime import datetime, timedelta, timezone

from app import contact_notify, jobs, models, sms_service


import pytest


@pytest.fixture(autouse=True)
def _clean_jobs(db_session):
    """Contact jobs queued by one test must not be delivered by the next one's drain."""
    def wipe():
        db_session.rollback()
        db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).delete()
        for row in db_session.query(models.Patient).filter(models.Patient.phone.isnot(None)).all():
            if contact_notify.normalize_phone(row.phone) == "60123456789":  # numbers other tests here gave to patients
                row.phone = None
        db_session.commit()
    wipe()
    yield
    wipe()


def _patient(db_session, **kw):
    p = models.Patient(
        full_name="Siti Aminah", date_of_birth="1958-02-02", blood_type="A+",
        emergency_contact_name="Hafiz", emergency_contact_relationship="son",
        emergency_contact_phone="012-345 6789", **kw)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _card(test_client, db_session, make_user, auth_headers, patient):
    clinician = make_user(role="clinician", facility="Contact Hospital")
    ward = models.Ward(facility_name="Contact Hospital", ward_name=f"W{uuid.uuid4().hex[:4]}", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Contact Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    resp = test_client.post("/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id})
    assert resp.status_code == 200, resp.text
    return resp.json()["card_reference"]


def _scan(test_client, card, headers=None):
    resp = test_client.post("/emergency/scan", headers=headers or {}, json={"card_reference": card})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _drain(db_session):
    while jobs.run_pending(db_session):
        pass


def test_contact_is_visible_to_responders_and_clinicians_but_not_the_public(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    assert "emergency_contact" not in _scan(test_client, card)
    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    seen = _scan(test_client, card, headers=auth_headers(guard))["emergency_contact"]
    assert seen == {"name": "Hafiz", "relationship": "son", "phone": "012-345 6789"}


def test_unregistered_contact_gets_an_sms_with_no_clinical_data(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append((to, text)) or True)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)  # public tier: the alert is queued but the response says nothing about it
    _drain(db_session)
    assert len(sent) == 1
    to, text = sent[0]
    assert to == "60123456789"
    assert "Siti" in text and "A+" not in text and "Warfarin" not in text and "1958" not in text


def test_registered_contact_gets_the_app_alert_and_the_sms(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    hafiz = models.Patient(full_name="Hafiz Bin Ali", date_of_birth="1985-01-01", phone="+60 12-3456789")
    db_session.add(hafiz)
    db_session.commit()
    db_session.refresh(hafiz)
    hafiz_account = make_user(role="patient", patient_id=hafiz.id)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    _drain(db_session)
    rows = db_session.query(models.Notification).filter_by(user_id=hafiz_account.id, kind="contact_card_scanned").all()
    assert len(rows) == 1 and rows[0].urgent and "Siti" in rows[0].title
    assert sent == ["60123456789"]  # never replaced by the in-app alert


def test_a_squatter_claiming_the_contacts_number_cannot_stop_the_sms(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    squatter = models.Patient(full_name="Mallory", date_of_birth="1990-01-01", phone="012 345 6789")  # the real contact's number
    db_session.add(squatter)
    db_session.commit()
    db_session.refresh(squatter)
    make_user(role="patient", patient_id=squatter.id)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    _drain(db_session)
    assert sent == ["60123456789"]


def test_a_retried_sms_never_duplicates_the_in_app_alert(test_client, db_session, make_user, auth_headers, monkeypatch):
    state = {"up": False}
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: state["up"])
    hafiz = models.Patient(full_name="Hafiz Bin Ali", date_of_birth="1985-01-01", phone="+60 12-3456789")
    db_session.add(hafiz)
    db_session.commit()
    db_session.refresh(hafiz)
    account = make_user(role="patient", patient_id=hafiz.id)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    job = db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).first()
    jobs.run_pending(db_session)  # SMS down: no in-app alert yet either
    assert db_session.query(models.Notification).filter_by(user_id=account.id, kind="contact_card_scanned").count() == 0
    state["up"] = True
    db_session.refresh(job)
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    db_session.commit()
    jobs.run_pending(db_session)
    assert db_session.query(models.Notification).filter_by(user_id=account.id, kind="contact_card_scanned").count() == 1


def test_a_phone_shared_by_two_patients_falls_back_to_sms(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    for name in ("Family One", "Family Two"):
        p = models.Patient(full_name=name, date_of_birth="1990-01-01", phone="0123456789")
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)
        make_user(role="patient", patient_id=p.id)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    _drain(db_session)
    assert sent == ["60123456789"]


def test_repeat_scans_inside_the_window_alert_once(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    results = [_scan(test_client, card, headers=auth_headers(guard))["family_notification"] for _ in range(3)]
    _drain(db_session)
    assert results == ["queued", "throttled", "throttled"] and len(sent) == 1


def test_no_contact_means_no_job(test_client, db_session, make_user, auth_headers):
    p = models.Patient(full_name="No Contact", date_of_birth="1970-01-01")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    card = _card(test_client, db_session, make_user, auth_headers, p)
    before = db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).count()
    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    assert _scan(test_client, card, headers=auth_headers(guard))["family_notification"] == "none"
    assert db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).count() == before


def test_outage_delays_the_alert_instead_of_losing_it(test_client, db_session, make_user, auth_headers, monkeypatch):
    """Gateway down: the job stays pending (spaced retries); once it is back, the alert goes out."""
    state = {"up": False, "sent": 0}

    def flaky(to, text):
        if state["up"]:
            state["sent"] += 1
        return state["up"]

    monkeypatch.setattr(sms_service, "send_sms", flaky)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    job = db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).order_by(models.Job.created_at.desc()).first()

    jobs.run_pending(db_session)
    db_session.refresh(job)
    assert job.status == "pending" and job.attempts == 1 and state["sent"] == 0

    assert jobs.run_pending(db_session) is False  # 5-minute spacing: not retried straight away

    state["up"] = True
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)  # the spacing has elapsed
    db_session.commit()
    jobs.run_pending(db_session)
    db_session.refresh(job)
    assert job.status == "done" and state["sent"] == 1


def test_gives_up_after_the_retry_budget(test_client, db_session, make_user, auth_headers, monkeypatch):
    monkeypatch.setattr(sms_service, "send_sms", lambda *a: False)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    job = db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).order_by(models.Job.created_at.desc()).first()
    for _ in range(20):
        job.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        jobs.run_pending(db_session)
        db_session.refresh(job)
    assert job.status == "failed" and job.attempts == 20


def test_offline_tag_upload_alerts_the_contact_later(test_client, db_session, make_user, auth_headers, monkeypatch):
    from app import auth, tag_crypto
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    patient = _patient(db_session)
    clinician = make_user(role="clinician", facility="Contact Hospital")
    ward = models.Ward(facility_name="Contact Hospital", ward_name="WO", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Contact Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    uid = f"04{uuid.uuid4().hex[:12]}".upper()
    assert test_client.post("/emergency/nfc/register", headers=auth_headers(clinician),
                            json={"patient_id": patient.id, "nfc_uid": uid}).status_code == 200

    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    read_at = datetime.now(timezone.utc).isoformat()
    entry_hash = tag_crypto.read_entry_hash(tag_crypto.GENESIS_HASH, 0, read_at, auth.canonical_nfc_uid(uid), 1, "decrypted")
    resp = test_client.post("/emergency/offline-reads", headers=auth_headers(guard), json={
        "device_id": "device-0001",
        "entries": [{"seq": 0, "read_at": read_at, "nfc_uid": uid, "key_id": 1, "outcome": "decrypted",
                     "prev_hash": tag_crypto.GENESIS_HASH, "entry_hash": entry_hash}]})
    assert resp.status_code == 200, resp.text
    _drain(db_session)
    assert sent == ["60123456789"]


def test_phone_normalisation():
    n = contact_notify.normalize_phone
    assert n("012-345 6789") == n("+60 12 3456789") == n("0060123456789") == "60123456789"
    assert n("") is None and n(None) is None and n("123") is None


def test_sms_log_provider_is_refused_outside_demo(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "log")
    monkeypatch.setenv("APP_ENV", "production")
    assert sms_service.send_sms("60123456789", "x") is False
    monkeypatch.setenv("APP_ENV", "demo")
    assert sms_service.send_sms("60123456789", "x") is True
    monkeypatch.delenv("SMS_PROVIDER")
    assert sms_service.send_sms("60123456789", "x") is False


# ---- hardening from the security review -------------------------------------------------

def test_public_scan_reveals_nothing_about_the_contact_or_the_alert(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    body = _scan(test_client, card)
    assert "family_notification" not in body and "emergency_contact" not in body
    assert "Hafiz" not in str(body) and "6789" not in str(body)
    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    assert _scan(test_client, card, headers=auth_headers(guard))["family_notification"] in ("queued", "throttled")


def test_a_failing_alert_queue_never_fails_the_scan_or_its_audit_row(test_client, db_session, make_user, auth_headers, monkeypatch):
    patient = _patient(db_session)
    card = _card(test_client, db_session, make_user, auth_headers, patient)
    monkeypatch.setattr(contact_notify, "queue", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db locked")))
    guard = make_user(role="emergency_responder", facility="Contact Hospital")
    body = _scan(test_client, card, headers=auth_headers(guard))
    assert body["family_notification"] == "error"
    assert db_session.query(models.AuditLog).filter_by(patient_id=patient.id, action="emergency_access").count() == 1


def test_nfc_scan_alerts_the_contact_too(test_client, db_session, make_user, auth_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: sent.append(to) or True)
    patient = _patient(db_session)
    clinician = make_user(role="clinician", facility="Contact Hospital")
    ward = models.Ward(facility_name="Contact Hospital", ward_name="WN", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Contact Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    uid = f"04{uuid.uuid4().hex[:12]}".upper()
    assert test_client.post("/emergency/nfc/register", headers=auth_headers(clinician),
                            json={"patient_id": patient.id, "nfc_uid": uid}).status_code == 200
    assert test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).status_code == 200
    _drain(db_session)
    assert sent == ["60123456789"]


def test_only_plausible_malaysian_mobiles_are_ever_texted():
    from app import phone
    assert contact_notify.normalize_phone("012-3456789 ext 5") is None  # no digit-gluing
    assert contact_notify.normalize_phone("call Hafiz 0123456789") is None
    assert phone.sms_allowed(contact_notify.normalize_phone("07700 900123")) is False  # UK-looking, becomes 60 7700...
    assert phone.sms_allowed(contact_notify.normalize_phone("+44 7700 900123")) is False
    assert phone.sms_allowed(contact_notify.normalize_phone("1-900-555-0100")) is False  # premium
    assert phone.sms_allowed(contact_notify.normalize_phone("012-345 6789")) is True


def test_profile_update_rejects_a_number_we_would_not_text():
    import pytest
    from pydantic import ValidationError
    from app import schemas
    with pytest.raises(ValidationError):
        schemas.PatientProfileUpdate(emergency_contact_phone="+44 7700 900123")
    assert schemas.PatientProfileUpdate(emergency_contact_phone="012-345 6789").emergency_contact_phone
    assert schemas.PatientProfileUpdate(emergency_contact_phone=None).emergency_contact_phone is None


def test_one_phone_number_cannot_be_used_to_spam_across_many_records(test_client, db_session, make_user, auth_headers):
    results = []
    for i in range(contact_notify.MAX_PER_DESTINATION_PER_HOUR + 1):
        p = _patient(db_session)  # every record names the same contact number
        results.append(contact_notify.safe_queue(db_session, p))
    assert results == ["queued"] * contact_notify.MAX_PER_DESTINATION_PER_HOUR + ["throttled"]


def test_the_per_patient_window_reopens_after_ten_minutes(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    assert contact_notify.safe_queue(db_session, patient) == "queued"
    assert contact_notify.safe_queue(db_session, patient) == "throttled"
    db_session.query(models.Patient).filter_by(id=patient.id).update(
        {"emergency_contact_notified_at": datetime.now(timezone.utc) - timedelta(minutes=11)})
    db_session.commit()
    db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).delete()  # keep the per-number cap out of it
    db_session.commit()
    assert contact_notify.safe_queue(db_session, patient) == "queued"


def test_a_number_the_gateway_rejects_for_good_fails_at_once_not_twenty_times(test_client, db_session, make_user, auth_headers, monkeypatch):
    def reject(*a):
        raise sms_service.SmsRejected("Twilio status 400")
    monkeypatch.setattr(sms_service, "send_sms", reject)
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    _scan(test_client, card)
    job = db_session.query(models.Job).filter_by(kind=contact_notify.JOB_KIND).first()
    jobs.run_pending(db_session)
    db_session.refresh(job)
    assert job.status == "failed" and job.attempts == 1


def test_offline_read_of_a_deleted_patient_is_ignored_not_fatal(db_session):
    assert contact_notify.safe_queue(db_session, None, late=True) == "none"


def test_a_late_offline_report_says_so(test_client, db_session, make_user, auth_headers, monkeypatch):
    texts = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, text: texts.append(text) or True)
    patient = _patient(db_session)
    assert contact_notify.safe_queue(db_session, patient, late=True) == "queued"
    _drain(db_session)
    assert "without network" in texts[0] and "Siti" in texts[0]
