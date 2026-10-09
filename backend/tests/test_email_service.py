"""Mailtrap sender: confirmed-2xx -> True, everything else -> False, never raises."""
import pytest
import requests

from app import email_service


class _Resp:
    def __init__(self, status=200, text="ok"):
        self.status_code, self.text = status, text


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("MAILTRAP_API_TOKEN", "MAILTRAP_INBOX_ID", "MAILTRAP_SENDER_EMAIL", "MAILTRAP_SENDER_NAME"):
        monkeypatch.delenv(k, raising=False)


def test_not_configured_returns_false_without_calling_out(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the network when unconfigured")
    monkeypatch.setattr(requests, "post", boom)
    assert email_service.send_password_reset_otp_email("a@b.c", "123456", "Ann") is False


def test_live_mode_request_shape(monkeypatch):
    monkeypatch.setenv("MAILTRAP_API_TOKEN", "tok")
    monkeypatch.setenv("MAILTRAP_SENDER_EMAIL", "noreply@clarion.larmkx.com")
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, json=json)
        return _Resp(200)
    monkeypatch.setattr(requests, "post", fake_post)
    assert email_service.send_self_registration_otp_email("p@x.my", "654321", "Siti") is True
    assert seen["url"] == "https://send.api.mailtrap.io/api/send"
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["json"]["to"] == [{"email": "p@x.my"}]
    assert seen["json"]["from"]["email"] == "noreply@clarion.larmkx.com"
    assert "654321" in seen["json"]["text"] and seen["json"]["category"] == "self-registration"


def test_sandbox_mode_uses_inbox_url(monkeypatch):
    monkeypatch.setenv("MAILTRAP_API_TOKEN", "tok")
    monkeypatch.setenv("MAILTRAP_INBOX_ID", "12345")
    seen = {}
    monkeypatch.setattr(requests, "post", lambda url, **k: seen.setdefault("url", url) and _Resp(200))
    assert email_service.send_password_reset_otp_email("a@b.c", "111111", "Ann") is True
    assert seen["url"] == "https://sandbox.api.mailtrap.io/api/send/12345"


def test_non_2xx_and_network_errors_return_false(monkeypatch):
    monkeypatch.setenv("MAILTRAP_API_TOKEN", "tok")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(401, "Unauthorized"))
    assert email_service.send_password_reset_otp_email("a@b.c", "111111", "Ann") is False
    def raises(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "post", raises)
    assert email_service.send_password_reset_otp_email("a@b.c", "111111", "Ann") is False


def test_patient_name_is_html_escaped(monkeypatch):
    monkeypatch.setenv("MAILTRAP_API_TOKEN", "tok")
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json=json)
        return _Resp(200)
    monkeypatch.setattr(requests, "post", fake_post)
    email_service.send_password_reset_otp_email("a@b.c", "111111", "<script>x</script>")
    assert "<script>" not in seen["json"]["html"]
    assert "&lt;script&gt;" in seen["json"]["html"]
