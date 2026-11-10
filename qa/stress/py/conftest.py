"""Live-suite fixtures. Everything is env driven; tests skip when BASE_URL is unset.

BASE_URL          https://staging.example         (required)
ADMIN_EMAIL/ADMIN_PASSWORD   staging admin login   (required for most tests)
TOXIPROXY_URL     http://localhost:8474           (degraded-network tests)
VERIFY_TLS        0 to accept a self-signed cert  (default 0)
"""
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
VERIFY = os.environ.get("VERIFY_TLS", "0") == "1"


def pytest_collection_modifyitems(config, items):
    if BASE_URL:
        return
    skip = pytest.mark.skip(reason="BASE_URL not set (live staging URL required)")
    for it in items:
        if it.fspath.basename in ("test_races_live.py", "test_degraded_network.py"):
            it.add_marker(skip)


@pytest.fixture(scope="session")
def base():
    return BASE_URL


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, verify=VERIFY, timeout=30) as c:
        yield c


def login(client, email, password):
    r = client.post("/auth/login", data={"username": email, "password": password})
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    return r.json()


@pytest.fixture(scope="session")
def admin(client):
    email, pw = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not (email and pw):
        pytest.skip("ADMIN_EMAIL/ADMIN_PASSWORD not set")
    tok = login(client, email, pw)
    return {"headers": {"Authorization": f"Bearer {tok['access_token']}"}, "refresh": tok.get("refresh_token"),
            "email": email, "password": pw, "user": tok.get("user", {})}
