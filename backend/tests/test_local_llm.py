"""P4.3 — app/ai/local_llm.py: the on-prem Ollama client, and that
summarize.py / nric_ocr.py actually fall back cleanly when it's unavailable.

No real Ollama server needed: httpx.post is monkeypatched for the happy
paths, and the "server unreachable" cases hit a real closed port so the
never-raises contract is checked against genuine connection errors too.
"""
import base64

import httpx
import pytest

from app.ai import local_llm, nric_ocr, summarize


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_disabled_makes_no_network_call(monkeypatch):
    monkeypatch.setenv("CLARION_DISABLE_LOCAL_AI", "1")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call out")))
    assert local_llm.generate_text("hello") is None
    assert local_llm.generate_vision_text("hello", b"fake-image-bytes") is None


def test_unreachable_server_returns_none_not_raise(monkeypatch):
    # Port 1 is a real closed port on any machine -- a genuine connection
    # error, not a mock, to prove the except-Exception net is wide enough.
    monkeypatch.setenv("CLARION_LOCAL_LLM_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CLARION_LOCAL_LLM_TIMEOUT", "2")
    assert local_llm.generate_text("hello") is None


def test_public_host_refused_without_network_call(monkeypatch):
    # A copy-paste deploy mistake pointing at a real public host must be
    # refused before any bytes go out -- not merely fail after connecting.
    # A literal IP (not a hostname) keeps this offline-CI-safe: no DNS query.
    monkeypatch.setenv("CLARION_LOCAL_LLM_URL", "http://8.8.8.8:11434")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call out")))
    assert local_llm.generate_text("hello") is None


def test_generate_text_happy_path(monkeypatch):
    monkeypatch.delenv("CLARION_DISABLE_LOCAL_AI", raising=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({"response": "  a brief  "}))
    assert local_llm.generate_text("hello") == "a brief"


def test_generate_text_blank_response_is_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({"response": "   "}))
    assert local_llm.generate_text("hello") is None


def test_generate_vision_sends_base64_image_no_data_uri_prefix(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"response": '{"ic_number": "1", "name": ""}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    image_bytes = b"not-really-an-image"
    local_llm.generate_vision_text("prompt", image_bytes)

    assert captured["json"]["images"] == [base64.b64encode(image_bytes).decode("ascii")]
    assert "/api/generate" in captured["url"]


def test_summarize_falls_back_when_local_llm_unavailable(monkeypatch):
    monkeypatch.setattr(summarize, "generate_text", lambda *a, **kw: None)
    patient = {
        "full_name": "Jane Tan", "date_of_birth": "1990-01-01",
        "conditions": [], "medications": [], "allergies": [], "encounters": [],
    }
    brief = summarize.generate_handover_brief(patient)
    assert "Jane Tan" in brief
    assert "No known allergies" in brief


def test_summarize_uses_local_llm_when_available(monkeypatch):
    monkeypatch.setattr(summarize, "generate_text", lambda *a, **kw: "a generated brief")
    patient = {"full_name": "Jane Tan", "date_of_birth": "1990-01-01"}
    assert summarize.generate_handover_brief(patient) == "a generated brief"


def test_nric_ocr_falls_back_to_tesseract_when_local_llm_unavailable(monkeypatch):
    monkeypatch.setattr(nric_ocr, "generate_vision_text", lambda *a, **kw: None)
    result = nric_ocr.extract_nric_fields(b"fake-image-bytes")
    assert result["method"] == "tesseract"


def test_nric_ocr_uses_local_llm_json_when_available(monkeypatch):
    monkeypatch.setattr(
        nric_ocr, "generate_vision_text",
        lambda *a, **kw: '{"ic_number": "990101-01-1234", "name": "Ali bin Ahmad"}',
    )
    result = nric_ocr.extract_nric_fields(b"fake-image-bytes")
    assert result == {
        "ic_number": "990101011234",
        "name": "Ali bin Ahmad",
        "method": "llm",
        "name_confidence": "high",
    }


def test_nric_ocr_malformed_local_llm_json_falls_back(monkeypatch):
    monkeypatch.setattr(nric_ocr, "generate_vision_text", lambda *a, **kw: "not json at all")
    result = nric_ocr.extract_nric_fields(b"fake-image-bytes")
    assert result["method"] == "tesseract"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
