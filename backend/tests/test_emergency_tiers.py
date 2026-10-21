"""Role-based scan tiers: what a scan returns is grant.scope (the patient's consent)
intersected with a ceiling set by the scanner's verified account. Nothing the caller
types (responder_name / responder_org) can raise the tier."""
import uuid

from app import models


def _patient(db_session):
    p = models.Patient(full_name="Tier Patient", date_of_birth="1960-03-03", blood_type="O+")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    db_session.add_all([
        models.AllergyIntolerance(patient_id=p.id, substance="Penicillin", severity="severe", critical_for_emergency=True),
        models.Condition(patient_id=p.id, name="Epilepsy", critical_for_emergency=True),
        models.MedicationStatement(patient_id=p.id, drug_name="Warfarin", dosage="5mg", frequency="daily",
                          active=True, critical_for_emergency=True),
    ])
    db_session.commit()
    return p


def _card(test_client, db_session, make_user, auth_headers, patient, scope=None):
    clinician = make_user(role="clinician", facility="Tier Hospital")
    ward = models.Ward(facility_name="Tier Hospital", ward_name="W", total_beds=4)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Tier Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    body = {"patient_id": patient.id, **({"scope": scope} if scope else {})}
    resp = test_client.post("/emergency/issue", headers=auth_headers(clinician), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["card_reference"]


def _scan(test_client, card_ref, headers=None, **extra):
    resp = test_client.post("/emergency/scan", headers=headers or {}, json={"card_reference": card_ref, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_public_scan_gets_only_the_flags_that_change_first_aid(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    body = _scan(test_client, card)
    assert body["tier"] == "public"
    assert body["full_name"] is None and body["age"] is None
    assert [a["substance"] for a in body["allergies"]] == ["Penicillin"]
    assert body["conditions"] == ["Epilepsy"]
    assert "blood_type" not in body and "medications" not in body


def test_typed_credentials_cannot_raise_the_tier(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    body = _scan(test_client, card, responder_name="Dr Real", responder_org="JBPM Ambulance")
    assert body["tier"] == "public" and body["full_name"] is None


def test_responder_account_sees_identity_and_blood_type_but_not_medications(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    body = _scan(test_client, card, headers=auth_headers(guard))
    assert body["tier"] == "responder"
    assert body["full_name"] == "Tier Patient" and body["blood_type"] == "O+"
    assert "medications" not in body


def test_clinical_account_sees_medications(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    doctor = make_user(role="clinician", facility="Tier Hospital")
    body = _scan(test_client, card, headers=auth_headers(doctor))
    assert body["tier"] == "clinical"
    assert body["medications"][0]["drug_name"] == "Warfarin"


def test_patient_account_scanning_someone_elses_card_is_public(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    bystander = make_user(role="patient")
    assert _scan(test_client, card, headers=auth_headers(bystander))["tier"] == "public"


def test_grant_scope_is_a_ceiling_even_for_clinicians(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session), scope=["allergies"])
    doctor = make_user(role="clinician", facility="Tier Hospital")
    body = _scan(test_client, card, headers=auth_headers(doctor))
    assert "blood_type" not in body and "medications" not in body and "conditions" not in body
    assert [a["substance"] for a in body["allergies"]] == ["Penicillin"]


def test_scan_above_public_notifies_the_patient_and_public_does_not(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    owner = make_user(role="patient", patient_id=patient.id)
    card = _card(test_client, db_session, make_user, auth_headers, patient)

    _scan(test_client, card)
    assert db_session.query(models.Notification).filter_by(user_id=owner.id).count() == 0

    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    _scan(test_client, card, headers=auth_headers(guard))
    rows = db_session.query(models.Notification).filter_by(user_id=owner.id, kind="card_scanned").all()
    assert len(rows) == 1 and rows[0].urgent and "responder" in rows[0].body


def test_audit_rows_record_tier_and_the_fields_actually_returned(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    card = _card(test_client, db_session, make_user, auth_headers, patient)
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    _scan(test_client, card, headers=auth_headers(guard))
    _scan(test_client, card, responder_org="Mall Security")

    rows = (db_session.query(models.AuditLog)
            .filter(models.AuditLog.patient_id == patient.id, models.AuditLog.action == "emergency_access")
            .order_by(models.AuditLog.timestamp).all())
    verified, unverified = rows[-2], rows[-1]
    assert verified.actor == guard.id and "tier=responder" in verified.detail
    assert "medications" not in verified.fields_accessed and "blood_type" in verified.fields_accessed
    assert unverified.actor_role == "public_unverified" and unverified.detail == "org=Mall Security"
    assert set(unverified.fields_accessed) == {"allergies", "conditions"}


def test_nfc_scan_uses_the_same_tiers(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    clinician = make_user(role="clinician", facility="Tier Hospital")
    ward = models.Ward(facility_name="Tier Hospital", ward_name="W2", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Tier Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    uid = f"04{uuid.uuid4().hex[:12]}".upper()
    reg = test_client.post("/emergency/nfc/register", headers=auth_headers(clinician),
                           json={"patient_id": patient.id, "nfc_uid": uid})
    assert reg.status_code == 200, reg.text

    public = test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).json()
    assert public["tier"] == "public" and public["full_name"] is None
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    verified = test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}, headers=auth_headers(guard)).json()
    assert verified["tier"] == "responder" and verified["blood_type"] == "O+"


def test_one_unread_alert_per_window_not_one_per_scan(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    owner = make_user(role="patient", patient_id=patient.id)
    card = _card(test_client, db_session, make_user, auth_headers, patient)
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    for _ in range(3):
        _scan(test_client, card, headers=auth_headers(guard))
    assert db_session.query(models.Notification).filter_by(user_id=owner.id, kind="card_scanned").count() == 1


def test_role_mappings_and_public_tier_hides_omitted_counts(test_client, db_session, make_user, auth_headers):
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    expected = {"receptionist": "responder", "admin": "clinical", "pharmacist": "clinical", "records_officer": "clinical"}
    for role, tier in expected.items():
        user = make_user(role=role, facility="Tier Hospital")
        assert _scan(test_client, card, headers=auth_headers(user))["tier"] == tier, role
    assert _scan(test_client, card)["omitted_non_critical"] == {}


def test_expired_responder_account_falls_back_to_public(test_client, db_session, make_user, auth_headers):
    from datetime import datetime, timedelta, timezone
    card = _card(test_client, db_session, make_user, auth_headers, _patient(db_session))
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    headers = auth_headers(guard)
    guard.access_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db_session.commit()
    assert _scan(test_client, card, headers=headers)["tier"] == "public"


def test_nfc_responder_never_gets_medications_and_history_parses_verified_rows(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    clinician = make_user(role="clinician", facility="Tier Hospital")
    ward = models.Ward(facility_name="Tier Hospital", ward_name="W3", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Tier Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()
    uid = f"04{uuid.uuid4().hex[:12]}".upper()
    assert test_client.post("/emergency/nfc/register", headers=auth_headers(clinician),
                            json={"patient_id": patient.id, "nfc_uid": uid}).status_code == 200
    guard = make_user(role="emergency_responder", facility="Tier Hospital")
    body = test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid, "responder_org": "Mall Security"},
                            headers=auth_headers(guard)).json()
    assert "medications" not in body
    row = (db_session.query(models.AuditLog)
           .filter(models.AuditLog.patient_id == patient.id, models.AuditLog.action == "emergency_access_nfc").one())
    assert "tier=responder" in row.detail


def test_anomaly_detector_ignores_public_unverified_actors():
    from app import security_analytics
    assert not security_analytics._is_real_staff_actor("public_unverified:Ali")
