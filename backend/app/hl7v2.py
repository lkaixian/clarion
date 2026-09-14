"""P4.8: the
lab-analyser integration protocol -- HL7 v2.5.1 pipe/hat encoding over
MLLP, the actual real-world standard for "1-2 modern analysers"
(healthcare/Integration Engine and LDAP.md's own scoping call; a full
multi-vendor integration engine is out of scope), not the tender's generic
"REST/JSON" line, which describes this app's OWN API, not what
lab instruments speak on the wire.

Deliberately hand-rolled rather than a third-party HL7 library: this app
is BOTH the message producer (order push, ORM^O01, fields it fully
controls) and consumer (result parse, ORU^R01, arbitrary incoming text) of
exactly two message types, a few dozen fields total -- the standard escape/
separator rules below are the whole spec surface this needs, and owning
them means no dependency whose parsing quirks this codebase would have to
reverse-engineer anyway to interoperate with a real analyser later.

No real analyser to test against in this environment -- verified against
hand-crafted HL7 v2 messages (see test_hl7v2.py), including a round-trip
through this module's own builder into its own parser, and manually
checked against the HL7 v2.5.1 spec's own worked examples for escaping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import List, Optional

_FIELD_SEP = "|"
_COMPONENT_SEP = "^"
_ENCODING_CHARS = "^~\\&"  # MSH-2: component, repetition, escape, sub-component
_SEGMENT_SEP = "\r"

_ABNORMAL_FLAGS = {"H", "HH", "L", "LL", "A", "AA", "HU", "LU"}  # HL7 Table 0078, the common subset

# Sequential whole-string str.replace calls are WRONG here: escaping a lone
# "\" first (-> "\E\") can then collide with a later replace's own pattern
# (e.g. a raw "\F\" in the input encodes to "\E\F\E\", and a naive
# sequential unescape matches an ACCIDENTAL "\E\" spanning the boundary
# between the introduced escape and the literal "F", corrupting the
# round-trip). `re.sub` doesn't have this problem: it scans the ORIGINAL
# string once, left to right, and never re-examines text it already
# substituted -- the standard correct way to implement a reversible
# escaping scheme. Found by voltagent review, 2026-09-14, with a
# hand-verified failing case before this fix existed.
_ESCAPE_MAP = {"\\": "\\E\\", "|": "\\F\\", "^": "\\S\\", "~": "\\R\\", "&": "\\T\\"}
_ESCAPE_RE = re.compile("[" + re.escape("".join(_ESCAPE_MAP)) + "]")
_UNESCAPE_MAP = {"F": "|", "S": "^", "R": "~", "T": "&", "E": "\\"}
_UNESCAPE_RE = re.compile(r"\\([FSRTE])\\")


def _escape(value: Optional[str]) -> str:
    """Escapes OUR OWN field values before embedding them in a message we
    build -- the standard HL7 v2 escape sequences (2.7 "Use of escape
    sequences in text fields")."""
    if not value:
        return ""
    out = _ESCAPE_RE.sub(lambda m: _ESCAPE_MAP[m.group(0)], str(value))
    return out.replace("\r", "").replace("\n", " ")  # a segment separator can never appear inside a field


def _unescape(value: Optional[str]) -> str:
    """Inverse of `_escape`."""
    if not value:
        return ""
    return _UNESCAPE_RE.sub(lambda m: _UNESCAPE_MAP[m.group(1)], value)


def _seg(*fields: str) -> str:
    return _FIELD_SEP.join(fields)


def _comp(*parts: str) -> str:
    return _COMPONENT_SEP.join(parts)


# ---------------------------------------------------------------------------
# Outbound: ORM^O01 (order) -- "push patient demographics + test
# orders to the lab device"
# ---------------------------------------------------------------------------

def build_orm_o01(
    *, control_id: str, placer_order_number: str,
    patient_id: str, patient_name: str, date_of_birth: Optional[str], sex: Optional[str],
    test_code: Optional[str], test_name: str, code_system: Optional[str],
    ordering_provider: Optional[str], sending_facility: str, receiving_facility: str,
    now: Optional[datetime] = None,
) -> str:
    """MSH+PID+ORC+OBR, the minimum set a receiving analyser needs to
    accession a specimen against a known order. `placer_order_number` is
    this app's own ServiceRequest.id -- the SAME id the analyser is
    expected to echo back in its ORU^R01 result (OBR-2), which is how
    `parse_oru_r01`'s caller matches a result to its originating order
    without a second numbering scheme to keep in sync."""
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M%S")
    dob = (date_of_birth or "").replace("-", "")
    sex_code = {"male": "M", "female": "F"}.get((sex or "").strip().lower(), "U")

    msh = _seg("MSH", _ENCODING_CHARS, "CLARION", _escape(sending_facility),
               "ANALYSER", _escape(receiving_facility), ts, "", "ORM^O01", control_id, "P", "2.5.1")
    # PID-5 (name) has no given/family split in this app's data model (one
    # free-text full_name) -- the whole name goes in the family-name
    # component, a common simplification for a full-name-only source system.
    pid = _seg("PID", "1", "", _escape(patient_id), "", _comp(_escape(patient_name), ""), "", dob, sex_code)
    orc = _seg("ORC", "NW", _escape(placer_order_number), "", "", "", "", "", "", "", "",
               _escape(ordering_provider or ""))
    obr = _seg("OBR", "1", _escape(placer_order_number), "",
                _comp(_escape(test_code or ""), _escape(test_name), _escape(code_system or "")),
                "", "", ts)
    return _SEGMENT_SEP.join([msh, pid, orc, obr]) + _SEGMENT_SEP


# ---------------------------------------------------------------------------
# Inbound: ORU^R01 (result) -- "lab device returns results
# automatically"
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    code: str
    text: str
    value: str
    units: str = ""
    reference_range: str = ""
    abnormal_flag: Optional[str] = None

    @property
    def is_abnormal(self) -> bool:
        return bool(self.abnormal_flag) and self.abnormal_flag.upper() in _ABNORMAL_FLAGS


@dataclass
class OruResult:
    control_id: str
    sending_facility: str
    placer_order_number: Optional[str]  # OBR-2 -- matches build_orm_o01's placer_order_number
    patient_id: Optional[str]           # PID-3, if the analyser echoes it back
    observations: List[Observation] = dc_field(default_factory=list)

    @property
    def any_abnormal(self) -> bool:
        return any(o.is_abnormal for o in self.observations)


class Hl7ParseError(Exception):
    """Malformed message -- not a well-formed MSH+segments structure, or
    not an ORU^R01. The caller (the MLLP listener) turns this into an
    HL7 negative-ACK (AR) rather than crashing the connection."""


def _split_segments(raw: str) -> List[List[str]]:
    segments = []
    for line in raw.replace("\r\n", "\r").replace("\n", "\r").split("\r"):
        line = line.strip("\x0b\x1c\x00")  # tolerate a caller that didn't fully strip MLLP framing
        if not line:
            continue
        segments.append(line.split(_FIELD_SEP))
    return segments


def parse_oru_r01(raw: str) -> OruResult:
    """Parses MSH+[PID]+[ORC]+OBR+OBX* into an `OruResult`. Lenient about
    segment order/repetition (a real analyser's exact segment set varies)
    but requires at least one MSH and one OBR -- anything less isn't a
    result CLARION can act on."""
    segments = _split_segments(raw)
    by_id = {}
    for parts in segments:
        by_id.setdefault(parts[0], []).append(parts)

    msh_rows = by_id.get("MSH")
    if not msh_rows:
        raise Hl7ParseError("no MSH segment")
    msh = msh_rows[0]
    # MSH is the one segment where field N is at list index N (not N+1) --
    # MSH-1 (the field separator) is the delimiter itself, already consumed
    # by str.split, so MSH-2 (encoding chars) really is msh[1].
    message_type = msh[8] if len(msh) > 8 else ""
    if not message_type.startswith("ORU"):
        raise Hl7ParseError(f"not an ORU message: MSH-9={message_type!r}")
    control_id = msh[9] if len(msh) > 9 else ""
    sending_facility = _unescape(msh[3]) if len(msh) > 3 else ""

    obr_rows = by_id.get("OBR")
    if not obr_rows:
        raise Hl7ParseError("no OBR segment")
    obr = obr_rows[0]
    placer_order_number = _unescape(obr[2]) if len(obr) > 2 and obr[2] else None

    pid_rows = by_id.get("PID")
    patient_id = _unescape(pid_rows[0][3]) if pid_rows and len(pid_rows[0]) > 3 and pid_rows[0][3] else None

    observations: List[Observation] = []
    for obx in by_id.get("OBX", []):
        # OBX-3 Observation Identifier (code^text^system), OBX-5 Value,
        # OBX-6 Units, OBX-7 Reference Range, OBX-8 Abnormal Flags.
        ident = obx[3].split(_COMPONENT_SEP) if len(obx) > 3 and obx[3] else [""]
        code = _unescape(ident[0])
        text = _unescape(ident[1]) if len(ident) > 1 else code
        value = _unescape(obx[5]) if len(obx) > 5 else ""
        units = _unescape(obx[6]) if len(obx) > 6 else ""
        ref_range = _unescape(obx[7]) if len(obx) > 7 else ""
        flag = _unescape(obx[8]) if len(obx) > 8 and obx[8] else None
        observations.append(Observation(
            code=code, text=text, value=value, units=units,
            reference_range=ref_range, abnormal_flag=flag,
        ))

    return OruResult(
        control_id=control_id, sending_facility=sending_facility,
        placer_order_number=placer_order_number, patient_id=patient_id,
        observations=observations,
    )


def format_observations(observations: List[Observation]) -> str:
    """One plain-text line per observation -- what ends up in a staged
    AnalyserResultInbox row / the pre-fill a clinician reviews before
    signing off, not a clinical interpretation of any kind."""
    lines = []
    for o in observations:
        line = f"{o.text}: {o.value}"
        if o.units:
            line += f" {o.units}"
        if o.reference_range:
            line += f" (ref {o.reference_range})"
        if o.is_abnormal:
            line += f" [{o.abnormal_flag}]"
        lines.append(line)
    return "\n".join(lines)


def build_ack(control_id: str, *, accept: bool, sending_facility: str, text: str = "") -> str:
    """MSA-1 AA (accept) or AR (reject) -- MLLP's own handshake, required
    for a well-behaved analyser to consider the message delivered.
    `control_id` is attacker-controlled (echoed from the inbound message's
    own MSH-10) -- escaped like every other field built from external
    input, so a raw `|` in it can't corrupt this message's own structure."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_control_id = _escape(control_id)
    msh = _seg("MSH", _ENCODING_CHARS, "CLARION", _escape(sending_facility),
               "ANALYSER", "", now, "", "ACK", f"ACK{safe_control_id}", "P", "2.5.1")
    msa = _seg("MSA", "AA" if accept else "AR", safe_control_id, _escape(text))
    return _SEGMENT_SEP.join([msh, msa]) + _SEGMENT_SEP


# ---------------------------------------------------------------------------
# MLLP framing (Minimal Lower Layer Protocol) -- the TCP wire format every
# real HL7 v2 interface (this app's listener included) uses.
# ---------------------------------------------------------------------------

_MLLP_START = b"\x0b"
_MLLP_END = b"\x1c\x0d"


def wrap_mllp(message: str) -> bytes:
    return _MLLP_START + message.encode("utf-8") + _MLLP_END


def unwrap_mllp(buf: bytes) -> Optional[str]:
    """Strips MLLP framing off the FIRST complete message in `buf`; `None`
    if `buf` doesn't contain a complete frame yet (the caller keeps
    reading more bytes). Ignores anything before the first start-block --
    a stray byte on a freshly-opened socket is not this module's problem."""
    start = buf.find(_MLLP_START)
    if start == -1:
        return None
    end = buf.find(_MLLP_END, start)
    if end == -1:
        return None
    return buf[start + 1:end].decode("utf-8", errors="replace")
