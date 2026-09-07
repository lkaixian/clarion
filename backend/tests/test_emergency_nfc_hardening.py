"""Security Audit M7 — NFC emergency-card hardening.

M7a: `EmergencyToken.nfc_uid` stores `auth.hash_nfc_uid(raw)` (keyed
     HMAC-SHA256), never the raw MIFARE UID; every lookup hashes the
     presented UID first. `nfc_uid_last4` (cleartext tail) + the grant `id`
     are what the console shows / revokes by.
M7c: many scans of one card in a short window drop an
     `emergency_card_scan_anomaly` audit row (life-safety = can't block,
     so make it conspicuous).

The `emergency_tokens.nfc_uid` HMAC column is UNIQUE and the test DB is
session-scoped, so every test uses a distinct raw UID.
"""
import importlib.util
import pathlib
import uuid

from app import auth, models


def test_migration_hash_helpers_match_auth():
    """The M7 Alembic migration inlines its own copies of the UID hash /
    last4 / canonical helpers (so it doesn't import the app). Pin them to
    auth.* -- a future change to auth.canonical_nfc_uid that isn't mirrored
    would silently desync every card issued before the drift on a re-run."""
    mig_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "f3a9d21c5e88_m7_hash_nfc_uid_at_rest.py"
    )
    spec = importlib.util.spec_from_file_location("_m7_migration", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    for raw in ("04:1A:2B:3C", "041a2b3c4d5e6f", "AA-BB-CC-DD", "0a 1b 2c 3d"):
        assert mig._hash_nfc_uid(raw) == auth.hash_nfc_uid(raw), raw
        assert mig._last4(raw) == auth.nfc_uid_last4(raw), raw
        assert mig._canonical(raw) == auth.canonical_nfc_uid(raw), raw


def _uid() -> str:
    h = uuid.uuid4().hex.upper()
    return f"04:{h[0:2]}:{h[2:4]}:{h[4:6]}:{h[6:8]}"  # -> last4 == h[4:8]


def _expected_last4(raw: str) -> str:
    return raw.replace(":", "")[-4:].upper()


def _patient(db_session, **kw):
    p = models.Patient(
        full_name=kw.pop("full_name", "M7 Patient"),
        date_of_birth=kw.pop("date_of_birth", "1970-03-03"),
        **kw,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _present(db_session, patient, facility):
    ward = models.Ward(facility_name=facility, ward_name="W", total_beds=4)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    db_session.add(models.Admission(
        facility_name=facility, patient_id=patient.id, ward_id=ward.id, bed_number=1,
    ))
    db_session.commit()


def _register(test_client, auth_headers, staff, patient_id, uid):
    return test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient_id, "nfc_uid": uid},
    )


def test_register_stores_hmac_not_raw_uid(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="records_officer", facility="H1")
    patient = _patient(db_session)
    _present(db_session, patient, "H1")
    uid = _uid()

    resp = _register(test_client, auth_headers, staff, patient.id, uid)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "nfc_uid" not in body               # raw UID never round-trips
    assert body["nfc_uid_last4"] == _expected_last4(uid)
    assert body["id"]

    row = db_session.query(models.EmergencyToken).filter_by(id=body["id"]).one()
    assert row.nfc_uid == auth.hash_nfc_uid(uid)
    assert row.nfc_uid != uid
    assert len(row.nfc_uid) == 64
    assert row.nfc_uid_last4 == _expected_last4(uid)


def test_scan_accepts_raw_uid_and_never_logs_it(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H2")
    patient = _patient(db_session, full_name="M7 Scan", blood_type="O+")
    _present(db_session, patient, "H2")
    uid = _uid()
    assert _register(test_client, auth_headers, staff, patient.id, uid).status_code == 200

    scan = test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid})
    assert scan.status_code == 200, scan.text
    assert scan.json()["full_name"] == "M7 Scan"

    details = " || ".join(
        r.detail or "" for r in db_session.query(models.AuditLog)
        .filter(models.AuditLog.action.like("emergency_access%")).all()
    )
    assert uid not in details
    assert "nfc_hash=" in details  # the M7c count marker (HMAC prefix, not a key)


def test_list_and_revoke_use_grant_id(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="admin", facility="H3")
    patient = _patient(db_session, full_name="M7 List")
    _present(db_session, patient, "H3")
    uid = _uid()
    reg = _register(test_client, auth_headers, staff, patient.id, uid)
    grant_id = reg.json()["id"]

    listing = test_client.get(f"/emergency/nfc/{patient.id}", headers=auth_headers(staff))
    assert listing.status_code == 200
    card = listing.json()[0]
    assert card["id"] == grant_id
    assert card["nfc_uid_last4"] == _expected_last4(uid)
    assert "nfc_uid" not in card

    # revoke by the raw UID (old contract) must not work anymore
    assert test_client.post(
        f"/emergency/nfc/revoke/{uid}", headers=auth_headers(staff)
    ).status_code == 404
    # revoke by grant id works
    assert test_client.post(
        f"/emergency/nfc/revoke/{grant_id}", headers=auth_headers(staff)
    ).status_code == 200
    db_session.expire_all()
    assert db_session.query(models.EmergencyToken).filter_by(id=grant_id).one().revoked is True


def test_uid_lookup_is_separator_and_case_insensitive(test_client, db_session, make_user, auth_headers):
    """A card registered as `04:AB:CD:EF` must still resolve when a
    different reader / manual entry produces `04abcdef` or `04-ab-cd-ef`
    (auth.canonical_nfc_uid normalises before hashing)."""
    staff = make_user(role="clinician", facility="H4b")
    patient = _patient(db_session, full_name="M7 Canon")
    _present(db_session, patient, "H4b")
    assert _register(test_client, auth_headers, staff, patient.id, "04:AB:CD:EF:12:34").status_code == 200

    for variant in ("04abcdef1234", "04-ab-cd-ef-12-34", "04 AB CD EF 12 34"):
        r = test_client.post("/emergency/nfc/scan", json={"nfc_uid": variant})
        assert r.status_code == 200, f"{variant} -> {r.status_code}"
        assert r.json()["full_name"] == "M7 Canon"


def test_reception_checkin_by_nfc_still_resolves(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="records_officer", facility="H4")
    receptionist = make_user(role="receptionist", facility="H4")
    patient = _patient(db_session, full_name="M7 Checkin")
    _present(db_session, patient, "H4")
    uid = _uid()
    assert _register(test_client, auth_headers, staff, patient.id, uid).status_code == 200

    resp = test_client.post(
        "/reception/checkin",
        headers=auth_headers(receptionist),
        json={"nfc_uid": uid},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["patient_full_name"] == "M7 Checkin"


def test_repeated_scans_of_one_card_raise_an_anomaly_row(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H5")
    patient = _patient(db_session, full_name="M7 Anomaly")
    _present(db_session, patient, "H5")
    uid = _uid()
    assert _register(test_client, auth_headers, staff, patient.id, uid).status_code == 200

    def _anomaly_count():
        return (
            db_session.query(models.AuditLog)
            .filter_by(action="emergency_card_scan_anomaly", patient_id=patient.id)
            .count()
        )

    for _ in range(7):  # below threshold (8)
        assert test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).status_code == 200
    assert _anomaly_count() == 0, "must not fire before the 8th scan"

    assert test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).status_code == 200  # 8th
    assert _anomaly_count() == 1, "fires on exactly the 8th scan"

    assert test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).status_code == 200  # 9th
    assert _anomaly_count() == 1  # debounced -- still one

    anomalies = (
        db_session.query(models.AuditLog)
        .filter_by(action="emergency_card_scan_anomaly", patient_id=patient.id)
        .all()
    )
    assert anomalies[0].actor == "system"
    assert "count=" in (anomalies[0].detail or "")
    assert uid not in (anomalies[0].detail or "")


def test_failed_scan_flood_flags_anomaly_without_patient_id(test_client, db_session, make_user, auth_headers):
    """A flood of failed scans of a revoked card also trips M7c -- and the
    anomaly row carries patient_id=None (same "don't correlate a probe to a
    patient" reasoning as the failed-scan row itself)."""
    staff = make_user(role="clinician", facility="H7")
    patient = _patient(db_session, full_name="M7 FailFlood")
    _present(db_session, patient, "H7")
    uid = _uid()
    reg = _register(test_client, auth_headers, staff, patient.id, uid)
    # revoke it so every subsequent scan is a failure
    test_client.post(f"/emergency/nfc/revoke/{reg.json()['id']}", headers=auth_headers(staff))

    for _ in range(9):
        assert test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid}).status_code == 404

    anomalies = db_session.query(models.AuditLog).filter_by(action="emergency_card_scan_anomaly").all()
    mine = [a for a in anomalies if "count=" in (a.detail or "") and a.patient_id is None]
    assert mine, "expected a patient_id=None anomaly row from the failed-scan flood"


def test_different_cards_do_not_cross_trigger_anomaly(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H6")
    patient = _patient(db_session, full_name="M7 TwoCards")
    _present(db_session, patient, "H6")
    uid_a, uid_b = _uid(), _uid()
    assert _register(test_client, auth_headers, staff, patient.id, uid_a).status_code == 200
    assert _register(test_client, auth_headers, staff, patient.id, uid_b).status_code == 200

    for uid in (uid_a, uid_b):
        for _ in range(5):  # 5 each -- neither alone crosses 8
            test_client.post("/emergency/nfc/scan", json={"nfc_uid": uid})

    assert (
        db_session.query(models.AuditLog)
        .filter_by(action="emergency_card_scan_anomaly", patient_id=patient.id)
        .count() == 0
    )
