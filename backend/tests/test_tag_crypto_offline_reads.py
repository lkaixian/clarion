"""Encrypted NFC tag payload + offline-read audit upload (tag_crypto.py,
GET /emergency/tag-keys, POST /emergency/offline-reads)."""
import secrets

import pytest

from app import models, tag_crypto

UID = "04A1B2C3D4E5F6"


def _patient(db_session):
    p = models.Patient(full_name="Tag Patient", date_of_birth="1990-01-01", blood_type="O+")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _chain(n, uid=UID, key_id=1, outcome="decrypted", start_seq=0, prev=tag_crypto.GENESIS_HASH):
    out = []
    for seq in range(start_seq, start_seq + n):
        read_at = f"2026-10-10T08:0{seq % 10}:00Z"
        h = tag_crypto.read_entry_hash(prev, seq, read_at, uid, key_id, outcome)
        out.append({"seq": seq, "read_at": read_at, "nfc_uid": uid, "key_id": key_id,
                    "outcome": outcome, "prev_hash": prev, "entry_hash": h})
        prev = h
    return out


# ---- crypto ----

def test_seal_open_roundtrip_and_uid_binding():
    blob = tag_crypto.seal("BT:O+|AL:Penicillin(severe)", UID)
    assert blob.startswith("C1.")
    assert tag_crypto.open_blob(blob, UID) == "BT:O+|AL:Penicillin(severe)"
    with pytest.raises(ValueError):
        tag_crypto.open_blob(blob, "04FFFFFFFFFFFF")  # blob copied to another tag


def test_tampered_blob_is_rejected():
    blob = tag_crypto.seal("BT:O+", UID)
    head, last = blob[:-2], blob[-2:]
    with pytest.raises(ValueError):
        tag_crypto.open_blob(head + ("AA" if last != "AA" else "BB"), UID)


def test_plaintext_budget_fits_the_tag():
    for cap in (128, 200, 504):
        budget = tag_crypto.plaintext_budget(cap)
        blob = tag_crypto.seal("x" * budget, UID)
        assert len(blob) <= cap


# ---- register returns a sealed blob that opens ----

def test_register_returns_blob_for_the_tags_uid(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    patient = _patient(db_session)
    uid = secrets.token_hex(7).upper()  # the test DB is shared; never reuse a registered UID
    resp = test_client.post(
        "/emergency/nfc/register", headers=auth_headers(clin),
        json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": 256},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tag_blob"] and body["tag_blob_key_id"] == tag_crypto.current_key_id()
    assert "BT:O+" in tag_crypto.open_blob(body["tag_blob"], uid)


# ---- keys endpoint ----

def test_tag_keys_staff_only(test_client, make_user, auth_headers):
    patient_user = make_user(role="patient")
    assert test_client.get("/emergency/tag-keys", headers=auth_headers(patient_user)).status_code == 403
    assert test_client.get("/emergency/tag-keys").status_code == 401

    # Only roles with an emergency/clinical need get the key.
    for role in ("pharmacist", "receptionist"):
        other = make_user(role=role, facility="Main Hospital")
        assert test_client.get("/emergency/tag-keys", headers=auth_headers(other)).status_code == 403

    staff = make_user(role="emergency_responder", facility="Main Hospital")
    resp = test_client.get("/emergency/tag-keys", headers=auth_headers(staff))
    assert resp.status_code == 200
    assert str(resp.json()["current_key_id"]) in resp.json()["keys"]
    assert resp.headers["cache-control"] == "no-store"


# ---- offline reads ----

def test_offline_reads_stored_audited_and_idempotent(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    patient = _patient(db_session)
    h = auth_headers(clin)
    uid = secrets.token_hex(7).upper()
    assert test_client.post(
        "/emergency/nfc/register", headers=h, json={"patient_id": patient.id, "nfc_uid": uid}
    ).status_code == 200

    body = {"device_id": "device-abc12345", "entries": _chain(3, uid=uid)}
    r = test_client.post("/emergency/offline-reads", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"stored": 3, "duplicates": 0, "conflicts": 0, "chain_broken": 0}

    rows = db_session.query(models.OfflineTagRead).filter_by(user_id=clin.id).all()
    assert len(rows) == 3 and all(x.chain_ok and x.patient_id == patient.id for x in rows)
    assert all(uid not in x.nfc_uid_hash for x in rows)

    audit = db_session.query(models.AuditLog).filter_by(
        action="emergency_access_nfc_offline", patient_id=patient.id).count()
    assert audit == 3

    again = test_client.post("/emergency/offline-reads", headers=h, json=body)
    assert again.json() == {"stored": 0, "duplicates": 3, "conflicts": 0, "chain_broken": 0}


def test_offline_reads_flag_a_broken_chain(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    entries = _chain(3)
    # Device owner deletes the middle entry before upload: seq 2 no longer
    # links to anything stored.
    del entries[1]
    r = test_client.post("/emergency/offline-reads", headers=h,
                         json={"device_id": "device-abc12345", "entries": entries})
    assert r.status_code == 200
    assert r.json()["stored"] == 2 and r.json()["chain_broken"] == 1

    bad = db_session.query(models.OfflineTagRead).filter_by(user_id=clin.id, chain_ok=False).all()
    assert [x.seq for x in bad] == [2]


def test_offline_reads_reject_a_forged_hash(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    entries = _chain(1)
    entries[0]["entry_hash"] = "a" * 64
    r = test_client.post("/emergency/offline-reads", headers=auth_headers(clin),
                         json={"device_id": "device-abc12345", "entries": entries})
    assert r.status_code == 200 and r.json()["chain_broken"] == 1


def test_offline_reads_patient_forbidden(test_client, make_user, auth_headers):
    pu = make_user(role="patient")
    r = test_client.post("/emergency/offline-reads", headers=auth_headers(pu),
                         json={"device_id": "device-abc12345", "entries": _chain(1)})
    assert r.status_code == 403


def test_same_seq_different_hash_is_a_conflict_not_a_silent_drop(test_client, make_user, auth_headers, db_session):
    """A device that lost its log state restarts at seq 0 under the same
    device id: those reads must be reported, not counted as duplicates."""
    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    first = _chain(1)
    assert test_client.post("/emergency/offline-reads", headers=h,
                            json={"device_id": "device-abc12345", "entries": first}).json()["stored"] == 1
    other = _chain(1, uid="04ABCDEF123456")  # seq 0 again, different content
    r = test_client.post("/emergency/offline-reads", headers=h,
                         json={"device_id": "device-abc12345", "entries": other})
    assert r.json()["conflicts"] == 1 and r.json()["stored"] == 0
    assert db_session.query(models.AuditLog).filter_by(
        action="offline_read_seq_conflict", actor=clin.id).count() == 1


def test_offline_reads_reject_oversized_ints_and_batches(test_client, make_user, auth_headers):
    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    big = _chain(1)
    big[0]["seq"] = 2**31
    assert test_client.post("/emergency/offline-reads", headers=h,
                            json={"device_id": "device-abc12345", "entries": big}).status_code == 422
    many = _chain(26)
    assert test_client.post("/emergency/offline-reads", headers=h,
                            json={"device_id": "device-abc12345", "entries": many}).status_code == 422


def test_old_ntag_types_still_register_with_a_warning(test_client, make_user, auth_headers, db_session):
    """NTAG213/215 (and unknown) keep working end to end; only the response
    flags the missing read counter. NTAG 424 DNA gets no warning."""
    clin = make_user(role="clinician", facility="Main Hospital")
    patient = _patient(db_session)
    h = auth_headers(clin)
    for tag_type, size, warns in (("ntag21x", 137, True), ("unknown", None, True), ("ntag424", 250, False)):
        uid = secrets.token_hex(7).upper()
        body = test_client.post(
            "/emergency/nfc/register", headers=h,
            json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": size, "tag_type": tag_type},
        ).json()
        assert body["tag_blob"], tag_type  # always something writable
        assert "tag_text" not in body
        assert (body["tag_security"]["warning"] is not None) is warns
        assert body["tag_security"]["read_counter"] is (not warns)
        assert len(body["tag_blob"]) <= (size or 128)


def test_sealed_blob_carries_the_grant_expiry(test_client, make_user, auth_headers, db_session):
    clin = make_user(role="clinician", facility="Main Hospital")
    patient = _patient(db_session)
    uid = secrets.token_hex(7).upper()
    body = test_client.post(
        "/emergency/nfc/register", headers=auth_headers(clin),
        json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": 256},
    ).json()
    assert tag_crypto.open_blob(body["tag_blob"], uid).startswith("X:20")


# ---- offline revocation list + key lifetime ----

def _register(test_client, headers, patient, uid):
    r = test_client.post("/emergency/nfc/register", headers=headers,
                         json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": 256})
    assert r.status_code == 200, r.text
    return r.json()


def test_revoked_card_is_listed_with_the_key_a_device_needs_to_match_it(
        test_client, make_user, auth_headers, db_session):
    import base64
    import hashlib
    import hmac as hmac_mod

    from app import auth

    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    patient = _patient(db_session)
    uid = secrets.token_hex(7).upper()
    grant = _register(test_client, h, patient, uid)

    keys = test_client.get("/emergency/tag-keys", headers=h).json()
    rid = tag_crypto.revocation_id(auth.canonical_nfc_uid(uid))
    assert rid not in keys["revoked_card_ids"]  # still valid

    assert test_client.post(f"/emergency/nfc/revoke/{grant['id']}", headers=h).status_code == 200
    keys = test_client.get("/emergency/tag-keys", headers=h).json()
    assert rid in keys["revoked_card_ids"]

    # The device recomputes the id from the UID it read, using only what the
    # response gave it (the same HMAC the Flutter app implements).
    key = base64.b64decode(keys["revocation_key"])
    device_id = hmac_mod.new(key, f"rev|{auth.canonical_nfc_uid(uid)}".encode(), hashlib.sha256).hexdigest()[:32]
    assert device_id == rid

    # Registering the same card again re-enables it and drops it from the list.
    _register(test_client, h, patient, uid)
    assert rid not in test_client.get("/emergency/tag-keys", headers=h).json()["revoked_card_ids"]


def test_expired_revoked_cards_are_left_off_the_list(test_client, make_user, auth_headers, db_session):
    from datetime import datetime, timedelta, timezone

    from app import auth, models as m

    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    patient = _patient(db_session)
    uid = secrets.token_hex(7).upper()
    grant = _register(test_client, h, patient, uid)
    test_client.post(f"/emergency/nfc/revoke/{grant['id']}", headers=h)
    row = db_session.query(m.EmergencyToken).filter_by(id=grant["id"]).first()
    rid = tag_crypto.revocation_id(auth.canonical_nfc_uid(uid))

    # Lapsed hours ago: the sealed expiry is date-only, so a device still opens
    # the record until the end of that UTC day -- it must stay listed.
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    db_session.commit()
    assert rid in test_client.get("/emergency/tag-keys", headers=h).json()["revoked_card_ids"]

    # Lapsed days ago: every device refuses it by date, so it drops off the list.
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
    db_session.commit()
    assert rid not in test_client.get("/emergency/tag-keys", headers=h).json()["revoked_card_ids"]


def test_revoking_a_card_with_no_revocation_id_says_it_is_not_offline_revocable(
        test_client, make_user, auth_headers, db_session):
    from app import models as m

    clin = make_user(role="clinician", facility="Main Hospital")
    h = auth_headers(clin)
    patient = _patient(db_session)
    grant = _register(test_client, h, patient, secrets.token_hex(7).upper())

    res = test_client.post(f"/emergency/nfc/revoke/{grant['id']}", headers=h).json()
    assert res == {"status": "revoked", "offline_revocable": True}

    # A card issued before the column existed has no id to list.
    row = db_session.query(m.EmergencyToken).filter_by(id=grant["id"]).first()
    row.nfc_revocation_id = None
    db_session.commit()
    res = test_client.post(f"/emergency/nfc/revoke/{grant['id']}", headers=h).json()
    assert res == {"status": "revoked", "offline_revocable": False}


def test_key_max_age_defaults_to_24h_and_is_configurable(test_client, make_user, auth_headers, monkeypatch):
    h = auth_headers(make_user(role="clinician", facility="Main Hospital"))
    assert test_client.get("/emergency/tag-keys", headers=h).json()["key_max_age_hours"] == 24
    monkeypatch.setenv("CLARION_TAG_KEY_MAX_AGE_HOURS", "6")
    assert test_client.get("/emergency/tag-keys", headers=h).json()["key_max_age_hours"] == 6
    monkeypatch.setenv("CLARION_TAG_KEY_MAX_AGE_HOURS", "0")
    with pytest.raises(RuntimeError):
        tag_crypto.key_max_age_hours()


def test_revocation_id_is_stable_and_tied_to_the_uid():
    a = tag_crypto.revocation_id("04A1B2C3D4E5F6")
    assert a == tag_crypto.revocation_id("04A1B2C3D4E5F6")
    assert a != tag_crypto.revocation_id("04A1B2C3D4E5F7")
    assert len(a) == 32
