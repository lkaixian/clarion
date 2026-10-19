"""QR 3-year default, NFC validity by chip type, card status/outdated flag and card history."""
from datetime import datetime, timedelta, timezone

from app import models
from conftest import _facility, _make_patient

import secrets


def _uid():
    return "04" + secrets.token_hex(6).upper()


def _grant_days(resp):
    until = datetime.fromisoformat(resp["grant_valid_until"])
    return (until - datetime.now(timezone.utc).replace(tzinfo=None)).days


def _staff_and_patient(db, make_user):
    fac = _facility("CardPolicy")
    staff = make_user(role="admin", facility=fac)
    p = _make_patient(db, full_name="Card Holder")
    db.add(models.Encounter(patient_id=p.id, facility_name=fac, encounter_type="outpatient"))
    db.commit()
    return staff, p, make_user(role="patient", patient_id=p.id, facility=None)


def test_qr_defaults_to_three_years(test_client, make_user, auth_headers, db_session):
    _, p, pat = _staff_and_patient(db_session, make_user)
    r = test_client.post("/emergency/issue", json={"patient_id": p.id}, headers=auth_headers(pat))
    assert r.status_code == 200, r.text
    assert 1090 <= _grant_days(r.json()) <= 1096


def test_nfc_validity_depends_on_chip(test_client, make_user, auth_headers, db_session):
    staff, p, _ = _staff_and_patient(db_session, make_user)
    uid = _uid()
    h = auth_headers(staff)
    old = test_client.post("/emergency/nfc/register", headers=h,
                           json={"patient_id": p.id, "nfc_uid": uid, "tag_type": "ntag21x"})
    assert old.status_code == 200, old.text
    assert 360 <= _grant_days(old.json()) <= 366           # 1 year default
    too_long = test_client.post("/emergency/nfc/register", headers=h,
                                json={"patient_id": p.id, "nfc_uid": uid, "tag_type": "ntag21x",
                                      "valid_minutes": 3 * 525600})
    assert too_long.status_code == 422                       # 2 years is the ceiling for old chips
    new = test_client.post("/emergency/nfc/register", headers=h,
                           json={"patient_id": p.id, "nfc_uid": _uid(), "tag_type": "ntag424"})
    assert new.status_code == 200
    assert 2550 <= _grant_days(new.json()) <= 2558           # 7 years


def test_card_list_flags_outdated_and_status_and_history(test_client, make_user, auth_headers, db_session):
    staff, p, pat = _staff_and_patient(db_session, make_user)
    uid = _uid()
    hs = auth_headers(staff)
    test_client.post("/emergency/nfc/register", headers=hs,
                     json={"patient_id": p.id, "nfc_uid": uid, "tag_type": "ntag21x"})
    test_client.post("/emergency/nfc/register", headers=hs,
                     json={"patient_id": p.id, "nfc_uid": _uid(), "tag_type": "ntag424"})
    cards = test_client.get(f"/emergency/nfc/{p.id}", headers=auth_headers(pat)).json()
    by_type = {c["tag_type"]: c for c in cards}
    assert by_type["ntag21x"]["outdated"] is True and by_type["ntag424"]["outdated"] is False
    assert all(c["status"] == "active" and c["valid_days_left"] > 300 for c in cards)

    old = by_type["ntag21x"]
    scan = test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid, "responder_org": "City Clinic"})
    assert scan.status_code == 200
    test_client.post("/emergency/nfc/register", headers=hs,   # renew
                     json={"patient_id": p.id, "nfc_uid": uid, "tag_type": "ntag21x"})
    hist = test_client.get(f"/emergency/nfc/{p.id}/{old['id']}/history", headers=auth_headers(pat))
    assert hist.status_code == 200
    events = [e["event"] for e in hist.json()]
    assert set(events) >= {"registered", "scanned", "renewed"}
    scanned = next(e for e in hist.json() if e["event"] == "scanned")
    assert scanned["by_org"] == "City Clinic"
    assert "responder_name" not in scanned

    # another patient's card id is a 404, not a leak
    other = _make_patient(db_session, full_name="Someone Else")
    test_client.post("/emergency/nfc/register", headers=hs,
                     json={"patient_id": other.id, "nfc_uid": _uid(), "tag_type": "ntag424"})
    assert test_client.get(f"/emergency/nfc/{p.id}/{old['id']}x/history", headers=auth_headers(pat)).status_code == 404


def test_expired_and_revoked_status(test_client, make_user, auth_headers, db_session):
    staff, p, pat = _staff_and_patient(db_session, make_user)
    uid = _uid()
    test_client.post("/emergency/nfc/register", headers=auth_headers(staff),
                     json={"patient_id": p.id, "nfc_uid": uid, "tag_type": "ntag424"})
    g = db_session.query(models.EmergencyToken).filter_by(patient_id=p.id).one()
    g.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db_session.commit()
    c = test_client.get(f"/emergency/nfc/{p.id}", headers=auth_headers(pat)).json()[0]
    assert c["status"] == "expired" and c["valid_days_left"] is None
    g.revoked = True
    db_session.commit()
    c = test_client.get(f"/emergency/nfc/{p.id}", headers=auth_headers(pat)).json()[0]
    assert c["status"] == "revoked"
