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


def _signed_off_request(db, patient_id, facility, module="laboratory"):
    """Build a same-facility, already signed-off ServiceRequest directly via
    the ORM -- same shortcut test_ancillary.py/test_dental.py already use for
    fixture rows the ancillary engine's own API isn't what's under test."""
    item = models.ServiceCatalogItem(module=module, name="CBC", unit_price_cents=4500)
    db.add(item)
    db.flush()
    req = models.ServiceRequest(
        patient_id=patient_id, module=module, catalog_item_id=item.id,
        source="frontdesk", priority="routine", unit_price_cents=4500,
        ordering_facility_name=facility, status="signed_off",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def test_follow_up_and_referral_persisted(test_client, db_session, make_user, auth_headers):
    """P3.4 loose end: follow_up_at + referral_service_request_id round-trip
    through the note -- previously only exercised by the schema, not the UI
    or a test."""
    facility = _facility("SOAP")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)
    referral = _signed_off_request(db_session, patient.id, facility)

    response = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={
            "assessment": "Needs a repeat CBC",
            "follow_up_at": "2026-10-01T09:00:00Z",
            "referral_service_request_id": referral.id,
            "signature_b64": _TEST_SIGNATURE_B64,
        },
    )
    assert response.status_code == 200, response.text
    note = db_session.query(models.ConsultationNote).filter_by(
        encounter_id=response.json()["encounter_id"]
    ).one()
    assert note.referral_service_request_id == referral.id
    assert note.follow_up_at is not None


def test_referral_rejects_cross_facility_request(test_client, db_session, make_user, auth_headers):
    """A referral must point at a ServiceRequest ordered by the SAME
    facility as the signing clinician -- otherwise a signed clinical record
    could become a cross-site identifier oracle (same class of bug the
    ancillary/dental annotation-scoping fixes closed elsewhere)."""
    facility_a, facility_b = _facility("SOAP A"), _facility("SOAP B")
    clinician = make_user(role="clinician", facility=facility_a)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility_a)
    ticket = _ticket(db_session, patient.id, facility_a, room.id, clinician.id)
    foreign_referral = _signed_off_request(db_session, patient.id, facility_b)

    response = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete",
        headers=auth_headers(clinician),
        json={
            "assessment": "x",
            "referral_service_request_id": foreign_referral.id,
            "signature_b64": _TEST_SIGNATURE_B64,
        },
    )
    assert response.status_code == 404


def test_annotation_correction_on_consultation_note(test_client, db_session, make_user, auth_headers):
    """The model's own docstring promises corrections go through
    ClinicalRecordAnnotation with target_type='consultation_note' -- this
    was never actually wired into patients.py's _ANNOTATION_MODEL /
    schemas.ANNOTATION_TARGET_TYPES until now."""
    facility = _facility("SOAP")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)
    completed = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete", headers=auth_headers(clinician),
        json={"assessment": "typo'd this", "signature_b64": _TEST_SIGNATURE_B64},
    ).json()
    note = db_session.query(models.ConsultationNote).filter_by(
        encounter_id=completed["encounter_id"]
    ).one()

    resp = test_client.post(
        f"/patients/{patient.id}/annotations",
        json={"target_type": "consultation_note", "target_id": note.id, "kind": "correction", "note": "meant viral, not bacterial"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text

    listed = test_client.get(f"/patients/{patient.id}/annotations", headers=auth_headers(clinician))
    assert listed.status_code == 200
    assert any(a["target_type"] == "consultation_note" and a["target_id"] == note.id for a in listed.json())


def test_annotation_on_consultation_note_rejects_cross_facility(test_client, db_session, make_user, auth_headers):
    """ConsultationNote is the one _ANNOTATION_MODEL target with NO cross-
    facility read at all (unlike condition/medication/encounter, which are
    already universally cross-facility readable) -- a facility with no read
    access to the note must not be able to attach a signed correction to it
    either. Caught on self-review: the _ANNOTATION_MODEL wiring above had
    no facility check at all, unlike the note's own dedicated read
    endpoint."""
    facility_a, facility_b = _facility("SOAP A"), _facility("SOAP B")
    author = make_user(role="clinician", facility=facility_a)
    other = make_user(role="clinician", facility=facility_b)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, author, facility_a)
    ticket = _ticket(db_session, patient.id, facility_a, room.id, author.id)
    completed = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete", headers=auth_headers(author),
        json={"assessment": "private", "signature_b64": _TEST_SIGNATURE_B64},
    ).json()
    note = db_session.query(models.ConsultationNote).filter_by(
        encounter_id=completed["encounter_id"]
    ).one()

    resp = test_client.post(
        f"/patients/{patient.id}/annotations",
        json={"target_type": "consultation_note", "target_id": note.id, "kind": "correction", "note": "nope"},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404
