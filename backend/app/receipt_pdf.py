"""One payment receipt as a PDF (A4, reportlab canvas, same approach as
document_generation.py). Input is the dict routers/payments.py::_receipt builds,
so the PDF can never show a figure the JSON receipt does not."""
from __future__ import annotations

import io
import textwrap
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

_W, _H = A4
_M = 20 * mm
_METHODS = {"online": "Online payment", "cash": "Cash", "card": "Card", "deposit": "Admission deposit"}


def rm(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}RM {abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def _when(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y %H:%M") + " UTC"
    return str(value or "-")


def render_receipt(r: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Receipt {r['receipt_no']}")
    y = _H - _M

    def room():
        nonlocal y
        if y < _M + 25 * mm:
            c.showPage()
            y = _H - _M

    def line(text, size=10, bold=False, step=6 * mm):
        nonlocal y
        room()
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(_M, y, text)
        y -= step

    def row(label, amount, bold=False):
        nonlocal y
        room()
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(_M, y, label)
        c.drawRightString(_W - _M, y, amount)
        y -= 6 * mm

    line("PAYMENT RECEIPT", 16, True, step=9 * mm)
    line(r.get("facility_name") or "", 11, True)
    line(f"Receipt no: {r['receipt_no']}")
    line(f"Date: {_when(r.get('received_at'))}")
    line(f"Patient: {r.get('patient_full_name') or '-'}")
    line(f"Method: {_METHODS.get(r['method'], r['method'])}")
    if r.get("reference_no"):
        line(f"Reference: {r['reference_no']}")
    if r.get("received_by_name"):
        line(f"Received by: {r['received_by_name']}")
    if r.get("voided"):
        line("THIS PAYMENT HAS BEEN VOIDED", 12, True)
    y -= 3 * mm
    line("Bill items", 10, True)
    for i in r["items"]:
        qty = f" x{i['quantity']}" if i["quantity"] > 1 else ""
        row(textwrap.shorten(f"{i['description']}{qty}", width=70, placeholder="..."), rm(i["amount_cents"]))
    y -= 2 * mm
    row("Bill total", rm(r["bill_total_cents"]), True)
    row("This payment", rm(r["amount_cents"]), True)
    if r.get("refunded_cents"):
        row("Refunded", rm(-r["refunded_cents"]))
    row("Balance after this payment", rm(r["bill_balance_after_cents"]))
    y -= 6 * mm
    line("Computer generated receipt. No signature required.", 8)
    c.showPage()
    c.save()
    return buf.getvalue()
