"""routers/ancillary.py's P4.8 additions: the analyser-inbox list/discard
endpoints (RBAC + facility scoping) and the best-effort HL7 order push
wired into POST /ancillary/requests.
"""
import socket
import threading

from app import hl7v2, models
from conftest import _facility, _make_patient
from test_ancillary import _make_catalog_item, _order_body
from test_hl7_listener import _service_request


def _inbox_row(db_session, service_request_id, **overrides):
    row = models.AnalyserResultInbox(
        service_request_id=service_request_id,
        result_text=overrides.pop("result_text", "Glucose: 5.6 mmol/L"),
        flag_abnormal=overrides.pop("flag_abnormal", False),
        raw_message=overrides.pop("raw_message", "MSH|..."),
        **overrides,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_list_analyser_inbox_rbac(test_client, make_user, auth_headers):
    facility = _facility("InboxRbac")
    receptionist = make_user(role="receptionist", facility=facility)
    clinician = make_user(role="clinician", facility=facility)

    assert test_client.get("/ancillary/analyser-inbox", headers=auth_headers(receptionist)).status_code == 403
    assert test_client.get("/ancillary/analyser-inbox", headers=auth_headers(clinician)).status_code == 200


def test_list_analyser_inbox_is_facility_scoped(test_client, make_user, auth_headers, db_session):
    fac_a, fac_b = _facility("InboxA"), _facility("InboxB")
    patient = _make_patient(db_session)
    req_a = _service_request(db_session, patient.id, fac_a)
    req_b = _service_request(db_session, patient.id, fac_b)
    row_a = _inbox_row(db_session, req_a.id)
    _inbox_row(db_session, req_b.id)

    clinician_a = make_user(role="clinician", facility=fac_a)
    resp = test_client.get("/ancillary/analyser-inbox", headers=auth_headers(clinician_a))
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert ids == {row_a.id}


def test_list_analyser_inbox_excludes_unmatched_rows(test_client, make_user, auth_headers, db_session):
    facility = _facility("InboxUnmatched")
    _inbox_row(db_session, None)  # unmatched -- never exposed, see models.AnalyserResultInbox docstring
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.get("/ancillary/analyser-inbox", headers=auth_headers(clinician))
    assert resp.status_code == 200 and resp.json() == []


def test_discard_analyser_inbox_happy_path_and_double_discard(test_client, make_user, auth_headers, db_session):
    facility = _facility("InboxDiscard")
    patient = _make_patient(db_session)
    req = _service_request(db_session, patient.id, facility)
    row = _inbox_row(db_session, req.id)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        f"/ancillary/analyser-inbox/{row.id}/discard", json={"reason": "duplicate resend"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200

    listed = test_client.get("/ancillary/analyser-inbox", headers=auth_headers(clinician)).json()
    assert row.id not in {r["id"] for r in listed}

    again = test_client.post(
        f"/ancillary/analyser-inbox/{row.id}/discard", json={}, headers=auth_headers(clinician),
    )
    assert again.status_code == 400


def test_discard_analyser_inbox_denied_for_other_facility(test_client, make_user, auth_headers, db_session):
    fac_a, fac_b = _facility("InboxDiscA"), _facility("InboxDiscB")
    patient = _make_patient(db_session)
    req = _service_request(db_session, patient.id, fac_a)
    row = _inbox_row(db_session, req.id)
    clinician_b = make_user(role="clinician", facility=fac_b)

    resp = test_client.post(
        f"/ancillary/analyser-inbox/{row.id}/discard", json={}, headers=auth_headers(clinician_b),
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# Outbound push wired into order creation
# --------------------------------------------------------------------------

def test_create_lab_request_pushes_hl7_order_when_analyser_configured(
    test_client, make_user, auth_headers, db_session, monkeypatch,
):
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
        conn.sendall(hl7v2.wrap_mllp(hl7v2.build_ack("x", accept=True, sending_facility="Lab")))
        conn.close()

    t = threading.Thread(target=_fake_analyser, daemon=True)
    t.start()
    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_PORT", str(port))
    monkeypatch.setenv("CLARION_HL7_ANALYSER_TIMEOUT", "5")

    facility = _facility("PushLab")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, module="laboratory", code="2345-7", code_system="LOINC")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician),
    )
    assert resp.status_code == 201
    req_id = resp.json()["id"]
    t.join(timeout=2)
    server.close()

    assert req_id in received.get("message", "")
    assert "ORM^O01" in received["message"]


def test_create_lab_request_never_fails_when_analyser_unreachable(
    test_client, make_user, auth_headers, db_session, monkeypatch,
):
    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_PORT", "1")  # nothing listens on port 1
    monkeypatch.setenv("CLARION_HL7_ANALYSER_TIMEOUT", "1")

    facility = _facility("PushLabFail")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, module="laboratory")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id), headers=auth_headers(clinician),
    )
    assert resp.status_code == 201  # the order itself must never fail because the analyser push did


def test_create_non_lab_request_does_not_push(test_client, make_user, auth_headers, db_session, monkeypatch):
    """No listener at all -- if create_service_request ever tried to push
    for a non-laboratory module, this would hang/raise inside the request;
    it must not attempt it."""
    monkeypatch.setenv("CLARION_HL7_ANALYSER_HOST", "127.0.0.1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_PORT", "1")
    monkeypatch.setenv("CLARION_HL7_ANALYSER_TIMEOUT", "1")

    facility = _facility("PushNonLab")
    patient = _make_patient(db_session)
    item = _make_catalog_item(db_session, module="physiotherapy")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/ancillary/requests", json=_order_body(patient.id, item.id, module="physiotherapy"),
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 201
