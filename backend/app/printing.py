"""P3.9: calling-system hardware output -- pure, no-I/O byte/image builders,
same split as app/appointments.py (logic here, HTTP layer in the routers
that call it: routers/reception/queue.py for the ticket, routers/ancillary.py
for the lab label).

Neither function talks to an actual printer -- there is no thermal/label
printer attached in this environment to test against. Wiring the returned
bytes to a real USB/network printer (a local print-spooler agent that polls
these endpoints, or a browser extension that forwards to one) is deploy-time
hardware integration, the same "documented go-live step, not faked" call
P1.9 made for the TLS certificate pair -- see docs/deployment.md.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
import qrcode

# --- ESC/POS queue ticket -------------------------------------
_ESC = b"\x1b"
_GS = b"\x1d"

# Security review follow-up (2026-09-14, P3.9/P3.10 wave): every text field
# that reaches _escpos_line is staff/admin-supplied free text (QueueTicket.
# department, HospitalSetting.display_name, ...) with no control-character
# validation at the schema layer. `str.encode("ascii", errors="replace")`
# only substitutes NON-ascii bytes -- ASCII control bytes, including 0x1b/
# 0x1d (this module's own ESC/GS command-introducer bytes), passed straight
# through unfiltered, letting a low-privilege receptionist/admin account
# inject arbitrary ESC/POS commands (cash-drawer-open opcodes, repeated
# cut/feed paper-waste, malformed sequences that lock up the printer) into
# every ticket subsequently printed for that facility. Stripped here, the
# one place every text field funnels through, rather than re-validating at
# every call site.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _escpos_line(text: str) -> bytes:
    # Plain CP437-ish ASCII -- most thermal printers' default code page.
    # Non-ASCII characters (rare in a facility name/room label here) become
    # "?" rather than raising or mojibake-ing on the receipt.
    safe = _CONTROL_CHARS_RE.sub("", text)
    return safe.encode("ascii", errors="replace") + b"\n"


def build_ticket_escpos(
    *,
    facility_display_name: str,
    queue_number: int,
    department: str | None,
    room_name: str | None,
    checked_in_at: datetime,
) -> bytes:
    """A queue-number ticket as raw ESC/POS command bytes, ready to write
    straight to a compatible receipt printer's port. Big bold centered
    queue number (what the patient actually needs to read from across the
    waiting room), everything else small."""
    out = bytearray()
    out += _ESC + b"\x40"  # initialize
    out += _ESC + b"\x61\x01"  # center align
    out += _escpos_line(facility_display_name)
    out += _escpos_line("-" * 24)
    out += _ESC + b"\x45\x01"  # bold on
    out += _GS + b"\x21\x11"  # double width + double height
    prefix = f"{department.upper()} " if department else ""
    out += _escpos_line(f"{prefix}{queue_number}")
    out += _GS + b"\x21\x00"  # normal size
    out += _ESC + b"\x45\x00"  # bold off
    if room_name:
        out += _escpos_line(f"Room: {room_name}")
    out += _escpos_line(checked_in_at.strftime("%Y-%m-%d %H:%M"))
    out += _escpos_line("Please wait to be called")
    out += _ESC + b"\x61\x00"  # left align (restore default)
    out += _ESC + b"\x64\x04"  # feed 4 lines
    out += _GS + b"\x56\x00"  # full cut
    return bytes(out)


# --- Lab/ancillary sample label --------------------------------
_LABEL_SIZE = (560, 260)  # px at ~200dpi -- roughly a 70mm x 32mm label
_LABEL_MARGIN = 14

# per line: (font size, bold, line advance, max lines)
_NORMAL = ((32, True, 44, 1), (26, False, 38, 1), (26, False, 38, 1),
           (26, False, 38, 1), (26, False, 38, 1), (26, False, 38, 1))
_COMPACT = ((24, True, 30, 2), (21, False, 27, 1), (21, False, 27, 1),
            (21, False, 27, 2), (21, False, 27, 2), (21, False, 27, 1))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """Greedy word-wrap to at most max_lines; only the last allowed line is
    ellipsised, and only when the text genuinely doesn't fit."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] += "…"
    out = []
    for line in lines:  # also catches one over-long unbroken token
        while len(line) > 1 and draw.textlength(line, font=font) > max_w:
            line = line[:-2] + "…"
        out.append(line)
    return out


def _place(draw, texts, spec, qr_x, qr_bottom, top):
    """Lay the label lines out; returns (draw ops, every line fit unwrapped).
    Lines beside the QR get the narrow column, lines below it the full width."""
    ops, y, fits = [], top, True
    for text, (size, bold, advance, max_lines) in zip(texts, spec):
        # Pillow's built-in font scales (load_default(size=)), so no system
        # font is needed -- the Linux container has no arial.ttf.
        font = ImageFont.load_default(size=size)
        right = qr_x - 10 if y < qr_bottom else _LABEL_SIZE[0] - _LABEL_MARGIN
        max_w = right - _LABEL_MARGIN - (2 if bold else 0)
        lines = _wrap(draw, text, font, max_w, max_lines)
        fits = fits and lines == [text]
        for line in lines:
            ops.append((_LABEL_MARGIN, y, line, font, bold))
            y += advance
    return ops, fits


def build_sample_label_png(
    *,
    patient_name: str,
    national_id: str | None,
    item_name: str,
    request_id: str,
    created_at: datetime | str | None = None,
    created_by: str | None = None,
) -> bytes:
    """A printable sample-label image, top to bottom: patient name, IC/ID,
    date created, created by, item, request, plus a scannable code carrying
    the request id (the tender's "barcode (if applicable)"). Uses qrcode
    (already a dependency, see nric_ocr / reception stations QR generation)
    rather than adding a Code128 library -- a QR is scan-compatible for the
    same purpose and this codebase has no Code128 reader anywhere to justify a
    second barcode symbology. Pillow-drawn (already a dependency, see
    app/imaging.py), no template engine -- one fixed layout, same "simplest
    tool that draws a form" call app/document_generation.py made for the PDF
    documents.

    Big text first; if a name/item doesn't fit on one line the compact layout
    wraps it to a second line (and shrinks the QR) rather than cutting it --
    a truncated patient name on a specimen is a misidentification risk."""
    from .report_export import _fmt_dt  # DD-MM-YYYY HH:MM, Malaysia time

    width = _LABEL_SIZE[0]
    img = Image.new("RGB", _LABEL_SIZE, "white")
    draw = ImageDraw.Draw(img)
    texts = (
        patient_name,
        f"IC/ID: {national_id or '-'}",
        f"Created: {_fmt_dt(created_at)}",
        f"Created by: {created_by or '-'}",
        f"Item: {item_name}",
        f"Request: {request_id[:8]}",
    )

    qr_size = 160
    qr_x, qr_y = width - _LABEL_MARGIN - qr_size, _LABEL_MARGIN
    ops, fits = _place(draw, texts, _NORMAL, qr_x, qr_y + qr_size, top=10)
    if not fits:
        qr_size = 130  # still scans at 200dpi; frees the full width for lines below it
        qr_x, qr_y = width - _LABEL_MARGIN - qr_size, _LABEL_MARGIN
        ops, _ = _place(draw, texts, _COMPACT, qr_x, qr_y + qr_size, top=8)

    img.paste(qrcode.make(request_id).resize((qr_size, qr_size)), (qr_x, qr_y))
    for x, y, line, font, bold in ops:
        draw.text((x, y), line, fill="black", font=font, stroke_width=1 if bold else 0, stroke_fill="black")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
