"""CK1-CK11: refresh-token cookie handling against a LIVE url (protocol section E1).

  BASE_URL=https://clarion.example.com SEC_USER=... SEC_PASS=... pytest qa/stress/sec/test_cookies.py -v
Each test that needs a session logs in afresh so refresh families never interfere.
"""

import re
import subprocess

import httpx
import pytest

from conftest import (BASE, COOKIE_NAME, IS_DEMO, UA, bearer, client, cookies_of, env, hsts_max_age,
                      refresh_cookie, url, with_cookie)

REDIRECTS = (301, 302, 307, 308)


# --- CK1 / CK10 ----------------------------------------------------------------------------------
def test_ck1_cookie_attributes(session):
    ck = session["cookie"]
    if ck is None:
        pytest.skip("web flow sets no cookie (body-only refresh token)")
    a = ck["attrs"]
    assert "httponly" in a, f"HttpOnly missing: {ck['raw']}"
    assert "secure" in a, f"Secure missing: {ck['raw']}"
    assert a.get("samesite", "").lower() in ("strict", "lax"), f"SameSite: {ck['raw']}"
    if env("SEC_REQUIRE_STRICT", "1") == "1":
        assert a.get("samesite", "").lower() == "strict", f"SameSite should be Strict: {ck['raw']}"
    assert a.get("max-age", "").isdigit() and int(a["max-age"]) > 0, f"no finite Max-Age: {ck['raw']}"
    # Protocol wants Path limited to /api/auth. The app default is "/" (REFRESH_COOKIE_PATH) because
    # a Path=/auth cookie is never sent to /api/auth/refresh. Set REFRESH_COOKIE_PATH=/api/auth in
    # the Pi compose to satisfy this; SEC_ALLOW_ROOT_PATH=1 accepts "/" knowingly.
    if env("SEC_ALLOW_ROOT_PATH") != "1":
        assert a.get("path", "/") != "/", f"cookie Path is '/', sent to every route: {ck['raw']}"


def test_ck1b_host_prefix(session):
    ck = session["cookie"]
    if ck is None:
        pytest.skip("no cookie")
    if not ck["name"].startswith("__Host-"):
        pytest.xfail("no __Host- prefix (needs Path=/ and no Domain; conflicts with a narrowed Path)")


def test_ck10_no_domain_attribute(session):
    ck = session["cookie"]
    if ck is None:
        pytest.skip("no cookie")
    assert "domain" not in ck["attrs"], f"Domain set (cookie shared with subdomains): {ck['raw']}"


# --- CK2 -----------------------------------------------------------------------------------------
def _http_base():
    return "http://" + BASE.split("://", 1)[1]


def test_ck2_plaintext_http_redirects_without_cookie(creds):
    h = _http_base()
    try:
        with client() as c:
            g = c.get(h + "/")
            p = c.post(h + url("/auth/login", api=True)[len(BASE):],
                       data={"username": creds[0], "password": creds[1]})
    except httpx.ConnectError:
        pytest.skip("port 80 closed (fine: nothing is served over http)")
    for r in (g, p):
        assert r.status_code in REDIRECTS, f"{r.request.method} http:// returned {r.status_code}, not a redirect"
        assert r.headers.get("location", "").startswith("https://")
        assert not r.headers.get_list("set-cookie"), "Set-Cookie on a plaintext response"
        assert "access_token" not in r.text


# --- CK6 -----------------------------------------------------------------------------------------
def test_ck6_no_token_in_url_or_js_storage(session):
    r = session["resp"]
    assert "location" not in r.headers or "token" not in r.headers["location"].lower()
    with client() as c:
        idx = c.get(BASE + "/")
        if idx.status_code != 200:
            pytest.skip(f"SPA index {idx.status_code}")
        bad = []
        for src in re.findall(r'src="(/assets/[^"]+\.js)"', idx.text)[:12]:
            js = c.get(BASE + src).text
            bad += re.findall(
                r"(?:local|session)Storage\.setItem\(\s*[\"'][^\"']*(?:token|refresh|jwt)[^\"']*[\"']", js, re.I)
    assert not bad, f"tokens written to web storage: {bad[:3]}"


def test_ck6b_token_not_in_server_logs(session):
    """Only when SEC_LOG_CMD is set, e.g. 'docker compose -f docker-compose.pi.yml logs --no-color --since 10m proxy backend'."""
    cmd = env("SEC_LOG_CMD")
    if not cmd:
        pytest.skip("SEC_LOG_CMD not set")
    with client() as c:  # one authenticated call so the token has a chance to be logged
        c.get(url("/auth/me"), headers=bearer(session["access"]))
    logs = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60).stdout
    assert session["refresh"] not in logs, "refresh token value found in logs"
    assert session["access"] not in logs, "access token value found in logs"
    assert "Bearer ey" not in logs, "Authorization header logged"


# --- CK7 -----------------------------------------------------------------------------------------
def _refresh(tok, **hdr):
    with client() as c:
        return c.post(url("/auth/refresh"), headers=with_cookie(tok, **hdr))


def _new_token(resp):
    ck = refresh_cookie(resp)
    return (ck and ck["value"]) or (resp.json().get("refresh_token") if resp.status_code == 200 else None)


def test_ck7_replay_after_logout(session):
    t = session["refresh"]
    with client() as c:
        assert c.post(url("/auth/logout"), headers=with_cookie(t)).status_code == 200
    again = _refresh(t)
    assert again.status_code == 401, f"refresh after logout returned {again.status_code}"


def test_ck7_rotation_reuse_revokes_family(session):
    a = session["refresh"]
    r1 = _refresh(a)
    assert r1.status_code == 200, f"first refresh failed: {r1.status_code}"
    b = _new_token(r1)
    assert b and b != a, "refresh token was not rotated"
    assert _refresh(a).status_code == 401, "old (rotated) token still accepted"
    # reuse of A must have burned the whole family, including the legitimate successor B
    assert _refresh(b).status_code == 401, "family not revoked after reuse (B still works)"


# --- CK8 -----------------------------------------------------------------------------------------
EVIL = "https://evil.example"


@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
def test_ck8_csrf_cors_never_reflects_foreign_origin(session, path):
    with client() as c:
        pre = c.options(url(path), headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"})
        r = c.post(url(path), headers=with_cookie(session["refresh"], Origin=EVIL, **{"Sec-Fetch-Site": "cross-site"}))
    for resp in (pre, r):
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao not in (EVIL, "*") or resp.headers.get("access-control-allow-credentials", "").lower() != "true", \
            f"credentialed CORS granted to a foreign origin on {path}"
    # Server-side Origin enforcement is NOT in the app (SameSite=Strict is the whole defence).
    if r.status_code == 200 and env("SEC_STRICT_ORIGIN") == "1":
        pytest.fail(f"{path} honoured the cookie on a cross-site request (add an Origin/Sec-Fetch-Site check)")
    if r.status_code == 200:
        pytest.xfail(f"{path} honours a cookie sent with a foreign Origin; defence relies on SameSite=Strict only")


def test_ck8b_samesite_blocks_when_not_strict(session):
    ck = session["cookie"]
    if ck is None:
        pytest.skip("no cookie")
    assert ck["attrs"].get("samesite", "").lower() != "none"


# --- CK9 (cheap half: CSP) -----------------------------------------------------------------------
def test_ck9_csp_blocks_inline_script():
    with client() as c:
        csp = c.get(BASE + "/").headers.get("content-security-policy", "")
    assert csp, "no CSP on the SPA"
    m = re.search(r"script-src([^;]*)", csp)
    assert m and "'unsafe-inline'" not in m.group(1) and "'unsafe-eval'" not in m.group(1), csp


# --- CK11 ----------------------------------------------------------------------------------------
def test_ck11_no_store_on_set_cookie_responses(session):
    r = session["resp"]
    assert r.headers.get_list("set-cookie") or session["cookie"] is None
    cc = r.headers.get("cache-control", "").lower()
    assert "no-store" in cc, f"login response Cache-Control={cc!r} (needs no-store)"
    ref = _refresh(session["refresh"])
    assert "no-store" in ref.headers.get("cache-control", "").lower(), "refresh response lacks no-store"
    for resp in (r, ref):
        assert resp.headers.get("cf-cache-status", "DYNAMIC").upper() in ("DYNAMIC", "BYPASS"), \
            resp.headers.get("cf-cache-status")


# --- HSTS ----------------------------------------------------------------------------------------
def test_hsts_max_age_one_year():
    with client() as c:
        h = c.get(BASE + "/").headers
    age = hsts_max_age(h)
    assert age is not None, "no HSTS header"
    if age < 31536000:
        if IS_DEMO:
            pytest.xfail(f"HSTS max-age={age} (< 31536000) accepted only because APP_ENV=demo")
        pytest.fail(f"HSTS max-age={age} < 31536000; set CLARION_HSTS=max-age=31536000 once TLS is stable")
