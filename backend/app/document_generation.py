"""P3.5: PDF generation for signed, staff-issued patient documents (Digital
Medical Certificate / Referral Letter / Timeslip -- the tender).

Deliberately NOT a template engine or multi-page report builder -- each of
the 3 document types is one fixed-layout A4 page, drawn directly with
reportlab's low-level Canvas (the same "simplest tool that draws a form"
choice app/imaging.py made for image normalisation with raw Pillow, rather
than pulling in a full HTML-to-PDF stack). The signer's saved signature PNG
is composited straight onto the page raster -- the rendered PDF bytes are
themselves the one WORM artifact (routers/patients.py::generate_document
stores them via ClinicalDocument + the `clarion-documents` bucket, same as
any other clinical document), so unlike Encounter/ConsultationNote/
ClinicalRecordAnnotation there is no separate signature-snapshot object
that needs to stay in sync with a record.
"""
from __future__ import annotations

import io
import textwrap
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

GENERATED_DOC_TYPES = {"medical_certificate", "referral_letter", "timeslip", "visit_summary"}

_TITLES = {
    "medical_certificate": "DIGITAL MEDICAL CERTIFICATE",
    "referral_letter": "REFERRAL LETTER",
    "timeslip": "CLINIC ATTENDANCE TIMESLIP",
    "visit_summary": "VISIT SUMMARY",
}

_PAGE_W, _PAGE_H = A4
_MARGIN = 20 * mm
_WRAP_WIDTH = 95  # characters -- reportlab's Canvas has no built-in text wrap


def _wrapped(label: str, text: str) -> list[str]:
    """`Label: long free text...` wrapped to _WRAP_WIDTH, continuation lines
    indented to line up under the value (not the label)."""
    prefix = f"{label}: "
    wrapped = textwrap.wrap(text, width=_WRAP_WIDTH) or [""]
    lines = [prefix + wrapped[0]]
    lines += [" " * len(prefix) + w for w in wrapped[1:]]
    return lines


def _content_lines(doc_type: str, patient, fields: dict) -> list[str]:
    """The body text, as plain lines -- shared between the PDF page and the
    ClinicalDocument.raw_text summary (so raw_text is never a second,
    independently-maintained copy of what the certificate actually says)."""
    header = [
        f"Patient: {patient.full_name}",
        f"NRIC / ID: {patient.national_id or '-'}",
        f"Date of birth: {patient.date_of_birth}",
        "",
    ]
    if doc_type == "medical_certificate":
        body = [
            "This is to certify that the above-named patient was examined and",
            f"is unfit for duty/school from {fields['rest_from']} to {fields['rest_to']} inclusive.",
            "",
            *_wrapped("Diagnosis / reason", fields["diagnosis"]),
        ]
        if fields.get("remarks"):
            body += ["", *_wrapped("Remarks", fields["remarks"])]
    elif doc_type == "referral_letter":
        body = [
            f"Referred to: {fields['referred_to']}",
            f"Urgency: {fields.get('urgency') or 'routine'}",
            "",
            *_wrapped("Reason for referral", fields["reason_for_referral"]),
        ]
        if fields.get("clinical_summary"):
            body += ["", *_wrapped("Clinical summary", fields["clinical_summary"])]
    elif doc_type == "timeslip":
        # fields['time_in']/['time_out'] are real datetime.time objects
        # (schemas.GenerateDocumentRequest types them `time`, not `str`) --
        # str(time(9, 0)) is "09:00:00", a redundant ":00" seconds suffix on
        # an official document nobody asked to the second. strftime instead.
        body = [
            "This is to certify that the above-named patient attended this clinic",
            f"on {fields['visit_date']} from {fields['time_in'].strftime('%H:%M')} "
            f"to {fields['time_out'].strftime('%H:%M')}.",
        ]
        if fields.get("purpose"):
            body += ["", *_wrapped("Purpose", fields["purpose"])]
    elif doc_type == "visit_summary":
        # P3.10: rendered read-only from an already-signed
        # Encounter/ConsultationNote -- unlike the 3 types above, the
        # caller here is routers/patients.py::get_visit_summary_pdf, not
        # POST /documents/generate (see schemas.VALID_GENERATED_DOC_TYPES,
        # which deliberately does NOT include "visit_summary" -- nothing
        # free-text/staff-entered is being issued, so it doesn't belong on
        # that surface).
        body = [
            f"Visit date: {fields['visit_date']}",
            f"Doctor: {fields.get('doctor_name') or '-'}",
            f"Department: {fields.get('department') or '-'}",
            "",
        ]
        if fields.get("vitals_line"):
            body += [f"Vitals: {fields['vitals_line']}", ""]
        if fields.get("assessment"):
            body += _wrapped("Diagnosis", fields["assessment"]) + [""]
        if fields.get("plan") or fields.get("treatment_plan"):
            treatment = " ".join(x for x in (fields.get("plan"), fields.get("treatment_plan")) if x)
            body += _wrapped("Treatment", treatment)
    else:  # pragma: no cover -- guarded by schemas.VALID_GENERATED_DOC_TYPES before this is called
        raise ValueError(f"Unknown generated doc_type: {doc_type}")
    return header + body


def render_document(
    doc_type: str,
    patient,
    fields: dict,
    *,
    facility_name: Optional[str],
    signer_name: str,
    signer_role: Optional[str],
    signed_at: datetime,
    signature_png: Optional[bytes] = None,
    seal_code: Optional[str] = None,
) -> tuple[bytes, str]:
    """Render one signed A4 PDF page. Returns (pdf_bytes, plain_text) -- the
    plain_text is stored as ClinicalDocument.raw_text, the same field an
    uploaded scan's OCR output lands in, so this document is searchable/
    summarisable through the same downstream path."""
    lines = _content_lines(doc_type, patient, fields)
    title = _TITLES[doc_type]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    y = _PAGE_H - _MARGIN
    c.setFont("Helvetica-Bold", 14)
    c.drawString(_MARGIN, y, facility_name or "CLARION Clinic")
    y -= 9 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(_PAGE_W / 2, y, title)
    y -= 5 * mm
    c.setLineWidth(0.5)
    c.line(_MARGIN, y, _PAGE_W - _MARGIN, y)
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    for line in lines:
        if y < _MARGIN + 45 * mm:  # would collide with the signature block below
            # ponytail: single-page only, remaining lines are silently dropped
            # rather than overflowing onto a 2nd page. Field lengths are capped
            # in schemas.py to fit one page for the normal case; add real
            # pagination if a longer clinical_summary/remarks turns out needed.
            break
        c.drawString(_MARGIN, y, line)
        y -= 6 * mm

    sig_y = _MARGIN + 30 * mm
    if signature_png:
        try:
            img = ImageReader(io.BytesIO(signature_png))
            c.drawImage(
                img, _MARGIN, sig_y, width=45 * mm, height=20 * mm,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass  # a corrupt/undecodable signature image must never block issuing the document
    sig_y -= 3 * mm
    c.setLineWidth(0.3)
    c.line(_MARGIN, sig_y, _MARGIN + 60 * mm, sig_y)
    sig_y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(_MARGIN, sig_y, signer_name + (f" ({signer_role})" if signer_role else ""))
    sig_y -= 5 * mm
    c.drawString(_MARGIN, sig_y, f"Signed: {signed_at.strftime('%Y-%m-%d %H:%M')} UTC")
    if seal_code:
        sig_y -= 5 * mm
        c.drawString(_MARGIN, sig_y, f"Digital seal: {seal_code}")

    c.showPage()
    c.save()
    return buf.getvalue(), "\n".join(lines)
