"""T1-T7: TLS floor, security headers, redirects, diagnostics not public, origin bypass (section E2).

Needs only BASE_URL. Optional: ORIGIN_IP (the Pi's public/LAN IP) for T7.
"""

import socket
import ssl
import subprocess
from urllib.parse import urlsplit

import httpx
import pytest

from conftest import BASE, IS_DEMO, VERIFY, client, env, hsts_max_age, host, url

REQUIRED = {
    "strict-transport-security": None,
    "content-security-policy": "default-src",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": None,
    "permissions-policy": None,
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
BEHIND_CF = env("SEC_BEHIND_CF", "1") == "1"


def _tls_connect(minv, maxv):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("ALL:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    ctx.minimum_version, ctx.maximum_version = minv, maxv
    u = urlsplit(BASE)
    with socket.create_connection((u.hostname, u.port or 443), timeout=10) as s:
        with ctx.wrap_socket(s, server_hostname=u.hostname) as t:
            return t.version()


# --- T1 (stdlib half; tls_audit.sh does the full testssl run) -----------------------------------
def test_t1_tls12_and_13_accepted():
    for v in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        assert _tls_connect(v, v) is not None


@pytest.mark.parametrize("name", ["TLSv1", "TLSv1_1"])
def test_t1_legacy_tls_refused(name):
    v = getattr(ssl.TLSVersion, name)
    try:
        got = _tls_connect(v, v)
    except (ssl.SSLError, OSError, ValueError):
        return  # handshake refused (or this OpenSSL cannot even offer it): pass
    pytest.fail(f"{name} handshake succeeded ({got})")


# --- T2 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/api/healthz"])
def test_t2_security_headers(path):
    with client() as c:
        r = c.get(BASE + path)
    h = r.headers
    missing = [k for k, want in REQUIRED.items() if k not in h or (want and want.lower() not in h[k].lower())]
    assert not missing, f"{path}: missing/wrong {missing}"
    assert "server" not in h or (BEHIND_CF and h["server"].lower() == "cloudflare"), f"Server banner: {h.get('server')}"
    assert "x-powered-by" not in h, h.get("x-powered-by")
    age = hsts_max_age(h)
    assert age and age > 0
    if age < 31536000:
        if IS_DEMO:
            pytest.xfail(f"HSTS max-age={age} (demo)")
        pytest.fail(f"HSTS max-age={age} < 31536000")


def test_t2_no_wildcard_cors_with_credentials():
    with client() as c:
        r = c.options(url("/auth/login"), headers={"Origin": "https://evil.example",
                                                   "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
    assert not (r.headers.get("access-control-allow-origin") == "*"
                and r.headers.get("access-control-allow-credentials", "").lower() == "true")


# --- T3 ------------------------------------------------------------------------------------------
def test_t3_http_redirects_and_serves_nothing():
    try:
        with client() as c:
            r = c.get("http://" + BASE.split("://", 1)[1] + "/")
    except httpx.ConnectError:
        pytest.skip("port 80 closed")
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"].startswith("https://")
    assert len(r.content) < 2048, "http:// response carries a body"


# --- T6 ------------------------------------------------------------------------------------------
BLOCKED = ["/metrics", "/readyz", "/docs", "/redoc", "/openapi.json",
           "/METRICS", "/Readyz", "/metrics/", "//metrics", "/%6detrics", "/%2e/metrics", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("p", BLOCKED)
def test_t6_diagnostics_not_public(p):
    with client() as c:
        r = c.get(url(p))
    body = r.text[:4000]
    assert r.status_code in (403, 404), f"{url(p)} -> {r.status_code}"
    assert "http_requests_total" not in body and '"openapi"' not in body and "swagger" not in body.lower()


# --- T7 ------------------------------------------------------------------------------------------
def test_t7_origin_ip_does_not_answer():
    ip = env("ORIGIN_IP")
    if not ip:
        pytest.skip("ORIGIN_IP not set")
    for port in (80, 443):
        try:
            socket.create_connection((ip, port), timeout=6).close()
        except OSError:
            continue
        # Port open: it must not serve the app for our Host header.
        try:
            r = httpx.get(f"{'https' if port == 443 else 'http'}://{ip}:{port}/healthz",
                          headers={"Host": host()}, verify=False, timeout=8)
        except httpx.HTTPError:
            continue
        pytest.fail(f"origin {ip}:{port} answers directly ({r.status_code}); bind to the tunnel only / firewall it")


def test_t1_testssl_json_if_available():
    """Runs tls_audit.sh when testssl is installed; skip otherwise."""
    import shutil, pathlib
    if not (shutil.which("testssl.sh") or shutil.which("testssl")):
        pytest.skip("testssl.sh not installed")
    sh = pathlib.Path(__file__).with_name("tls_audit.sh")
    p = subprocess.run(["bash", str(sh), host()], capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout[-3000:]
