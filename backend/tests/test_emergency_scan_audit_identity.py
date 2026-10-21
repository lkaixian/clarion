"""Security Audit M6 — the emergency-scan audit "actor" was unverified
free-text (`responder_name` / `responder_org` from the request body), never
distinguishable from a confirmed identity.

Fix (app/routers/emergency.py::_responder_audit + auth.get_optional_current_user):
the scan endpoints stay unauthenticated, but
  - no/invalid token -> audited EXACTLY as before: actor
    `public_unverified:<name>`, actor_role `public_unverified` (renamed from
    `emergency_responder`, which is now only a verified responder account)
  - valid staff token -> actor = the real user id, actor_role = their role,
    actor_facility recorded, detail carries `verified` + the typed-in name
    as `self_asserted=`
  - broken/expired token -> same as no token (never a 401)

The audit *action* string is deliberately unchanged (`emergency_access` /
`_nfc` / `_failed`) -- audit_log_screen.dart switches on it. The
verified/unverified distinction is: real user id + real role (verified) vs
the `public_unverified:` / `public_unverified` shape.
"""
from app import models


def _make_patient(db_session, **kw):
    p = models.Patient(
        full_name=kw.pop("full_name", "M6 Patient"),
        date_of_birth=kw.pop("date_of_birth", "1975-06-06"),
        **kw,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _issue_card(test_client, db_session, make_user, auth_headers, patient):
    """Issue a live QR card for `patient` via a clinician present at their
    facility (the H1/P2.1 facility-presence rule)."""
    clinician = make_user(role="clinician", facility="Issuer Hospital")
    ward = models.Ward(facility_name="Issuer Hospital", ward_name="W", total_beds=4)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(
        facility_name="Issuer Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1,
    ))
    db_session.commit()
    resp = test_client.post(
        "/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["card_reference"]


def _audit_rows(db_session, patient_id, action_prefix):
    return [
        r for r in db_session.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id)
        .all()
        if r.action.startswith(action_prefix)
    ]


def test_unauthenticated_scan_logs_unverified_actor(test_client, db_session, make_user, auth_headers):
    patient = _make_patient(db_session)
    card_ref = _issue_card(test_client, db_session, make_user, auth_headers, patient)

    resp = test_client.post(
        "/emergency/scan",
        json={"card_reference": card_ref, "responder_name": "Bomba Ali", "responder_org": "JBPM"},
    )
    assert resp.status_code == 200, resp.text

    rows = _audit_rows(db_session, patient.id, "emergency_access")
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "emergency_access"  # action string unchanged
    # unverified path is byte-for-byte the pre-M6 shape
    assert row.actor == "public_unverified:Bomba Ali"
    assert row.actor_role == "public_unverified"
    assert row.actor_facility is None
    assert row.detail == "org=JBPM"


def test_authenticated_scan_binds_real_identity(test_client, db_session, make_user, auth_headers):
    patient = _make_patient(db_session, full_name="M6 Verified")
    card_ref = _issue_card(test_client, db_session, make_user, auth_headers, patient)

    responder = make_user(role="clinician", facility="Responder Hospital")
    resp = test_client.post(
        "/emergency/scan",
        headers=auth_headers(responder),
        json={"card_reference": card_ref, "responder_name": "typed name", "responder_org": "ED"},
    )
    assert resp.status_code == 200, resp.text

    rows = _audit_rows(db_session, patient.id, "emergency_access")
    row = next(r for r in rows if r.action == "emergency_access" and r.actor == responder.id)
    assert row.actor_role == "clinician"
    assert row.actor_facility == "Responder Hospital"
    assert "verified" in (row.detail or "")
    assert "self_asserted=typed name" in (row.detail or "")


def test_failed_scan_unauthenticated_is_unverified(test_client, db_session):
    resp = test_client.post(
        "/emergency/scan",
        json={"card_reference": "totally-bogus", "responder_name": "X", "responder_org": "Y"},
    )
    assert resp.status_code == 404
    rows = [
        r for r in db_session.query(models.AuditLog)
        .filter(models.AuditLog.action == "emergency_access_failed").all()
        if "totally-bogus" in (r.detail or "")
    ]
    assert rows and rows[-1].actor == "public_unverified:X"
    assert rows[-1].actor_role == "public_unverified"


def test_nfc_scan_authenticated_binds_identity(test_client, db_session, make_user, auth_headers):
    patient = _make_patient(db_session, full_name="M6 NFC")
    staff = make_user(role="records_officer", facility="NFC Hospital")
    # register a card, present at facility
    ward = models.Ward(facility_name="NFC Hospital", ward_name="W", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(
        facility_name="NFC Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1,
    ))
    db_session.commit()
    reg = test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "nfc_uid": "04:AA:BB:CC:DD:EE:01"},
    )
    assert reg.status_code == 200, reg.text

    responder = make_user(role="clinician", facility="Field Unit")
    scan = test_client.post(
        "/emergency/nfc/scan",
        headers=auth_headers(responder),
        json={"nfc_uid": "04:AA:BB:CC:DD:EE:01", "responder_org": "Ambulance"},
    )
    assert scan.status_code == 200, scan.text
    rows = _audit_rows(db_session, patient.id, "emergency_access_nfc")
    assert any(
        r.action == "emergency_access_nfc"
        and r.actor == responder.id
        and r.actor_role == "clinician"
        for r in rows
    )


def test_broken_token_falls_back_to_unverified_no_401(test_client, db_session, make_user, auth_headers):
    patient = _make_patient(db_session, full_name="M6 BadToken")
    card_ref = _issue_card(test_client, db_session, make_user, auth_headers, patient)

    resp = test_client.post(
        "/emergency/scan",
        headers={"Authorization": "Bearer not.a.real.jwt"},
        json={"card_reference": card_ref, "responder_name": "Fallback", "responder_org": "Z"},
    )
    assert resp.status_code == 200, resp.text  # not 401
    rows = _audit_rows(db_session, patient.id, "emergency_access")
    assert rows[-1].action == "emergency_access"
    assert rows[-1].actor == "public_unverified:Fallback"
    assert rows[-1].actor_role == "public_unverified"


def test_sharing_bypass_row_uses_the_responder_identity(test_client, db_session, make_user, auth_headers):
    """_audit_sharing_bypass_if_any changed signature (payload -> ident) --
    confirm the bypass row is attributed the same way as the access row: a
    verified staff caller -> real id; the bypass fires only when a facility
    that authored some of the patient's data has opted out of public
    sharing."""
    patient = _make_patient(db_session, full_name="M6 Bypass")
    card_ref = _issue_card(test_client, db_session, make_user, auth_headers, patient)

    # An opted-out facility authored one of this patient's conditions.
    db_session.add(models.HospitalSetting(
        facility_name="Secretive Clinic", records_shared_publicly=False,
    ))
    db_session.add(models.Condition(
        patient_id=patient.id, name="Hidden", status="active",
        authored_by_facility="Secretive Clinic", critical_for_emergency=True,
    ))
    db_session.commit()

    responder = make_user(role="clinician", facility="Field Unit B")
    resp = test_client.post(
        "/emergency/scan",
        headers=auth_headers(responder),
        json={"card_reference": card_ref, "responder_org": "ED"},
    )
    assert resp.status_code == 200, resp.text

    bypass = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient.id, action="emergency_access_sharing_bypass")
        .first()
    )
    assert bypass is not None
    assert bypass.actor == responder.id
    assert bypass.actor_role == "clinician"
    assert bypass.actor_facility == "Field Unit B"
