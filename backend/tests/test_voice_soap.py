"""P4.3c — app/ai/voice_soap.py and /consultation/tickets/{id}/voice-to-soap.

Whisper itself is never exercised here (no model download in offline CI,
see healthcare/Implementation Roadmap.md's P2.11 offline-CI gate) --
`transcribe`/`_get_model` are monkeypatched so these tests stay fast and
network-free regardless of whether faster-whisper happens to be installed
in a given environment.
"""
from datetime import datetime

from app import models
from app.ai import voice_soap
from conftest import _facility, _make_patient


def _ticket(db, patient_id, facility, room_id, checked_in_by):
    ticket = models.QueueTicket(
        patient_id=patient_id, facility_name=facility, room_id=room_id,
        status="called", queue_number=1, queue_date=datetime.now().date().isoformat(),
        source="manual", checked_in_by=checked_in_by,
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


def test_transcribe_returns_none_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(voice_soap, "_get_model", lambda: None)
    assert voice_soap.transcribe(b"fake-audio-bytes") is None


def test_transcribe_refuses_over_duration_clip_without_calling_model(monkeypatch):
    """Security review 2026-09-13: the byte cap alone doesn't bound audio
    DURATION (a low-bitrate clip packs a long recording into few bytes) --
    an over-long clip must be refused before the expensive model.transcribe
    call, not merely after."""
    class _ExplodingModel:
        def transcribe(self, *a, **kw):
            raise AssertionError("must not reach the model for an over-duration clip")

    monkeypatch.setattr(voice_soap, "_get_model", lambda: _ExplodingModel())
    monkeypatch.setattr(voice_soap, "_duration_seconds", lambda path: voice_soap._MAX_AUDIO_SECONDS + 1)
    assert voice_soap.transcribe(b"fake-audio-bytes") is None


def test_transcribe_proceeds_when_duration_unknown(monkeypatch):
    """A container whose duration can't be read (e.g. an unusual webm
    trailer) must not block a legitimate short clip -- best-effort cap,
    not a hard gate."""
    class _FakeSegment:
        text = "hello"

    class _FakeModel:
        def transcribe(self, *a, **kw):
            return [_FakeSegment()], None

    monkeypatch.setattr(voice_soap, "_get_model", lambda: _FakeModel())
    monkeypatch.setattr(voice_soap, "_duration_seconds", lambda path: None)
    assert voice_soap.transcribe(b"fake-audio-bytes") == "hello"


def test_voice_to_soap_degrades_fully_when_speech_to_text_unavailable(monkeypatch):
    monkeypatch.setattr(voice_soap, "_get_model", lambda: None)
    result = voice_soap.voice_to_soap(b"fake-audio-bytes")
    assert result == {"transcript": None, "soap": {"subjective": "", "objective": "", "assessment": "", "plan": ""}}


def test_structure_as_soap_uses_local_llm_json(monkeypatch):
    monkeypatch.setattr(
        voice_soap, "generate_text",
        lambda *a, **kw: '{"subjective": "cough x2 days", "objective": "afebrile", "assessment": "", "plan": "rest"}',
    )
    soap = voice_soap.structure_as_soap("patient says cough for two days, afebrile, advised rest")
    assert soap == {"subjective": "cough x2 days", "objective": "afebrile", "assessment": "", "plan": "rest"}


def test_structure_as_soap_strips_markdown_json_fence(monkeypatch):
    monkeypatch.setattr(
        voice_soap, "generate_text",
        lambda *a, **kw: '```json\n{"subjective": "cough", "objective": "", "assessment": "", "plan": ""}\n```',
    )
    soap = voice_soap.structure_as_soap("patient reports cough")
    assert soap["subjective"] == "cough"


def test_structure_as_soap_falls_back_to_raw_transcript_on_unparseable_json(monkeypatch):
    monkeypatch.setattr(voice_soap, "generate_text", lambda *a, **kw: "not json")
    soap = voice_soap.structure_as_soap("raw dictation text")
    assert soap == {"subjective": "raw dictation text", "objective": "", "assessment": "", "plan": ""}


def test_structure_as_soap_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(voice_soap, "generate_text", lambda *a, **kw: None)
    soap = voice_soap.structure_as_soap("raw dictation text")
    assert soap["subjective"] == "raw dictation text"


def test_endpoint_transcribes_and_structures(db_session, test_client, make_user, auth_headers, monkeypatch):
    monkeypatch.setattr(voice_soap, "_get_model", lambda: None)  # no real model needed
    monkeypatch.setattr(voice_soap, "transcribe", lambda *a, **kw: "two days of cough, afebrile")
    monkeypatch.setattr(
        voice_soap, "generate_text",
        lambda *a, **kw: '{"subjective": "two days of cough", "objective": "afebrile", "assessment": "", "plan": ""}',
    )

    facility = _facility("VOICE")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, clinician, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, clinician.id)

    resp = test_client.post(
        f"/consultation/tickets/{ticket.id}/voice-to-soap",
        headers=auth_headers(clinician),
        files={"file": ("dictation.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transcript"] == "two days of cough, afebrile"
    assert body["soap"]["subjective"] == "two days of cough"


def test_endpoint_requires_a_claimed_room(db_session, test_client, make_user, auth_headers):
    facility = _facility("VOICE")
    owner = make_user(role="clinician", facility=facility)
    other = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    room = _room_and_claim(db_session, owner, facility)
    ticket = _ticket(db_session, patient.id, facility, room.id, owner.id)

    resp = test_client.post(
        f"/consultation/tickets/{ticket.id}/voice-to-soap",
        headers=auth_headers(other),
        files={"file": ("dictation.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 409
