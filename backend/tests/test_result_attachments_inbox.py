"""Result attachments at ancillary sign-off + the in-app inbox they feed.

Covers: staging -> sign-off links and seals the files, the orderer is
notified by default, type validation is by the file's own bytes, pending
files are private to the uploader, and removing an attachment after
sign-off flips the seal to "altered".
"""
import io
import json
import zipfile

from PIL import Image

from app import models
from conftest import _facility, _make_patient, _TEST_SIGNATURE_B64
from test_ancillary import _make_catalog_item, _order_body


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _docx(extra=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        for name in extra:
            z.writestr(name, "x")
    return buf.getvalue()


def _setup(test_client, db_session, make_user, auth_headers):
    facility = _facility("Facility A")
    orderer = make_user(role="clinician", facility=facility)
    signer = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    req = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(orderer)
    ).json()
    return orderer, signer, req


def _stage(test_client, auth_headers, user, req_id, name, data, mime="application/octet-stream"):
    return test_client.post(
        f"/ancillary/requests/{req_id}/attachments",
        files={"file": (name, data, mime)},
        headers=auth_headers(user),
    )


def test_attachments_sign_off_seal_and_notify_orderer(test_client, make_user, auth_headers, db_session):
    orderer, signer, req = _setup(test_client, db_session, make_user, auth_headers)

    ids = []
    for name, data in (
        ("slip.png", _png()),
        ("lab.txt", b"Hb 13.2 g/dL"),
        ("lab.json", json.dumps({"hb": 13.2}).encode()),
        ("report.docx", _docx()),
    ):
        r = _stage(test_client, auth_headers, signer, req["id"], name, data)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    # No typed result at all: attachments alone are enough.
    resp = test_client.post(
        f"/ancillary/requests/{req['id']}/result",
        json={"attachment_ids": ids, "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(signer),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert {a["filename"] for a in result["attachments"]} == {"slip.png", "lab.txt", "lab.json", "report.docx"}
    assert result["seal_status"] == "valid"

    # Downloads are attachment + nosniff; non-PDF/image types never get a renderable type.
    txt_id = next(a["id"] for a in result["attachments"] if a["filename"] == "lab.json")
    dl = test_client.get(
        f"/ancillary/requests/{req['id']}/attachments/{txt_id}", headers=auth_headers(orderer)
    )
    assert dl.status_code == 200
    assert dl.content == json.dumps({"hb": 13.2}).encode()
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert dl.headers["x-content-type-options"] == "nosniff"
    assert dl.headers["content-type"] == "application/octet-stream"

    # The orderer (not the signer) got the notification, by default.
    inbox = test_client.get("/notifications", headers=auth_headers(orderer)).json()
    assert len(inbox) == 1 and inbox[0]["kind"] == "result_ready" and inbox[0]["read_at"] is None
    assert test_client.get("/notifications/unread-count", headers=auth_headers(orderer)).json() == {"unread": 1}
    assert test_client.get("/notifications", headers=auth_headers(signer)).json() == []

    # Only the owner can mark it; marking drops the unread count.
    nid = inbox[0]["id"]
    assert test_client.post(f"/notifications/{nid}/read", headers=auth_headers(signer)).status_code == 404
    assert test_client.post(f"/notifications/{nid}/read", headers=auth_headers(orderer)).status_code == 200
    assert test_client.get("/notifications/unread-count", headers=auth_headers(orderer)).json() == {"unread": 0}

    # Removing an attachment afterwards breaks the seal -- it is part of the record.
    db_session.query(models.ServiceResultAttachment).filter(
        models.ServiceResultAttachment.id == txt_id
    ).delete()
    db_session.commit()
    again = test_client.get(f"/ancillary/requests/{req['id']}", headers=auth_headers(orderer)).json()
    assert again["result"]["seal_status"] == "altered"


def test_attachment_type_validation_is_by_content(test_client, make_user, auth_headers, db_session):
    _, signer, req = _setup(test_client, db_session, make_user, auth_headers)
    rid = req["id"]

    bad = {
        "old.doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,   # legacy OLE Word
        "tool.exe": b"MZ" + b"\x00" * 64,
        "fake.pdf": _png(),                                              # extension lies
        "macro.docx": _docx(extra=("word/vbaProject.bin",)),
        "embedded.docx": _docx(extra=("word/embeddings/oleObject1.bin",)),
        "broken.json": b"{not json",
        "binary.txt": b"abc\x00def",
    }
    for name, data in bad.items():
        r = _stage(test_client, auth_headers, signer, rid, name, data)
        assert r.status_code == 422, (name, r.status_code, r.text)
    assert ".docx" in _stage(test_client, auth_headers, signer, rid, "old.doc", bad["old.doc"]).json()["detail"]

    ok = {
        "r.pdf": b"%PDF-1.4\n%%EOF",
        "scan.png": _png(),
        "note.txt": "Hb 13.2 µg".encode("utf-8"),
        "msg.hl7": b"MSH|^~\\&|LIS|LAB|CLARION|HOSP|202610101200||ORU^R01|1|P|2.5.1",
        "study.dcm": b"\x00" * 128 + b"DICM" + b"\x00" * 16,
    }
    for name, data in ok.items():
        r = _stage(test_client, auth_headers, signer, rid, name, data)
        assert r.status_code == 201, (name, r.text)


def test_pending_attachments_are_private_and_self_order_is_silent(test_client, make_user, auth_headers, db_session):
    orderer, signer, req = _setup(test_client, db_session, make_user, auth_headers)
    other = make_user(role="clinician", facility=orderer.facility)

    att = _stage(test_client, auth_headers, signer, req["id"], "a.txt", b"hello").json()

    # Another clinician can neither download, delete, nor sign off with it.
    url = f"/ancillary/requests/{req['id']}/attachments/{att['id']}"
    assert test_client.get(url, headers=auth_headers(other)).status_code == 404
    assert test_client.delete(url, headers=auth_headers(other)).status_code == 404
    r = test_client.post(
        f"/ancillary/requests/{req['id']}/result",
        json={"attachment_ids": [att["id"]], "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(other),
    )
    assert r.status_code == 400

    # The uploader can fetch and remove their own pending file.
    assert test_client.get(url, headers=auth_headers(signer)).status_code == 200
    assert test_client.delete(url, headers=auth_headers(signer)).status_code == 200
    assert test_client.get(url, headers=auth_headers(signer)).status_code == 404

    # Signing your own order notifies nobody.
    r = test_client.post(
        f"/ancillary/requests/{req['id']}/result",
        json={"result_text": "ok", "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(orderer),
    )
    assert r.status_code == 200
    assert test_client.get("/notifications", headers=auth_headers(orderer)).json() == []


def test_receptionist_orderer_gets_no_result_notification(test_client, make_user, auth_headers, db_session):
    """A receptionist can place orders but is not a clinical reader: no inbox
    entry, so a critical flag can't reach them through the bell."""
    facility = _facility("Facility A")
    receptionist = make_user(role="receptionist", facility=facility)
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, facility_name=None)
    req = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(receptionist)
    ).json()

    r = test_client.post(
        f"/ancillary/requests/{req['id']}/result",
        json={"result_text": "K 6.9", "flag_critical": True, "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(clinician),
    )
    assert r.status_code == 200, r.text
    assert test_client.get("/notifications", headers=auth_headers(receptionist)).json() == []


def test_seal_covers_attachment_filename(test_client, make_user, auth_headers, db_session):
    _, signer, req = _setup(test_client, db_session, make_user, auth_headers)
    att = _stage(test_client, auth_headers, signer, req["id"], "result.txt", b"Hb 13").json()
    r = test_client.post(
        f"/ancillary/requests/{req['id']}/result",
        json={"attachment_ids": [att["id"]], "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(signer),
    )
    assert r.json()["result"]["seal_status"] == "valid"

    db_session.query(models.ServiceResultAttachment).filter(
        models.ServiceResultAttachment.id == att["id"]
    ).update({"filename": "other.txt"})
    db_session.commit()
    again = test_client.get(f"/ancillary/requests/{req['id']}", headers=auth_headers(signer)).json()
    assert again["result"]["seal_status"] == "altered"


def test_expired_staged_file_is_a_400_and_old_rows_do_not_fill_the_cap(test_client, make_user, auth_headers, db_session):
    from datetime import datetime, timedelta, timezone
    from app.storage import BUCKET_SCRATCH, get_object_store

    _, signer, req = _setup(test_client, db_session, make_user, auth_headers)
    rid = req["id"]

    # A staged file whose scratch object has expired: clear 400, not a looping 503.
    att = _stage(test_client, auth_headers, signer, rid, "a.txt", b"x").json()
    row = db_session.query(models.ServiceResultAttachment).filter_by(id=att["id"]).one()
    get_object_store().delete(BUCKET_SCRATCH, row.file_object_key)
    r = test_client.post(
        f"/ancillary/requests/{rid}/result",
        json={"attachment_ids": [att["id"]], "signature_b64": _TEST_SIGNATURE_B64},
        headers=auth_headers(signer),
    )
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    # ...and the request is still open (nothing half-signed).
    assert test_client.get(f"/ancillary/requests/{rid}", headers=auth_headers(signer)).json()["status"] == "ordered"

    # Staged rows older than the scratch TTL neither count toward the cap nor are listed.
    row.created_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()
    assert test_client.get(f"/ancillary/requests/{rid}/attachments", headers=auth_headers(signer)).json() == []

    fresh = _stage(test_client, auth_headers, signer, rid, "b.txt", b"y").json()
    listed = test_client.get(f"/ancillary/requests/{rid}/attachments", headers=auth_headers(signer)).json()
    assert [a["id"] for a in listed] == [fresh["id"]]
