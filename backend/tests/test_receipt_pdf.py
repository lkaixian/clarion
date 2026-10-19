"""PDF and emailed receipts. The PDF is rendered from the same dict as the JSON
receipt; the email always goes to the patient's own address on file."""
import pytest

from app import email_service, models
from conftest import _make_patient
from test_payments import World


@pytest.fixture
def w(test_client, make_user, auth_headers, db_session):
    return World(test_client, make_user, auth_headers, db_session)


def _pdf(w, user, pid):
    return w.c.get(f"/payments/receipts/{pid}/pdf", headers=w.h(user))


def test_pdf_has_the_receipt_and_the_same_access_rules(w, make_user):
    p = w.pay_online()
    r = _pdf(w, w.pat_user, p["payment_id"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and r.headers["cache-control"] == "no-store"
    assert f"receipt-{p['payment_id'][:8].upper()}.pdf" in r.headers["content-disposition"]
    assert _pdf(w, w.recep, p["payment_id"]).status_code == 200
    stranger = make_user(role="patient", patient_id=_make_patient(w.db, full_name="Some One Else").id, facility=None)
    outsider = make_user(role="receptionist", facility="Some Other Facility")
    assert _pdf(w, outsider, p["payment_id"]).status_code == 404
    assert _pdf(w, w.pat_user, "nope").status_code == 404
    assert _pdf(w, stranger, p["payment_id"]).status_code == 404


def test_email_needs_an_address_and_never_takes_a_recipient(w, monkeypatch):
    p = w.pay_online()
    sent = []
    monkeypatch.setattr(email_service, "send_receipt_email",
                        lambda to, name, no, summary, pdf: sent.append((to, no, pdf[:4])) or True)
    url = f"/payments/receipts/{p['payment_id']}/email"
    r = w.c.post(url, headers=w.h(w.pat_user))
    assert r.status_code == 400 and not sent  # no email on file

    w.patient.email = "pat@example.com"
    w.db.commit()
    r = w.c.post(url, headers=w.h(w.pat_user), json={"to": "attacker@evil.example"})
    assert r.status_code == 200 and r.json() == {"sent": True, "to_masked": "p***@example.com"}
    assert sent == [("pat@example.com", p["payment_id"][:8].upper(), b"%PDF")]
    # staff at the facility send to the same address on file
    assert w.c.post(url, headers=w.h(w.recep)).status_code == 200 and sent[-1][0] == "pat@example.com"
    audit = [a.action for a in w.db.query(models.AuditLog).filter_by(patient_id=w.patient.id).all()]
    assert "receipt_email_sent" in audit


def test_email_failure_is_reported_not_swallowed(w, monkeypatch):
    p = w.pay_online()
    w.patient.email = "pat@example.com"
    w.db.commit()
    monkeypatch.setattr(email_service, "send_receipt_email", lambda *a, **k: False)
    r = w.c.post(f"/payments/receipts/{p['payment_id']}/email", headers=w.h(w.pat_user))
    assert r.status_code == 503 and "PDF" in r.json()["detail"]


def test_email_is_denied_to_people_who_cannot_see_the_receipt(w, make_user, monkeypatch):
    p = w.pay_online()
    w.patient.email = "pat@example.com"
    w.db.commit()
    monkeypatch.setattr(email_service, "send_receipt_email", lambda *a, **k: True)
    outsider = make_user(role="receptionist", facility="Some Other Facility")
    assert w.c.post(f"/payments/receipts/{p['payment_id']}/email", headers=w.h(outsider)).status_code == 404


def test_mailtrap_payload_carries_the_pdf_attachment(monkeypatch):
    monkeypatch.setenv("MAILTRAP_API_TOKEN", "t")
    seen = {}

    class R:
        status_code = 200
        text = ""

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return R()
    monkeypatch.setattr(email_service.requests, "post", fake_post)
    assert email_service.send_receipt_email("a@b.c", "A", "AB12CD34", "RM 5.00 paid", b"%PDF-1.4 x")
    att = seen["attachments"][0]
    assert att["filename"] == "receipt-AB12CD34.pdf" and att["type"] == "application/pdf" and att["content"]
