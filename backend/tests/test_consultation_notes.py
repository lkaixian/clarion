"""P3.4 structured consultation-note lifecycle."""
from datetime import datetime
from app import models
from conftest import _TEST_SIGNATURE_B64, _facility, _make_patient


def _ticket(db, patient_id, facility, room_id, checked_in_by):
    ticket = models.QueueTicket(
        patient_id=patient_id, facility_name=facility, room_id=room_id,
        status="called", queue_number=1, queue_date=datetime.now().date().isoformat(), source="manual", checked_in_by=checked_in_by,
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


def test_complete_creates_signed_structured_note(test_client, db_session, make_user, auth_headers):
    facility = _facility("SOAP")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    response = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={
            "subjective": "Two days of cough", "objective": "Afebrile",
            "assessment": "Likely viral URI", "plan": "Rest and fluids",
            "treatment_plan": "Supportive care", "signature_b64": _TEST_SIGNATURE_B64,
        },
    )
    assert response.status_code == 200, response.text
    encounter_id = response.json()["encounter_id"]
    note = db_session.query(models.ConsultationNote).filter_by(encounter_id=encounter_id).one()
    assert note.patient_id == patient.id
    assert note.facility_name == facility
    assert note.assessment == "Likely viral URI"
    assert note.signed_by == clinician.id

    got = test_client.get(f"/consultation/encounters/{encounter_id}/note", headers=auth_headers(clinician))
    assert got.status_code == 200
    assert got.json()["plan"] == "Rest and fluids"


def test_structured_note_is_not_cross_facility_readable(test_client, db_session, make_user, auth_headers):
    facility_a, facility_b = _facility("SOAP A"), _facility("SOAP B")
    author = make_user(role="clinician", facility=facility_a)
    other = make_user(role="clinician", facility=facility_b)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, author, facility_a)
    ticket = _ticket(db_session, patient.id, facility_a, room.id, author.id)
    result = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete", headers=auth_headers(author),
        json={"assessment": "private", "signature_b64": _TEST_SIGNATURE_B64},
    )
    assert result.status_code == 200, result.text
    denied = test_client.get(
        f"/consultation/encounters/{result.json()['encounter_id']}/note", headers=auth_headers(other),
    )
    assert denied.status_code == 404
