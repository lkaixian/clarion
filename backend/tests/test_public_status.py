"""GET /status: public, booleans + latencies only, never leaks internals."""
from app import main


def test_status_shape_and_no_leaks(test_client, monkeypatch):
    monkeypatch.setitem(main._status_cache, "body", None)
    r = test_client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body["components"]) == {"api", "database", "object_store", "cache", "local_ai"}
    assert body["components"]["database"]["status"] == "up"
    assert body["status"] in {"ok", "degraded"}
    text = r.text.lower()
    for leak in ("sqlite", "redis://", "localhost", "traceback", "secret"):
        assert leak not in text


def test_status_reports_down_dependency(test_client, monkeypatch):
    monkeypatch.setitem(main._status_cache, "body", None)
    monkeypatch.setattr(main, "_check_database", lambda: False)
    body = test_client.get("/status").json()
    assert body["components"]["database"]["status"] == "down"
    assert body["status"] == "degraded"
    monkeypatch.setitem(main._status_cache, "body", None)  # don't leak the degraded body into other tests


def test_status_api_is_broken_down_into_checks(test_client, monkeypatch):
    monkeypatch.setitem(main._status_cache, "body", None)
    api = test_client.get("/status").json()["components"]["api"]
    checks = {c["id"]: c for c in api["checks"]}
    assert {"signin", "records", "emergency", "queue", "jobs", "federation"} <= set(checks)
    assert checks["records"]["status"] == "up" and api["status"] == "up"
    assert checks["federation"]["status"] == "disabled"  # MPI not configured in tests


def test_status_failing_api_check_degrades_api_and_overall(test_client, monkeypatch):
    monkeypatch.setitem(main._status_cache, "body", None)
    monkeypatch.setattr(main, "_db_probe", lambda fn: False)
    body = test_client.get("/status").json()
    assert body["components"]["api"]["status"] == "degraded"
    assert all(c["status"] == "down" for c in body["components"]["api"]["checks"] if c["id"] != "federation")
    assert body["status"] == "degraded"
    monkeypatch.setitem(main._status_cache, "body", None)


def test_status_reports_a_typical_latency_after_a_few_samples(test_client, monkeypatch):
    main._status_history.clear()
    for _ in range(6):
        monkeypatch.setitem(main._status_cache, "body", None)
        body = test_client.get("/status").json()
    db = body["components"]["database"]
    assert db["samples"] >= 5 and db["typical_ms"] >= 0 and db["p95_ms"] >= db["typical_ms"]
