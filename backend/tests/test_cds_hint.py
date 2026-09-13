"""P4.3b — /consultation/tickets/{id}/cds-hint: local-LLM advisory text +
deterministic allergy-conflict check, gated by the same room-ownership rule
as sign-off."""
from datetime import datetime

from app import models
from conftest import _facility, _make_patient


def _ticket(db, patient_id, facility, room_id, checked_in_by):
    ticket = models.QueueTicket(
        patient_id=patient_id, facility_name=facility, room_id=room_id,
        status="called", queue_number=1, queue_date=datetime.now().date().isoformat(),
        source="manual", checked_in_by=checked_in_by, reason="fever",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _room_and_claim(db, user, facility):
    room = models.ConsultationRoom(facility_name=facility, room_name="SOAP 1", active=True)
    db.add(room)
    db.flush()
    db.add(models.StaffClockEvent(user_id=user.id, facility_name=facility))
    db.add(models.RoomClaim(facility_name=facility, room_id=room.id, user_id=user.id))
    db.commit()
    return room


def test_cds_hint_uses_local_llm_and_flags_allergy_conflict(db_session, test_client, make_user, auth_headers, monkeypatch):
    monkeypatch.setattr("app.ai.cds_hint.generate_text", lambda *a, **kw: "- Consider viral URI\n- No red flags")

    facility = _facility("CDS")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    db_session.add(models.AllergyIntolerance(patient_id=patient.id, substance="Penicillin", severity="severe"))
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="Penicillin V", active=True))
    db_session.commit()
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    resp = test_client.post(
        f"/consultation/tickets/{ticket.id}/cds-hint",
        headers=auth_headers(clinician),
        json={"subjective": "cough for 2 days"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "viral URI" in body["hint"]
    assert any("Penicillin" in c for c in body["allergy_conflicts"])
    assert "reference aid" in body["disclaimer"].lower()


def test_cds_hint_falls_back_to_no_hint_but_keeps_allergy_check(db_session, test_client, make_user, auth_headers, monkeypatch):
    monkeypatch.setattr("app.ai.cds_hint.generate_text", lambda *a, **kw: None)

    facility = _facility("CDS")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    db_session.add(models.AllergyIntolerance(patient_id=patient.id, substance="Penicillin", severity="severe"))
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="Penicillin V", active=True))
    db_session.commit()
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    resp = test_client.post(
        f"/consultation/tickets/{ticket.id}/cds-hint", headers=auth_headers(clinician), json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hint"] is None
    assert any("Penicillin" in c for c in body["allergy_conflicts"])


def test_cds_hint_requires_a_claimed_room(db_session, test_client, make_user, auth_headers):
    facility = _facility("CDS")
    owner = make_user(role="clinician", facility=facility)
    other = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, owner, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, owner.id)

    resp = test_client.post(
        f"/consultation/tickets/{ticket.id}/cds-hint", headers=auth_headers(other), json={},
    )
    assert resp.status_code == 409
