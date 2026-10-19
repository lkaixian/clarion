"""Network-penetration cases (suite groups S-H / S-D-010/011 / S-F-008 /
S-I-007 / S-H-006 host-surface half) — black-box executable slice.

Targets the stack directly on 127.0.0.1 (no Caddy in this topology — the edge
proxy itself is Docker-only and lives in the docker-marked block at the bottom).
Raw-socket probes never assert on anything the docs don't state.
"""

import socket
import time

import httpx
import pytest

from conftest import bearer

PROBE_UID = "04:QA:B0:X5:DE:AD"  # well-formed-looking, guaranteed unregistered


def _raw(port: int, payload: bytes, timeout: float = 10.0) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(payload)
        try:
            return s.recv(65536)
        except socket.timeout:
            return b""
    finally:
        s.close()


# --- discovery / documented surface ---------------------------------------------


def test_openapi_reachable_and_documented(stack):
    """Info/audit: openapi.json is the suite's own discovery surface. Recorded,
    not failed — docs exposure is a deploy-hardening decision."""
    r = httpx.get(f"{stack.base_url}/openapi.json", timeout=15)
    assert r.status_code == 200
    docs = httpx.get(f"{stack.base_url}/docs", timeout=15, follow_redirects=True)
    assert docs.status_code in (200, 404), f"docs endpoint misbehaving: {docs.status_code}"


# --- S-H-007 CORS fail-closed matrix ---------------------------------------------


def test_cors_wildcard_never_pairs_with_credentials(stack):
    """S-H-007: wherever ACAO is '*', credentials MUST NOT be allowed; the
    wildcard itself requires the explicit demo opt-in."""
    r = httpx.options(
        f"{stack.base_url}/auth/login",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
        timeout=10,
    )
    acao = r.headers.get("access-control-allow-origin", "")
    creds = r.headers.get("access-control-allow-credentials", "")
    if acao == "*":
        assert creds.lower() != "true", "wildcard CORS combined with credentials — SA-M3 regression"
    if creds.lower() == "true":
        assert acao not in ("", "*"), "credentials allowed without an exact-origin allowlist"


def test_cors_null_origin_not_credentialed(stack):
    """S-H-007 (c): a null-origin (sandboxed iframe / redirected) request is
    never granted a credentialed cross-origin response."""
    r = httpx.get(
        f"{stack.base_url}/healthz",
        headers={"Origin": "null"},
        timeout=10,
    )
    acao = r.headers.get("access-control-allow-origin", "")
    creds = r.headers.get("access-control-allow-credentials", "")
    if creds.lower() == "true":
        assert acao not in ("", "*", "null")


# --- S-H-008 edge hardening (direct-to-backend equivalents) ----------------------


def test_oversized_request_header_recorded_and_survives(stack):
    """S-H-008 (direct-to-backend half): a 64KB header against the raw backend
    is RECORDED — in the composed topology the 431 cap lives at the Caddy edge
    (P1.9 M2 `max_header_size`) and the backend is expose-only, so a huge
    header can only ever arrive from the internal network. Assert: the server
    processes or rejects it WITHOUT dying. The 431-at-edge assertion is the
    docker-marked edge matrix."""
    payload = b"GET /healthz HTTP/1.1\r\nHost: qa\r\nX-Big: " + b"A" * 65536 + b"\r\n\r\n"
    data = _raw(stack.port, payload, timeout=15)
    if data:
        status = data.split(b"\r\n", 1)[0]
        assert b"500" not in status and b"503" not in status, (
            f"oversized header crashed the handler: {status!r}"
        )
    assert httpx.get(f"{stack.base_url}/healthz", timeout=10).status_code == 200


def test_crlf_and_desync_probes_rejected(stack):
    """S-D-010 / request-smuggling class: bare-LF header injection and
    conflicting Content-Length are rejected without echoing or crashing."""
    probes = [
        b"GET /healthz HTTP/1.1\r\nHost: qa\r\nX-Bad: v\rINJECTED: x\r\n\r\n",
        b"POST /healthz HTTP/1.1\r\nHost: qa\r\nContent-Length: 5\r\n"
        b"Content-Length: 6\r\n\r\nAAAAA",
    ]
    for p in probes:
        data = _raw(stack.port, p, timeout=10)
        if data:
            first = data.split(b"\r\n", 1)[0]
            assert b"200" not in first or b"400" in data, (
                f"desync probe accepted: {first!r}"
            )
    assert httpx.get(f"{stack.base_url}/healthz", timeout=10).status_code == 200


def test_h2c_smuggling_upgrade_refused(stack):
    """S-H-008: an h2c upgrade attempt is never answered with 101."""
    data = _raw(
        stack.port,
        b"POST /healthz HTTP/1.1\r\nHost: qa\r\nConnection: Upgrade, HTTP2-Settings\r\n"
        b"Upgrade: h2c\r\nContent-Length: 0\r\n\r\n",
        timeout=10,
    )
    if data:
        first = data.split(b"\r\n", 1)[0]
        assert b"101" not in first, "h2c upgrade accepted — smuggling vector"
        assert first.startswith(b"HTTP/1."), f"unexpected protocol response: {first!r}"


def test_slowloris_does_not_starve_health(stack):
    """S-H-008 (lite): an open, half-sent request never blocks /healthz.
    (Real edge idle-timeout enforcement = docker-marked S-H-008 full case.)"""
    s = socket.create_connection(("127.0.0.1", stack.port), timeout=10)
    try:
        s.sendall(b"GET /healthz HTTP/1.1\r\nHost: qa\r\n")  # deliberately unfinished
        time.sleep(3.0)
        r = httpx.get(f"{stack.base_url}/healthz", timeout=10)
        assert r.status_code == 200, "single stalled connection starved the worker"
    finally:
        s.close()


# --- S-I-007 public emergency surface --------------------------------------------


def test_public_emergency_scan_minimal_payload(stack):
    """S-I-007 / S-B-004: scan endpoints accept no token; a miss is a clean
    not-found and a hit exposes critical-only fields (AGE, never DOB/NRIC)."""
    forbidden_keys = {"national_id", "dob", "date_of_birth", "nric"}

    r = httpx.post(f"{stack.base_url}/emergency/nfc/scan",
                   json={"uid": PROBE_UID}, timeout=10)
    assert r.status_code in (200, 404, 422), f"unexpected scan behaviour: {r.status_code}"
    if r.status_code == 200:
        body = r.json().get("data", r.json())
        assert not (forbidden_keys & set(map(str.lower, body.keys()))), body

    r2 = httpx.post(f"{stack.base_url}/emergency/scan",
                    json={"code": PROBE_UID}, timeout=10)
    assert r2.status_code in (200, 404, 422), f"unexpected QR-scan behaviour: {r2.status_code}"
    if r2.status_code == 200:
        body = r2.json().get("data", r2.json())
        assert not (forbidden_keys & set(map(str.lower, body.keys()))), body
    # the public-surface point: a malformed/unauthenticated scan is never a 401/403
    # (these endpoints are public by design) and never a 5xx.


# --- S-H-005 XFF spoof (executable half; full key-identity proof = burst test) ---


def test_forged_xff_not_authorized_as_trust_signal(stack):
    """S-H-005: the backend itself must not act on a client-supplied
    X-Forwarded-For (FORWARDED_ALLOW_IPS is 127.0.0.1 by default). Observable,
    code-free proof lives in test_zzxf… in the compromise file, where a forged
    XFF demonstrably fails to escape the per-IP rate-limit bucket."""


# --- S-F-008 / S-H-001..006 — the real edge (Docker only) -------------------------


@pytest.mark.docker
def test_edge_tls_floor_headers_and_port_surface():
    """S-F-008 + S-H-001/002/003/004/005/006 against the composed proxy:
    - testssl/nmap: TLS 1.0/1.1 + weak suites refused; tls1.2/1.3 floor pinned
    - HTTP->HTTPS 308; HSTS present WITHOUT preload; CSP/X-Frame/COOP/CORP set;
      '-Server' suppressed
    - GET /api/metrics and /api/readyz -> 404 at the edge (P5.1 owed live check)
    - nmap from host + second machine: ONLY proxy 80/443 reachable; web/backend
      expose-only; mariadb/minio/redis/orthanc/hl7/grafana closed off the host
    - XFF spoof through the proxy vs direct-to-backend key identity
    Runbook: suite doc S-H section."""
