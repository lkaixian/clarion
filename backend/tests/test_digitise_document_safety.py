"""Security Audit finding M5 (upload magic-byte check) — POST
/ai/digitise/{patient_id} used to hand ANY uploaded bytes straight to
PIL/pytesseract with no format allowlist or pixel-bomb ceiling of its own.
Covers the fix: image-shaped uploads are validated through
app/imaging.py's hardened decode path (P1.7) before OCR is attempted; a
non-image upload (e.g. a PDF) is tolerated as before (OCR just skipped,
original still archived) rather than rejected.
"""
import io

from PIL import Image

from app import models


def _make_patient(db_session):
    patient = models.Patient(full_name="Doc Test Patient", date_of_birth="1990-01-01")
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _png_bytes(size=(50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def test_valid_image_upload_still_runs_ocr_path(test_client, make_user, db_session):
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    resp = test_client.post(
        f"/ai/digitise/{patient.id}",
        headers=auth_headers_for(test_client, clinician),
        params={"doc_type": "prescription"},
        files={"file": ("scan.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "OCR skipped: not an image" not in body["raw_text"]
    assert "failed safety validation" not in body["raw_text"]


def test_non_image_upload_ocr_skipped_gracefully_not_rejected(test_client, make_user, db_session):
    """A genuine non-image doc (e.g. a PDF) must still be ACCEPTED (200) --
    OCR is simply skipped, the original is still archived. This must not
    regress into an outright rejection."""
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    fake_pdf_bytes = b"%PDF-1.4\n%fake pdf content for test\n"
    resp = test_client.post(
        f"/ai/digitise/{patient.id}",
        headers=auth_headers_for(test_client, clinician),
        params={"doc_type": "discharge_summary"},
        files={"file": ("summary.pdf", fake_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    assert "OCR skipped: not an image format" in resp.json()["raw_text"]


def test_malformed_image_bytes_skip_ocr_not_crash(test_client, make_user, db_session):
    """Bytes that sniff as a PNG (correct magic header) but are truncated/
    corrupt after that must fail imaging's hardened decode gracefully --
    never a 500."""
    clinician = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    truncated_png = _png_bytes()[:20]  # valid PNG signature, corrupt body
    resp = test_client.post(
        f"/ai/digitise/{patient.id}",
        headers=auth_headers_for(test_client, clinician),
        params={"doc_type": "lab_report"},
        files={"file": ("broken.png", truncated_png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert "failed safety validation" in resp.json()["raw_text"]


def auth_headers_for(test_client, user) -> dict:
    resp = test_client.post(
        "/auth/login", data={"username": user.email, "password": user.plaintext_password}
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
