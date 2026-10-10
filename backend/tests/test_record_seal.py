"""Tamper seal (app/seal.py): sign-off seals the row; any later edit shows up
as "altered" on the patient record."""
from app import models, seal
from conftest import _TEST_SIGNATURE_B64, _facility, _make_patient
from test_consultation_notes import _room_and_claim, _ticket


def _sealed_encounter(test_client, db_session, make_user, auth_headers):
    facility = _facility("Seal")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)
    done = test_client.post(
        f"/consultation/tickets/{ticket.id}/complete", headers=auth_headers(clinician),
        json={"assessment": "viral URTI", "temperature_c": 37.2, "signature_b64": _TEST_SIGNATURE_B64},
    ).json()
    return clinician, patient, done["encounter_id"]


def _status(test_client, headers, patient_id, encounter_id):
    rec = test_client.get(f"/patients/{patient_id}", headers=headers).json()
    return next(e for e in rec["encounters"] if e["id"] == encounter_id)["seal_status"]


def test_encounter_is_sealed_and_edit_flips_it_to_altered(test_client, db_session, make_user, auth_headers):
    clinician, patient, enc_id = _sealed_encounter(test_client, db_session, make_user, auth_headers)
    h = auth_headers(clinician)
    assert _status(test_client, h, patient.id, enc_id) == "valid"

    # a direct DB edit (what a malicious admin / SQL console could do)
    note = db_session.query(models.ConsultationNote).filter_by(encounter_id=enc_id).one()
    note.assessment = "something else entirely"
    db_session.commit()
    assert _status(test_client, h, patient.id, enc_id) == "altered"


def test_swapping_the_signature_hash_is_detected(test_client, db_session, make_user, auth_headers):
    clinician, patient, enc_id = _sealed_encounter(test_client, db_session, make_user, auth_headers)
    enc = db_session.get(models.Encounter, enc_id)
    enc.signature_sha256 = "0" * 64
    db_session.commit()
    assert _status(test_client, auth_headers(clinician), patient.id, enc_id) == "altered"


def test_unsealed_legacy_row_is_not_reported_valid(db_session):
    enc = models.Encounter(patient_id="p", facility_name="f", encounter_type="visit")
    enc.id = "e1"
    assert seal.status("encounter", enc) == "unsealed"
