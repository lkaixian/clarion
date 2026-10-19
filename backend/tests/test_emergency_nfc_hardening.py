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

from app import auth, models, tag_crypto


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


# --------------------------------------------------------------------------
# Offline NFC-tag record (P5.x follow-up): the register response includes a
# sealed `tag_blob` meant to be written DIRECTLY onto the physical tag's own
# NDEF memory, so a responder can still read blood type / allergies / meds
# with ZERO network (not just when the WAN link specifically is down, but
# the whole backend). Plaintext is never returned. See
# routers/emergency.py::_build_compact_tag_text's own docstring.
# --------------------------------------------------------------------------

def _tag_plain(body, uid):
    """The sealed blob's contents with the leading `X:<expiry>|` stripped."""
    return tag_crypto.open_blob(body["tag_blob"], auth.canonical_nfc_uid(uid)).split("|", 1)[1]


def test_register_response_includes_sealed_tag_blob_and_no_plaintext(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H7")
    patient = _patient(db_session, full_name="M7 TagText", blood_type="O+")
    _present(db_session, patient, "H7")
    db_session.add(models.AllergyIntolerance(
        patient_id=patient.id, substance="Penicillin", severity="severe", critical_for_emergency=True,
    ))
    db_session.commit()

    uid = _uid()
    resp = _register(test_client, auth_headers, staff, patient.id, uid)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _tag_plain(body, uid) == "BT:O+|AL:Penicillin(severe)"
    assert body["tag_blob_truncated"] is False
    assert "tag_text" not in body and "tag_text_truncated" not in body


def test_register_response_omits_non_critical_and_non_scoped_items(test_client, db_session, make_user, auth_headers):
    """Only critical_for_emergency items make it onto the tag, and only
    for categories actually in the requested scope -- same rules the
    online _scoped_fields already enforces, reused not re-derived."""
    staff = make_user(role="clinician", facility="H8")
    patient = _patient(db_session, full_name="M7 ScopeCheck", blood_type="A-")
    _present(db_session, patient, "H8")
    db_session.add_all([
        models.AllergyIntolerance(
            patient_id=patient.id, substance="Pollen", severity="mild", critical_for_emergency=False,
        ),
        models.MedicationStatement(
            patient_id=patient.id, drug_name="Paracetamol", active=True, critical_for_emergency=True,
        ),
    ])
    db_session.commit()

    uid = _uid()
    resp = test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "nfc_uid": uid, "scope": ["allergies", "blood_type"]},
    )
    assert resp.status_code == 200, resp.text
    # medications not in scope -> never appears; the mild allergy isn't
    # critical -> also never appears. Only blood type makes it on.
    assert _tag_plain(resp.json(), uid) == "BT:A-"


def test_tag_blob_truncates_to_the_requested_capacity_and_flags_it(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H9")
    patient = _patient(db_session, full_name="M7 Truncate", blood_type="AB+")
    _present(db_session, patient, "H9")
    db_session.add_all([
        models.AllergyIntolerance(
            patient_id=patient.id, substance="Penicillin", severity="severe", critical_for_emergency=True,
        ),
        models.AllergyIntolerance(
            patient_id=patient.id, substance="Sulfa Drugs", severity="severe", critical_for_emergency=True,
        ),
    ])
    db_session.commit()

    # Smallest tag the sealed record fits on -- room for "BT:AB+" but not
    # the first allergy on top of it.
    uid = _uid()
    resp = test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": 89},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _tag_plain(body, uid).startswith("BT:AB+")
    assert body["tag_blob_truncated"] is True
    assert len(body["tag_blob"]) <= 89


def test_tag_too_small_for_the_sealed_record_is_refused_and_not_registered(test_client, db_session, make_user, auth_headers):
    """No plaintext fallback: a tag that can't hold the sealed blob gets a
    422 with a clear message, and no grant is created."""
    staff = make_user(role="clinician", facility="H12")
    patient = _patient(db_session, full_name="M7 TooSmall", blood_type="B+")
    _present(db_session, patient, "H12")
    uid = _uid()

    resp = test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "nfc_uid": uid, "tag_max_bytes": 16},
    )
    assert resp.status_code == 422, resp.text
    assert "larger tag" in resp.json()["detail"]
    assert db_session.query(models.EmergencyToken).filter_by(nfc_uid=auth.hash_nfc_uid(uid)).count() == 0


def test_patient_with_no_critical_data_registers_with_no_blob(test_client, db_session, make_user, auth_headers):
    """Nothing to seal is not an error: the card works online, nothing is written."""
    staff = make_user(role="clinician", facility="H13")
    patient = _patient(db_session, full_name="M7 Healthy")
    _present(db_session, patient, "H13")

    resp = _register(test_client, auth_headers, staff, patient.id, _uid())
    assert resp.status_code == 200, resp.text
    assert resp.json()["tag_blob"] is None


def test_tag_blob_sanitizes_the_field_separator_out_of_free_text(test_client, db_session, make_user, auth_headers):
    """`|` is the compact format's own field separator with no escaping --
    a substance name that happened to contain one would otherwise corrupt
    the parse on the mobile reading side."""
    staff = make_user(role="clinician", facility="H11")
    patient = _patient(db_session, full_name="M7 PipeChar")
    _present(db_session, patient, "H11")
    db_session.add(models.AllergyIntolerance(
        patient_id=patient.id, substance="Foo|Bar", severity="severe", critical_for_emergency=True,
    ))
    db_session.commit()

    uid = _uid()
    resp = _register(test_client, auth_headers, staff, patient.id, uid)
    assert resp.status_code == 200, resp.text
    # The stray "|" became "/" -- had it survived, this would parse back
    # (mobile_flutter's fromCompactTagText) as two separate fields instead
    # of one allergy.
    assert _tag_plain(resp.json(), uid) == "AL:Foo/Bar(severe)"


def test_tag_max_bytes_out_of_range_is_rejected(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H10")
    patient = _patient(db_session, full_name="M7 BadBytes")
    _present(db_session, patient, "H10")

    resp = test_client.post(
        "/emergency/nfc/register",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "nfc_uid": _uid(), "tag_max_bytes": 4},
    )
    assert resp.status_code == 422


def test_card_list_flags_a_tag_that_no_longer_matches_the_patient(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H14")
    patient = _patient(db_session, full_name="M7 Stale", blood_type="O+")
    _present(db_session, patient, "H14")
    uid = _uid()
    assert _register(test_client, auth_headers, staff, patient.id, uid).status_code == 200

    def stale():
        cards = test_client.get(f"/emergency/nfc/{patient.id}", headers=auth_headers(staff)).json()
        return cards[0]["tag_stale"]

    assert stale() is False  # just written
    db_session.add(models.AllergyIntolerance(
        patient_id=patient.id, substance="Penicillin", severity="severe", critical_for_emergency=True))
    db_session.commit()
    assert stale() is True  # a new life-threatening allergy the card does not show
    assert _register(test_client, auth_headers, staff, patient.id, uid).status_code == 200  # rewritten
    assert stale() is False


def test_card_written_empty_goes_stale_when_critical_data_appears(test_client, db_session, make_user, auth_headers):
    staff = make_user(role="clinician", facility="H15")
    patient = _patient(db_session, full_name="M7 EmptyCard")
    _present(db_session, patient, "H15")
    assert _register(test_client, auth_headers, staff, patient.id, _uid()).status_code == 200

    def stale():
        return test_client.get(f"/emergency/nfc/{patient.id}", headers=auth_headers(staff)).json()[0]["tag_stale"]

    assert stale() is False
    db_session.add(models.AllergyIntolerance(
        patient_id=patient.id, substance="Latex", severity="severe", critical_for_emergency=True))
    db_session.commit()
    assert stale() is True
