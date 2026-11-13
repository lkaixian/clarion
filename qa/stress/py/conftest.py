"""Live-suite fixtures. Everything is env driven; tests skip when BASE_URL is unset.

BASE_URL          https://staging.example         (required)
ADMIN_EMAIL/ADMIN_PASSWORD   staging admin login   (required for most tests)
TOXIPROXY_URL     http://localhost:8474           (degraded-network tests)
VERIFY_TLS        0 to accept a self-signed cert  (default 0)
"""
import base64
import hashlib
import hmac
import os
import struct
import sys
import time

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


_last_step = [0]


def totp_now(secret_b32):
    """RFC 6238 code (SHA-1, 6 digits, 30 s). The server refuses a step it already accepted, so a second login inside
    the same 30 s step waits for the next one."""
    step = int(time.time() // 30)
    if step <= _last_step[0]:
        time.sleep(30 - time.time() % 30 + 0.5)
        step = int(time.time() // 30)
    _last_step[0] = step
    key = base64.b32decode(secret_b32.strip().replace(" ", "").upper() + "=" * (-len(secret_b32.strip().replace(" ", "")) % 8))
    d = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = d[-1] & 15
    return str((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def login_tokens(client, email, password):
    """Login that also answers an MFA challenge when ADMIN_TOTP_SECRET is set (accounts of an MFA role on a production build)."""
    r = client.post("/auth/login", data={"username": email, "password": password})
    body = r.json() if r.status_code == 200 else {}
    if body.get("mfa_required"):
        secret = os.environ.get("ADMIN_TOTP_SECRET")
        if not secret or body.get("mfa_enrol"):
            pytest.skip(f"{email} needs MFA ({'enrolment' if body.get('mfa_enrol') else 'code'}); set ADMIN_TOTP_SECRET")
        for attempt in (0, 1):             # a code from a step another process already used is refused: retry on the next step
            r = client.post("/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": totp_now(secret)})
            if r.status_code != 401 or attempt:
                break
            _last_step[0] = int(time.time() // 30)
        body = r.json() if r.status_code == 200 else {}
    if "access_token" not in body:
        pytest.skip(f"login did not yield a token for {email} (status {r.status_code})")
    return body


@pytest.fixture(scope="session")
def admin(client):
    email, pw = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not (email and pw):
        pytest.skip("ADMIN_EMAIL/ADMIN_PASSWORD not set")
    tok = login_tokens(client, email, pw)
    return {"headers": {"Authorization": f"Bearer {tok['access_token']}"}, "refresh": tok.get("refresh_token"),
            "email": email, "password": pw, "user": tok.get("user", {})}
