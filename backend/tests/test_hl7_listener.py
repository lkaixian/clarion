"""app/hl7_listener.py: HL7 result ingestion -- matching, staging,
unmatched/wrong-module handling, and the actual MLLP socket loop.
"""
import socket
import threading
import time

from app import hl7v2, hl7_listener, models
from conftest import _facility, _make_patient
from test_ancillary import _make_catalog_item


def _service_request(db_session, patient_id, facility, module="laboratory", **overrides):
    item = _make_catalog_item(db_session, module=module)
    req = models.ServiceRequest(
        patient_id=patient_id, module=module, catalog_item_id=item.id, source="frontdesk",
        ordering_facility_name=facility, **overrides,
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)
    return req


def _oru(placer_order_number, control_id="ctrl-1", flag="N"):
    return (
        "MSH|^~\\&|ANALYSER|Lab A|CLARION|Hospital A|20260914120000||ORU^R01|" + control_id + "|P|2.5.1\r"
        "PID|1||pat-1||Ahmad Bin Ali||19900501|M\r"
        "OBR|1|" + placer_order_number + "||2345-7^Glucose^LOINC|||20260914120500\r"
        "OBX|1|NM|2345-7^Glucose^LOINC||5.6|mmol/L|3.9-5.5|" + flag + "|||F\r"
    )


# --------------------------------------------------------------------------
# handle_message -- pure DB logic, no socket
# --------------------------------------------------------------------------

def test_handle_message_matches_a_real_lab_request(db_session):
    facility = _facility("Hl7A")
    patient = _make_patient(db_session)
    req = _service_request(db_session, patient.id, facility, module="laboratory")

    ack, row = hl7_listener.handle_message(db_session, _oru(req.id, flag="H"))
    assert "MSA|AA" in ack
    assert row is not None
    assert row.service_request_id == req.id
    assert row.flag_abnormal is True
    assert "Glucose: 5.6 mmol/L (ref 3.9-5.5) [H]" in row.result_text
    assert row.facility_name == facility  # voltagent review: was left NULL despite the column/index existing


def test_handle_message_stages_unmatched_result_for_unknown_order(db_session):
    ack, row = hl7_listener.handle_message(db_session, _oru("no-such-request-id"))
    assert "MSA|AA" in ack  # still accepted -- CLARION did receive and store it
    assert row is not None
    assert row.service_request_id is None


def test_handle_message_does_not_match_a_non_laboratory_request(db_session):
    facility = _facility("Hl7B")
    patient = _make_patient(db_session)
    req = _service_request(db_session, patient.id, facility, module="physiotherapy")

    ack, row = hl7_listener.handle_message(db_session, _oru(req.id))
    assert "MSA|AA" in ack
    assert row is not None
    assert row.service_request_id is None  # wrong module -- treated as unmatched, not cross-linked


def test_handle_message_rejects_unparseable_message(db_session):
    ack, row = hl7_listener.handle_message(db_session, "not an HL7 message at all")
    assert "MSA|AR" in ack
    assert row is None


# --------------------------------------------------------------------------
# serve() -- the actual MLLP socket loop, real TCP
# --------------------------------------------------------------------------

def test_serve_over_real_socket_round_trip(db_session, request):
    facility = _facility("Hl7Socket")
    patient = _make_patient(db_session)
    req = _service_request(db_session, patient.id, facility, module="laboratory")
    # Captured as a plain string BEFORE the background thread touches the
    # shared db_session (its own commit() expires every tracked object) --
    # every reference below is by this id, never by re-touching `req`
    # itself, which would otherwise raise DetachedInstanceError.
    req_id = req.id

    listener_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener_sock.bind(("127.0.0.1", 0))
    port = listener_sock.getsockname()[1]
    listener_sock.listen(1)

    def session_factory():
        return db_session  # share the test's own session -- fine, single-threaded test client below

    def _accept_one():
        conn, addr = listener_sock.accept()
        hl7_listener._handle_connection(conn, addr, session_factory, threading.Semaphore(1))

    t = threading.Thread(target=_accept_one, daemon=True)
    t.start()
    time.sleep(0.05)  # let the accept() call actually start listening

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(hl7v2.wrap_mllp(_oru(req_id)))
    client.settimeout(5)
    raw_ack = client.recv(65536)
    client.close()
    listener_sock.close()
    t.join(timeout=2)

    ack = hl7v2.unwrap_mllp(raw_ack)
    assert ack is not None and "MSA|AA" in ack

    row = (
        db_session.query(models.AnalyserResultInbox)
        .filter(models.AnalyserResultInbox.service_request_id == req_id)
        .first()
    )
    assert row is not None


# --------------------------------------------------------------------------
# Hardening (voltagent review, 2026-09-14): idle-connection timeout +
# concurrency-slot release, so a connection that never sends a complete
# frame can't tie up a thread (or a connection slot) forever.
# --------------------------------------------------------------------------

def test_handle_connection_closes_an_idle_connection_after_its_timeout(monkeypatch):
    monkeypatch.setattr(hl7_listener, "_CONN_TIMEOUT", 0.2)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    conn, addr = server.accept()

    slot = threading.Semaphore(1)
    slot.acquire()  # mirrors serve()'s own accept loop: acquire before handing off, release on close
    start = time.monotonic()
    hl7_listener._handle_connection(conn, addr, lambda: None, slot)  # never sends anything
    elapsed = time.monotonic() - start

    assert elapsed < 2.0  # bounded by _CONN_TIMEOUT, not hung forever
    assert slot._value == 1  # released back, not leaked
    client.close()
    server.close()
