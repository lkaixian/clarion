"""P1.7b — GET /patients/{id}/documents/{doc_id}/thumbnail: the ?size=1400
web-preview variant, PDF page-1 rendering, and the ETag/If-None-Match 304
path added on top of P1.7's existing 300px raster thumbnail (already covered
at the imaging.py/derived.py unit level by test_imaging.py/test_derived.py).
"""
import io

from PIL import Image
from reportlab.pdfgen import canvas

from app import models


def _make_patient(db_session):
    patient = models.Patient(full_name="Thumb Test Patient", date_of_birth="1990-01-01")
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _pdf_bytes(w=400, h=300) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFillColorRGB(0.8, 0.2, 0.2)
    c.rect(0, 0, w, h, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


def _upload(test_client, headers, patient_id, filename, data, content_type, doc_type="lab_report"):
    resp = test_client.post(
        f"/ai/digitise/{patient_id}",
        headers=headers,
        params={"doc_type": doc_type},
        files={"file": (filename, data, content_type)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


def test_pdf_document_gets_a_rendered_thumbnail(test_client, make_user, db_session, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    headers = auth_headers(clinician)
    doc_id = _upload(test_client, headers, patient.id, "report.pdf", _pdf_bytes(), "application/pdf")

    resp = test_client.get(f"/patients/{patient.id}/documents/{doc_id}/thumbnail", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert img.format == "JPEG"
    assert max(img.size) <= 300


def test_preview_size_param_renders_a_bigger_variant(test_client, make_user, db_session, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    headers = auth_headers(clinician)
    doc_id = _upload(test_client, headers, patient.id, "report.pdf", _pdf_bytes(), "application/pdf")

    thumb = test_client.get(f"/patients/{patient.id}/documents/{doc_id}/thumbnail", headers=headers)
    preview = test_client.get(
        f"/patients/{patient.id}/documents/{doc_id}/thumbnail", headers=headers, params={"size": 1400},
    )
    assert preview.status_code == 200, preview.text
    preview_img = Image.open(io.BytesIO(preview.content))
    thumb_img = Image.open(io.BytesIO(thumb.content))
    assert max(preview_img.size) > max(thumb_img.size)


def test_unsupported_size_rejected(test_client, make_user, db_session, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    headers = auth_headers(clinician)
    doc_id = _upload(test_client, headers, patient.id, "report.pdf", _pdf_bytes(), "application/pdf")

    resp = test_client.get(
        f"/patients/{patient.id}/documents/{doc_id}/thumbnail", headers=headers, params={"size": 999},
    )
    assert resp.status_code == 422


def test_etag_round_trip_returns_304(test_client, make_user, db_session, auth_headers):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    headers = auth_headers(clinician)
    doc_id = _upload(test_client, headers, patient.id, "report.pdf", _pdf_bytes(), "application/pdf")

    first = test_client.get(f"/patients/{patient.id}/documents/{doc_id}/thumbnail", headers=headers)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag

    second = test_client.get(
        f"/patients/{patient.id}/documents/{doc_id}/thumbnail",
        headers={**headers, "If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.content == b""
