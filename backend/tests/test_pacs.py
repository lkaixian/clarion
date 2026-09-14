"""P4.7 PACS/DICOM imaging (routers/pacs.py + app/pacs.py). Orthanc itself
is never actually called -- every test monkeypatches app.pacs's three
client functions (upload_instance/get_study/get_instance_file), same
"mock the local/on-prem client, test our own logic" discipline as
test_cds_hint.py mocking generate_text."""
import io
import zipfile

from app import models, pacs
from app.routers import pacs as pacs_router
from conftest import _facility, _make_patient


def _fake_dicom(tag: bytes = b"one") -> bytes:
    return b"\x00" * 128 + b"DICM" + tag


def _fake_zip(*tags: bytes, extra_junk: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, tag in enumerate(tags):
            zf.writestr(f"IM{i}.dcm", _fake_dicom(tag))
        if extra_junk:
            zf.writestr("DICOMDIR", b"not a dicom file at all")
    return buf.getvalue()


def _make_catalog_item(db_session, module="xray"):
    item = models.ServiceCatalogItem(module=module, name="Chest X-ray", unit_price_cents=5000)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _make_request(db_session, patient_id, facility, module="xray", status="ordered"):
    item = _make_catalog_item(db_session, module=module)
    req = models.ServiceRequest(
        patient_id=patient_id, module=module, catalog_item_id=item.id, source="frontdesk",
        status=status, ordering_facility_name=facility, priority="routine",
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)
    return req


def _mock_orthanc(monkeypatch, *, study_id="orthanc-study-1", description="CHEST 2 VIEWS"):
    """One instance id per call, a shared study id -- mirrors what a real
    multi-instance study upload looks like."""
    counter = {"n": 0}

    def _upload(raw):
        counter["n"] += 1
        return {"ID": f"instance-{counter['n']}", "ParentStudy": study_id, "Status": "Success"}

    monkeypatch.setattr(pacs, "upload_instance", _upload)
    monkeypatch.setattr(pacs, "get_study", lambda sid: {"MainDicomTags": {"StudyDescription": description}})
    monkeypatch.setattr(pacs, "get_instance_file", lambda iid: f"bytes-for-{iid}".encode())


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_single_dicom_file(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["instances"] == ["instance-1"]
    assert body["description"] == "CHEST 2 VIEWS"

    # The worklist now reflects it.
    listed = test_client.get("/ancillary/requests", params={"module": "xray"}, headers=auth_headers(clinician)).json()
    assert next(r for r in listed if r["id"] == req.id)["has_dicom_study"] is True


def test_upload_zip_with_multiple_instances_skips_non_dicom_members(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    zip_bytes = _fake_zip(b"a", b"b", extra_junk=True)
    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["instances"] == ["instance-1", "instance-2"]  # DICOMDIR silently skipped


def test_upload_rejects_non_dicom_file(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert resp.status_code == 422


def test_upload_rejects_non_xray_module(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility, module="laboratory")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 400


def test_upload_rejects_second_study_on_same_request(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    files = {"file": ("study.dcm", _fake_dicom(), "application/dicom")}
    first = test_client.post(f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician), files=files)
    assert first.status_code == 201
    second = test_client.post(f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician), files=files)
    assert second.status_code == 409


def test_upload_rejects_cancelled_request(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility, status="cancelled")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 400


def test_upload_facility_scoped(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility_a, facility_b = _facility("A"), _facility("B")
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician_b),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 404  # scoped-404, not 403 -- same shape as every other cross-facility write here


def test_upload_rejects_zip_that_decompresses_past_the_cap(test_client, make_user, auth_headers, db_session, monkeypatch):
    """Regression for the voltagent finding (2026-09-14): the guard must
    bound the ACTUAL decompressed bytes as they stream out, never a
    declared/trusted size -- a highly-compressible member (a small zip, a
    huge real payload) is exactly the shape a forged-`file_size` zip bomb
    would also produce, and the fixed code doesn't consult `file_size` for
    this decision at all, so this reproduces the same abort path."""
    monkeypatch.setattr(pacs_router, "MAX_DICOM_UPLOAD_BYTES", 4096)  # small cap for the test
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Highly compressible: the zip file itself stays well under the
        # (now 4096-byte) cap, but the member decompresses to ~25x that --
        # the exact "small compressed footprint, huge decompressed size"
        # shape a forged-file_size zip bomb would also produce. The fixed
        # code never reads `file_size` for this decision, so this reproduces
        # the same abort path a hand-forged header would need to survive.
        zf.writestr("big.dcm", _fake_dicom() + b"\x00" * (1024 * 100))
    assert len(buf.getvalue()) < 4096  # sanity: the exploit shape actually holds

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 413


def test_upload_orthanc_unavailable_returns_503(test_client, make_user, auth_headers, db_session, monkeypatch):
    def _boom(raw):
        raise pacs.PacsError("connection refused")
    monkeypatch.setattr(pacs, "upload_instance", _boom)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 503


def test_upload_requires_signoff_role_not_just_order_role(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    receptionist = make_user(role="receptionist", facility=facility)

    resp = test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(receptionist),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# View metadata + instance membership check
# ---------------------------------------------------------------------------

def test_get_study_and_fetch_instance_file(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)
    test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )

    meta = test_client.get(f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician))
    assert meta.status_code == 200, meta.text
    instance_id = meta.json()["instances"][0]

    file_resp = test_client.get(
        f"/pacs/requests/{req.id}/study/instances/{instance_id}/file", headers=auth_headers(clinician),
    )
    assert file_resp.status_code == 200
    assert file_resp.content == f"bytes-for-{instance_id}".encode()
    assert file_resp.headers["content-type"] == "application/dicom"


def test_instance_id_cannot_be_borrowed_from_another_study(test_client, make_user, auth_headers, db_session, monkeypatch):
    """A caller who can see study A must not be able to read study B's
    pixel data by guessing/reusing one of B's instance ids -- the
    membership check is against THIS study's own stored list, not "is this
    a real Orthanc instance id anywhere"."""
    _mock_orthanc(monkeypatch)
    facility = _facility()
    patient = _make_patient(db_session)
    req_a = _make_request(db_session, patient.id, facility)
    req_b = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    test_client.post(
        f"/pacs/requests/{req_a.id}/study", headers=auth_headers(clinician),
        files={"file": ("a.dcm", _fake_dicom(), "application/dicom")},
    )
    resp_b = test_client.post(
        f"/pacs/requests/{req_b.id}/study", headers=auth_headers(clinician),
        files={"file": ("b.dcm", _fake_dicom(), "application/dicom")},
    )
    instance_id_b = resp_b.json()["instances"][0]

    # instance_id_b genuinely exists (in study B) but was never uploaded
    # against study A -- fetching it through study A's endpoint must 404.
    resp = test_client.get(
        f"/pacs/requests/{req_a.id}/study/instances/{instance_id_b}/file", headers=auth_headers(clinician),
    )
    assert resp.status_code == 404


def test_get_study_facility_scoped_with_continuity_of_care_exception(test_client, make_user, auth_headers, db_session, monkeypatch):
    _mock_orthanc(monkeypatch)
    facility_a, facility_b = _facility("A"), _facility("B")
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility_a)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)

    test_client.post(
        f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician_a),
        files={"file": ("study.dcm", _fake_dicom(), "application/dicom")},
    )

    # Same continuity-of-care default as the rest of this codebase: another
    # facility CAN read it (no opt-out configured) -- see
    # clinical_access._hidden_author_facilities.
    resp = test_client.get(f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician_b))
    assert resp.status_code == 200


def test_get_study_404_when_none_uploaded(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    req = _make_request(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.get(f"/pacs/requests/{req.id}/study", headers=auth_headers(clinician))
    assert resp.status_code == 404
