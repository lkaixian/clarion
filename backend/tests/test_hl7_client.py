"""app/hl7_client.py: outbound MLLP push -- env-driven
enable/disable, and the actual framed bytes sent over a real socket
against a tiny fake analyser.
"""
import socket
import threading

import pytest

from app import hl7_client, hl7v2


def test_disabled_when_host_unset(monkeypatch):
    monkeypatch.delenv("CLARION_HL7_ANALYSER_HOST", raising=False)
    assert hl7_client.enabled() is False
    with pytest.raises(hl7_client.Hl7PushError):
        hl7_client.push_order("MSH|...")


def test_enabled_when_host_set(monkeypatch):
    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    assert hl7_client.enabled() is True


def test_push_order_sends_a_correctly_framed_message_and_reads_the_ack(monkeypatch):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    received = {}

    def _fake_analyser():
        conn, _addr = server.accept()
        conn.settimeout(5)
        buf = b""
        while hl7v2.unwrap_mllp(buf) is None:
            buf += conn.recv(65536)
        received["message"] = hl7v2.unwrap_mllp(buf)
        conn.sendall(hl7v2.wrap_mllp(hl7v2.build_ack("c1", accept=True, sending_facility="Lab")))
        conn.close()

    t = threading.Thread(target=_fake_analyser, daemon=True)
    t.start()

    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_PORT", str(port))
    monkeypatch.setenv("CLARION_HL7_ANALYSER_TIMEOUT", "5")

    order = hl7v2.build_orm_o01(
        control_id="c1", placer_order_number="req-1", patient_id="p1",
        patient_name="Ahmad", date_of_birth="1990-01-01", sex="male",
        test_code="2345-7", test_name="Glucose", code_system="LOINC",
        ordering_provider="Dr Tan", sending_facility="Hospital A", receiving_facility="Lab A",
    )
    hl7_client.push_order(order)
    t.join(timeout=2)
    server.close()

    assert "req-1" in received["message"]
    assert "ORM^O01" in received["message"]


def test_push_order_raises_on_connection_refused(monkeypatch):
    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_PORT", "1")  # nothing listens on port 1
    monkeypatch.setenv("CLARION_HL7_ANALYSER_TIMEOUT", "1")
    with pytest.raises(hl7_client.Hl7PushError):
        hl7_client.push_order("MSH|...")
