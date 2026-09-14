"""app/hl7v2.py: HL7 v2 encode/decode (escape sequences, ORM^O01 build,
ORU^R01 parse, MLLP framing) -- pure protocol logic, no DB/network.
"""
import pytest

from app import hl7v2


def test_escape_unescape_round_trips_the_special_characters():
    raw = "A|B^C~D&E\\F"
    escaped = hl7v2._escape(raw)
    assert "|" not in escaped and "^" not in escaped and "~" not in escaped and "&" not in escaped
    assert hl7v2._unescape(escaped) == raw


@pytest.mark.parametrize("raw", [
    "\\F\\",   # voltagent review, 2026-09-14: this exact input broke the
    "\\S\\",   # old sequential-str.replace implementation -- escaping it
    "\\R\\",   # produces "\E\<letter>\E\", which a naive unescape pass
    "\\T\\",   # matches an ACCIDENTAL "\E\...\E\" spanning the boundary
    "\\E\\",   # between the introduced escape and the literal letter,
    "a\\F\\b", # corrupting the round-trip. Every one of these must survive
    "\\\\",    # escape() -> unescape() unchanged.
])
def test_escape_unescape_round_trips_values_shaped_like_escape_sequences(raw):
    assert hl7v2._unescape(hl7v2._escape(raw)) == raw


def test_escape_handles_empty_and_none():
    assert hl7v2._escape(None) == ""
    assert hl7v2._escape("") == ""
    assert hl7v2._unescape(None) == ""


def test_build_orm_o01_shape():
    msg = hl7v2.build_orm_o01(
        control_id="ctrl-1", placer_order_number="req-123",
        patient_id="pat-1", patient_name="Ahmad Bin Ali", date_of_birth="1990-05-01",
        sex="male", test_code="2345-7", test_name="Glucose", code_system="LOINC",
        ordering_provider="Dr Tan", sending_facility="Hospital A", receiving_facility="Lab A",
        now=None,
    )
    segments = {line.split("|")[0]: line for line in msg.strip("\r").split("\r")}
    assert set(segments) == {"MSH", "PID", "ORC", "OBR"}
    assert segments["MSH"].startswith("MSH|^~\\&|CLARION|Hospital A|ANALYSER|Lab A|")
    assert "ORM^O01" in segments["MSH"]
    assert "req-123" in segments["ORC"]
    assert "req-123" in segments["OBR"]
    assert "2345-7^Glucose^LOINC" in segments["OBR"]
    assert "19900501" in segments["PID"]  # DOB, dashes stripped
    assert "M" in segments["PID"].split("|")


def test_build_orm_o01_escapes_a_pipe_in_the_patient_name():
    msg = hl7v2.build_orm_o01(
        control_id="c", placer_order_number="req-1", patient_id="p1",
        patient_name="A|B", date_of_birth=None, sex=None, test_code=None,
        test_name="X", code_system=None, ordering_provider=None,
        sending_facility="F", receiving_facility="Lab",
    )
    pid_line = next(s for s in msg.split("\r") if s.startswith("PID"))
    fields = pid_line.split("|")
    assert len(fields) == 9  # a raw "|" in the name would have split PID into an extra field
    assert "\\F\\" in pid_line


def test_parse_oru_r01_basic():
    raw = (
        "MSH|^~\\&|ANALYSER|Lab A|CLARION|Hospital A|20260914120000||ORU^R01|ctrl-9|P|2.5.1\r"
        "PID|1||pat-1||Ahmad Bin Ali||19900501|M\r"
        "OBR|1|req-123||2345-7^Glucose^LOINC|||20260914120500\r"
        "OBX|1|NM|2345-7^Glucose^LOINC||5.6|mmol/L|3.9-5.5|H|||F\r"
        "OBX|2|NM|718-7^Haemoglobin^LOINC||13.2|g/dL|13.0-17.0|N|||F\r"
    )
    result = hl7v2.parse_oru_r01(raw)
    assert result.control_id == "ctrl-9"
    assert result.placer_order_number == "req-123"
    assert result.patient_id == "pat-1"
    assert len(result.observations) == 2
    glucose = result.observations[0]
    assert glucose.code == "2345-7" and glucose.text == "Glucose" and glucose.value == "5.6"
    assert glucose.units == "mmol/L" and glucose.reference_range == "3.9-5.5"
    assert glucose.is_abnormal is True
    assert result.observations[1].is_abnormal is False
    assert result.any_abnormal is True


def test_parse_oru_r01_rejects_non_oru_message():
    raw = "MSH|^~\\&|A|B|C|D|20260914120000||ORM^O01|c1|P|2.5.1\rOBR|1|req-1\r"
    with pytest.raises(hl7v2.Hl7ParseError):
        hl7v2.parse_oru_r01(raw)


def test_parse_oru_r01_requires_obr():
    raw = "MSH|^~\\&|A|B|C|D|20260914120000||ORU^R01|c1|P|2.5.1\rPID|1||pat-1\r"
    with pytest.raises(hl7v2.Hl7ParseError):
        hl7v2.parse_oru_r01(raw)


def test_format_observations_flags_abnormal():
    obs = [hl7v2.Observation(code="x", text="Glucose", value="5.6", units="mmol/L",
                              reference_range="3.9-5.5", abnormal_flag="H")]
    text = hl7v2.format_observations(obs)
    assert "Glucose: 5.6 mmol/L (ref 3.9-5.5) [H]" == text


def test_mllp_round_trip():
    msg = "MSH|^~\\&|A|B|C|D|20260914120000||ORU^R01|c1|P|2.5.1\r"
    framed = hl7v2.wrap_mllp(msg)
    assert framed[:1] == b"\x0b" and framed[-2:] == b"\x1c\x0d"
    assert hl7v2.unwrap_mllp(framed) == msg


def test_mllp_unwrap_incomplete_frame_returns_none():
    assert hl7v2.unwrap_mllp(b"\x0bMSH|^~\\&|partial") is None
    assert hl7v2.unwrap_mllp(b"no framing at all") is None


def test_build_ack_shape():
    ack = hl7v2.build_ack("ctrl-9", accept=True, sending_facility="Hospital A")
    assert "MSA|AA|ctrl-9" in ack
    rej = hl7v2.build_ack("ctrl-9", accept=False, sending_facility="Hospital A", text="bad order#")
    assert "MSA|AR|ctrl-9|bad order#" in rej


def test_build_ack_escapes_an_attacker_controlled_control_id():
    """voltagent review, 2026-09-14: control_id is echoed straight from an
    inbound message's own MSH-10 -- a raw "|" in it used to structurally
    corrupt the ACK's own segments."""
    ack = hl7v2.build_ack("evil|MSH|injected", accept=True, sending_facility="Hospital A")
    msa_line = next(line for line in ack.split("\r") if line.startswith("MSA"))
    assert msa_line.split("|") == ["MSA", "AA", "evil\\F\\MSH\\F\\injected", ""]
