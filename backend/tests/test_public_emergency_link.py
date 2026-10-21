"""The QR is now a link a plain phone camera can open, and a big-enough NFC tag carries a link first.
The link on a tag holds a random, rotating reference -- never the tag's UID. These tests pin the
contract the web page and the app rely on."""
import uuid

import pytest
import qrcode

from app import models
from app.routers import emergency


def _patient(db_session):
    p = models.Patient(full_name="Link Patient", date_of_birth="1970-01-01", blood_type="B+")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    db_session.add(models.AllergyIntolerance(patient_id=p.id, substance="Penicillin", severity="severe",
                                             critical_for_emergency=True))
    db_session.commit()
    return p


def _present(db_session, patient):
    ward = models.Ward(facility_name="Link Hospital", ward_name=f"W{uuid.uuid4().hex[:4]}", total_beds=2)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(facility_name="Link Hospital", patient_id=patient.id, ward_id=ward.id, bed_number=1))
    db_session.commit()


def _capture_qr(monkeypatch):
    seen = []
    real = qrcode.make
    monkeypatch.setattr(emergency.qrcode, "make", lambda data, *a, **k: seen.append(data) or real(data, *a, **k))
    return seen


def _register(test_client, auth_headers, clinician, patient, uid=None, cap=504):
    uid = uid or f"04:{uuid.uuid4().hex[:12].upper()}"
    resp = test_client.post("/emergency/nfc/register", headers=auth_headers(clinician),
                            json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": cap})
    assert resp.status_code == 200, resp.text
    return uid, resp.json()


def test_the_qr_encodes_a_link_to_the_public_page(monkeypatch):
    seen = _capture_qr(monkeypatch)
    monkeypatch.delenv("CLARION_PUBLIC_URL", raising=False)
    emergency._render_qr_base64("abc123")
    assert seen == ["https://clarion.larmkx.com/e/abc123"]


def test_the_public_base_url_is_configurable(monkeypatch):
    monkeypatch.setenv("CLARION_PUBLIC_URL", "https://clinic.example.org/")
    assert emergency._public_base() == "https://clinic.example.org"
    monkeypatch.setenv("CLARION_PUBLIC_URL", "http://localhost:8080")
    assert emergency._public_base() == "http://localhost:8080"
    monkeypatch.setenv("CLARION_PUBLIC_URL", "")
    assert emergency._public_base() == "https://clarion.larmkx.com"


@pytest.mark.parametrize("bad", [
    "clarion.uni.edu.my",              # no scheme
    "javascript:alert(1)",
    "http://clinic.example.org",       # cleartext off localhost
    "https://",                        # no host
    "https://user:pw@clinic.example.org",
    "https://clinic.example.org/app",  # a path
    "https://clinic.example.org?x=1",
    "https://clinic.example.org#frag",
])
def test_a_bad_public_base_url_is_refused_not_silently_replaced(monkeypatch, bad):
    monkeypatch.setenv("CLARION_PUBLIC_URL", bad)
    with pytest.raises(RuntimeError):
        emergency._public_base()


def test_an_issued_card_still_scans_by_its_reference_for_the_public_page(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    _present(db_session, patient)
    clinician = make_user(role="clinician", facility="Link Hospital")
    issued = test_client.post("/emergency/issue", headers=auth_headers(clinician), json={"patient_id": patient.id})
    assert issued.status_code == 200, issued.text
    page = test_client.post("/emergency/scan", json={"card_reference": issued.json()["card_reference"]})
    assert page.status_code == 200
    body = page.json()
    assert body["tier"] == "public" and body["full_name"] is None and "Penicillin" in str(body["allergies"])
    assert "family_notification" not in body and "emergency_contact" not in body


def test_a_big_tag_gets_a_random_link_and_a_smaller_sealed_budget(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    _present(db_session, patient)
    clinician = make_user(role="clinician", facility="Link Hospital")

    uid, big = _register(test_client, auth_headers, clinician, patient, cap=504)  # NTAG215
    assert big["url_on_tag"] is True
    assert big["public_url"].startswith("https://clarion.larmkx.com/e/")
    canonical = "".join(ch for ch in uid if ch not in ": -").upper()
    assert canonical not in big["public_url"].upper() and uid not in big["public_url"]  # the UID is never in the link

    _, mid = _register(test_client, auth_headers, clinician, patient, cap=256)  # too small for the extra record
    assert mid["url_on_tag"] is False


def test_the_link_on_a_tag_opens_the_public_page_and_rotates_when_the_tag_is_rewritten(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    _present(db_session, patient)
    clinician = make_user(role="clinician", facility="Link Hospital")
    uid, first = _register(test_client, auth_headers, clinician, patient)
    first_ref = first["public_url"].rsplit("/", 1)[1]

    page = test_client.post("/emergency/scan", json={"card_reference": first_ref})
    assert page.status_code == 200 and page.json()["tier"] == "public"
    assert "Penicillin" in str(page.json()["allergies"])

    _, second = _register(test_client, auth_headers, clinician, patient, uid=uid)  # same tag registered again
    second_ref = second["public_url"].rsplit("/", 1)[1]
    assert second_ref != first_ref
    assert test_client.post("/emergency/scan", json={"card_reference": first_ref}).status_code == 404
    assert test_client.post("/emergency/scan", json={"card_reference": second_ref}).status_code == 200


def test_a_revoked_tag_link_stops_working(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    _present(db_session, patient)
    clinician = make_user(role="clinician", facility="Link Hospital")
    _, reg = _register(test_client, auth_headers, clinician, patient)
    ref = reg["public_url"].rsplit("/", 1)[1]
    assert test_client.post("/emergency/scan", json={"card_reference": ref}).status_code == 200
    revoked = test_client.post(f"/emergency/nfc/revoke/{reg['id']}", headers=auth_headers(clinician))
    assert revoked.status_code in (200, 204), revoked.text
    assert test_client.post("/emergency/scan", json={"card_reference": ref}).status_code == 404


def test_a_public_nfc_lookup_leaves_no_raw_uid_in_the_audit_trail(test_client, db_session, make_user, auth_headers):
    patient = _patient(db_session)
    _present(db_session, patient)
    clinician = make_user(role="clinician", facility="Link Hospital")
    uid, _ = _register(test_client, auth_headers, clinician, patient)
    canonical = "".join(ch for ch in uid if ch not in ": -").upper()
    body = test_client.post("/emergency/nfc/scan", json={"nfc_uid": canonical}).json()
    assert body["tier"] == "public" and "family_notification" not in body and "emergency_contact" not in body
    rows = db_session.query(models.AuditLog).filter_by(patient_id=patient.id).all()
    assert all(canonical not in (r.detail or "") for r in rows)
