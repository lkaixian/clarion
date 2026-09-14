"""P5.1 — health/readiness probes, the request-id middleware, Prometheus
/metrics, and the structured-logging context (app/log_context.py)."""
import json
import logging

from app import log_context, main


def test_healthz_is_always_ok(test_client):
    resp = test_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_reports_all_checks_ok(test_client):
    resp = test_client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": True, "object_store": True}


def test_readyz_503s_when_a_dependency_is_down(test_client, monkeypatch):
    monkeypatch.setattr(main, "_check_object_store", lambda: False)
    resp = test_client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["checks"] == {"database": True, "object_store": False}
    # never leaks an exception string -- only booleans
    assert all(isinstance(v, bool) for v in body["checks"].values())


def test_readyz_503s_on_a_database_failure(test_client, monkeypatch):
    monkeypatch.setattr(main, "_check_database", lambda: False)
    resp = test_client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] is False


def test_request_id_header_present_and_unique(test_client):
    first = test_client.get("/healthz")
    second = test_client.get("/healthz")
    assert "x-request-id" in first.headers
    assert len(first.headers["x-request-id"]) == 12  # uuid4().hex[:12]
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_metrics_endpoint_exposes_prometheus_format(test_client):
    resp = test_client.get("/metrics")
    assert resp.status_code == 200
    assert b"# HELP" in resp.content


def test_request_id_propagates_into_the_dependency_resolution_task(
    test_client, make_user, auth_headers, monkeypatch,
):
    """Regression guard for a real historical bug class: older Starlette
    releases (pre-0.36) ran BaseHTTPMiddleware's call_next downstream app in
    a separate anyio task without correctly propagating contextvars into
    it -- which would have broken exactly this. request_id is bound in the
    OUTER _request_id_middleware, BEFORE call_next runs; auth.py's
    _resolve_current_user (which calls log_context.bind_user) executes
    INSIDE call_next's downstream chain (FastAPI's dependency resolution),
    not in the middleware itself. requirements.txt pins starlette==1.6.0,
    well past that fix -- this proves it with a real authenticated request
    rather than trusting the pin (voltagent review, 2026-09-15)."""
    seen = {}
    real_bind_user = log_context.bind_user

    def spy(*args, **kwargs):
        seen["request_id_at_bind_user"] = log_context.current_request_id()
        return real_bind_user(*args, **kwargs)

    monkeypatch.setattr(log_context, "bind_user", spy)

    clinician = make_user(role="clinician", facility="Facility A")
    resp = test_client.get("/auth/me", headers=auth_headers(clinician))
    assert resp.status_code == 200
    assert seen["request_id_at_bind_user"] == resp.headers["x-request-id"]


def test_metrics_and_health_routes_hidden_from_the_openapi_schema(test_client):
    schema = test_client.get("/openapi.json").json()
    assert "/metrics" not in schema["paths"]
    assert "/healthz" not in schema["paths"]
    assert "/readyz" not in schema["paths"]


# --------------------------------------------------------------------------
# app/log_context.py -- unit level, no HTTP
# --------------------------------------------------------------------------
def test_bind_and_read_request_id():
    rid = log_context.new_request_id()
    log_context.bind_request(rid)
    assert log_context.current_request_id() == rid


def test_context_filter_stamps_defaults_outside_a_request():
    # A fresh contextvar default ("-") outside any bind_request/bind_user call.
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    log_context.ContextFilter().filter(record)
    assert record.request_id and record.user_id and record.role and record.facility


def test_context_filter_reflects_bound_values():
    log_context.bind_request("abc123")
    log_context.bind_user("u1", "clinician", "Facility A")
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    log_context.ContextFilter().filter(record)
    assert record.request_id == "abc123"
    assert record.user_id == "u1"
    assert record.role == "clinician"
    assert record.facility == "Facility A"


def test_bind_user_with_no_facility_falls_back_to_dash():
    log_context.bind_user("u2", "admin", None)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    log_context.ContextFilter().filter(record)
    assert record.facility == "-"


def test_json_formatter_emits_valid_json_with_expected_fields():
    # JsonFormatter reads record.request_id/user_id/role/facility -- attached
    # by ContextFilter, which in the real handler chain always runs before
    # the Formatter. Run it explicitly here since this test bypasses that
    # handler pipeline.
    log_context.bind_request("req-1")
    log_context.bind_user("u3", "records_officer", "Main Hospital")
    record = logging.LogRecord("clarion.test", logging.WARNING, __file__, 42, "something happened", None, None)
    log_context.ContextFilter().filter(record)
    line = log_context.JsonFormatter().format(record)
    payload = json.loads(line)  # must be exactly one valid JSON object
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "clarion.test"
    assert payload["msg"] == "something happened"
    assert payload["request_id"] == "req-1"
    assert payload["user_id"] == "u3"
    assert payload["role"] == "records_officer"
    assert payload["facility"] == "Main Hospital"


def test_json_formatter_includes_exc_info_when_present():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "clarion.test", logging.ERROR, __file__, 1, "failed", None, __import__("sys").exc_info(),
        )
    log_context.ContextFilter().filter(record)
    payload = json.loads(log_context.JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_json_formatter_never_crashes_on_a_non_json_native_arg():
    """A stray %-arg (e.g. a UUID/Decimal someone logs) must fall back to
    str(), never raise mid-request and take the whole response down with it."""
    import uuid as _uuid

    record = logging.LogRecord(
        "clarion.test", logging.INFO, __file__, 1, "id=%s", (_uuid.uuid4(),), None,
    )
    log_context.ContextFilter().filter(record)
    line = log_context.JsonFormatter().format(record)
    json.loads(line)  # does not raise
