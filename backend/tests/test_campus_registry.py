"""P5.x demo mock: SMP/SMS/e-klinik-panel/Registrar eligibility check
See app/campus_registry.py's module docstring for why
this is a mock, not a real campus integration.

Three layers, each tested at the level that's actually meaningful:
  1. The mock registry's own data/404 behaviour (routers/campus_registry_mock.py)
  2. The adapter's HTTP handling incl. graceful-degradation paths
     (app/campus_registry.py) -- exercised in-process via httpx's ASGITransport
     (no real socket needed) since this repo has no async-test plugin and
     TestClient itself doesn't bind a real port an httpx client could reach.
  3. The authenticated CLARION endpoint (GET /patients/campus-eligibility/{nric})
     via the normal TestClient, same as every other router test here.
"""
import asyncio

import httpx

from app.main import app
from app.campus_registry import check_eligibility


def test_mock_registry_known_nric_returns_flagged_mock_record():
    from app.routers.campus_registry_mock import mock_eligibility

    result = mock_eligibility("000101-01-0001")
    assert result["mock"] is True
    assert result["eligible"] is True
    assert result["source"] == "SMP"
    assert result["full_name"] == "Ahmad bin Ismail (mock)"


def test_mock_registry_dash_and_case_insensitive():
    from app.routers.campus_registry_mock import mock_eligibility

    dashed = mock_eligibility("000101-01-0001")
    bare = mock_eligibility("000101010001")
    assert dashed == bare


def test_mock_registry_unknown_nric_404s():
    from fastapi import HTTPException

    from app.routers.campus_registry_mock import mock_eligibility

    try:
        mock_eligibility("010101-01-9999")
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


def _run_against_app(coro):
    """Route check_eligibility's internal httpx.AsyncClient through the real
    FastAPI app in-process (ASGITransport) instead of a real socket."""
    return asyncio.run(coro)


def test_adapter_success_path(monkeypatch):
    class _ASGIClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.ASGITransport(app=app)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.campus_registry.httpx.AsyncClient", _ASGIClient)

    result = _run_against_app(
        check_eligibility("990202-02-0002", base_url="http://testserver/mock-campus-registry")
    )
    assert result["available"] is True
    assert result["eligible"] is True
    assert result["source"] == "SMS"
    assert result["mock"] is True


def test_adapter_not_found_path(monkeypatch):
    class _ASGIClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.ASGITransport(app=app)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.campus_registry.httpx.AsyncClient", _ASGIClient)

    result = _run_against_app(
        check_eligibility("010101-01-9999", base_url="http://testserver/mock-campus-registry")
    )
    assert result == {
        "available": True, "eligible": False, "source": None,
        "detail": "Not found in the University registry",
    }


def test_adapter_never_raises_on_unreachable_registry():
    """The whole point: a down/misconfigured registry is advisory-fail, not
    a 500 -- real network call to a closed port, no mocking."""
    result = _run_against_app(
        check_eligibility("000101-01-0001", base_url="http://127.0.0.1:1", timeout=1.0)
    )
    assert result["available"] is False
    assert result["eligible"] is None
    assert "detail" in result


def test_adapter_never_raises_on_a_control_character_in_nric(monkeypatch):
    """Code review 2026-09-15: a raw tab/newline in `nric` used to raise
    httpx.InvalidURL uncaught (not an httpx.HTTPError subclass), a real 500
    that broke this function's own "never raises" contract. Reproduces the
    exact finding against the real ASGI app, not a mock."""
    class _ASGIClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.ASGITransport(app=app)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.campus_registry.httpx.AsyncClient", _ASGIClient)

    result = _run_against_app(
        check_eligibility("12\t0934", base_url="http://testserver/mock-campus-registry")
    )
    # Not found (the mock has no such record) rather than a raised exception.
    assert result["available"] is True
    assert result["eligible"] is False


def test_endpoint_requires_patients_page_access(test_client, make_user, auth_headers):
    pharmacist = make_user(role="pharmacist")  # no `patients` page by default
    resp = test_client.get(
        "/patients/campus-eligibility/000101-01-0001", headers=auth_headers(pharmacist)
    )
    assert resp.status_code == 403


def test_endpoint_degrades_gracefully_when_registry_unreachable(test_client, make_user, auth_headers):
    """No CAMPUS_REGISTRY_BASE_URL override reachable from inside the test
    process -- confirms the real endpoint returns 200 with available=False
    rather than a 500, i.e. this never blocks the New Patient flow."""
    records_officer = make_user(role="records_officer")
    resp = test_client.get(
        "/patients/campus-eligibility/000101-01-0001", headers=auth_headers(records_officer)
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is False
