from app import main, models


def test_status_is_recorded_and_exposed(test_client, db_session, monkeypatch):
    monkeypatch.setattr(main, "_status_recorded_at", 0.0)
    monkeypatch.setattr(main, "_status_cache", {"at": 0.0, "body": None})
    assert test_client.get("/status").status_code == 200

    rows = db_session.query(models.StatusDaily).all()
    assert any(r.component == "database" and r.total >= 1 for r in rows)

    hist = test_client.get("/status/history?days=90").json()
    assert hist["days"] == 90
    day = next(iter(hist["components"]["database"].values()))
    assert day["total"] >= 1 and day["bad"] == 0


def test_history_days_is_clamped(test_client):
    assert test_client.get("/status/history?days=9999").json()["days"] == 90
