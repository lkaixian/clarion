def test_app_version_is_public_and_configurable(test_client, monkeypatch):
    r = test_client.get("/app/version")
    assert r.status_code == 200 and set(r.json()) == {"latest", "min_supported", "download_url"}
    monkeypatch.setenv("CLARION_APP_LATEST_VERSION", "9.9.9")
    assert test_client.get("/app/version").json()["latest"] == "9.9.9"
