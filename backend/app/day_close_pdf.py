"""The cashier day-close as a one-page PDF, rendered from the same dict GET /billing/reconciliation
returns, so the paper can never disagree with the screen."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .receipt_pdf import rm

_W, _H = A4
_M = 20 * mm


def render_day_close(rec: dict, generated_by: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ranged = rec.get("days", 1) > 1
    c.setTitle(f"Day close {rec['from_day']} to {rec['day']}" if ranged else f"Day close {rec['day']}")
    y = _H - _M

    def room():
        nonlocal y
        if y < _M + 20 * mm:
            c.showPage()
            y = _H - _M

    def line(text, size=10, bold=False, step=6 * mm):
        nonlocal y
        room()
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(_M, y, text)
        y -= step

    def row(label, count, amount, bold=False):
        nonlocal y
        room()
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(_M, y, str(label)[:48])
        if count is not None:
            c.drawRightString(_W - _M - 45 * mm, y, str(count))
        c.drawRightString(_W - _M, y, amount)
        y -= 6 * mm

    line("CASHIER CLOSE" if ranged else "CASHIER DAY CLOSE", 16, True, step=9 * mm)
    line(rec.get("facility_name") or "", 11, True)
    tz = f"UTC{rec['tz_offset_minutes'] / 60:+g}"
    if ranged:
        line(f"Period: {rec['from_day']} to {rec['day']}  ({rec['days']} days, {tz})")
    else:
        line(f"Day: {rec['day']}   ({tz})")
    line(f"Prepared by: {generated_by}")
    y -= 4 * mm

    line("Summary", 11, True)
    row("Collected (not voided, not from deposits)", None, rm(rec["collected_cents"]))
    row("Deposits received", rec["deposits_received"]["count"], rm(rec["deposits_received"]["total_cents"]))
    row("Refunds approved", rec["refunds"]["count"], rm(-rec["refunds"]["total_cents"]))
    row("Deposit refunds", rec["deposit_refunds"]["count"], rm(-rec["deposit_refunds"]["total_cents"]))
    row("Net", None, rm(rec["net_cents"]), True)
    y -= 4 * mm

    line("By method", 11, True)
    if rec["by_method"]:
        for m, v in rec["by_method"].items():
            row(m.capitalize(), v["count"], rm(v["total_cents"]))
    else:
        line("No payments were taken on this day.")
    y -= 4 * mm

    line("By cashier", 11, True)
    for cashier in rec["by_cashier"]:
        row(cashier["name"], cashier["count"], rm(cashier["total_cents"]))
    if not rec["by_cashier"]:
        line("None.")
    y -= 4 * mm

    line("For review (not part of the net above)", 11, True)
    row("Voided payments", rec["voided"]["count"], rm(rec["voided"]["total_cents"]))
    row("Paid from deposits (not new cash)", rec["applied_from_deposits"]["count"],
        rm(rec["applied_from_deposits"]["total_cents"]))
    row("Online payments waiting for the gateway", rec["online_pending"]["count"],
        rm(rec["online_pending"]["total_cents"]))
    y -= 14 * mm
    line("Counted by: ______________________     Checked by: ______________________", 10)
    c.showPage()
    c.save()
    return buf.getvalue()
