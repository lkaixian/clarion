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
