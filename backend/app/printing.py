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


def build_sample_label_png(
    *,
    patient_name: str,
    national_id: str | None,
    item_name: str,
    request_id: str,
) -> bytes:
    """A printable sample-label image: patient name, IC, item, and a
    scannable code carrying the request id (the tender's "barcode (if
    applicable)"). Uses qrcode (already a dependency, see nric_ocr /
    reception stations QR generation) rather than adding a Code128 library
    -- a QR is scan-compatible for the same purpose and this codebase has no
    Code128 reader anywhere to justify a second barcode symbology.
    Pillow-drawn (already a dependency, see app/imaging.py), no template
    engine -- one fixed layout, same "simplest tool that draws a form" call
    app/document_generation.py made for the PDF documents."""
    img = Image.new("RGB", _LABEL_SIZE, "white")
    draw = ImageDraw.Draw(img)
    try:
        font_bold = ImageFont.truetype("arialbd.ttf", 22)
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font_bold = font = ImageFont.load_default()

    qr_img = qrcode.make(request_id).resize((200, 200))
    img.paste(qr_img, (_LABEL_SIZE[0] - 210, 30))

    y = 15
    for text, f in (
        (patient_name, font_bold),
        (f"IC/ID: {national_id or '-'}", font),
        (f"Item: {item_name}", font),
        (f"Request: {request_id[:8]}", font),
    ):
        draw.text((15, y), text, fill="black", font=f)
        y += 34

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
