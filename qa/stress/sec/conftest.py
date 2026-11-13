"""Shared helpers for the live-URL security suite (qa/stress/sec).

Everything is driven by env, nothing is hardcoded:
  BASE_URL        https://clarion.example.com            (required; no trailing slash)
  API_PREFIX      /api                                   (default; "" if hitting the backend directly)
  SEC_USER/SEC_PASS            a staff login (cookie + JWT tests); for an MFA role also set SEC_TOTP_SECRET (base32)
  SEC_<ROLE>_USER/_PASS        ROLE in ADMIN CLINICIAN PHARMACIST RECEPTIONIST PATIENT OTHERFAC
  SEC_INSECURE=1  skip TLS verification (tls internal origin tests)
  APP_ENV=demo    HSTS short max-age becomes an xfail instead of a failure
  SEC_BEHIND_CF=1 (default) a `Server: cloudflare` header is not a leak
  SEC_OUT         dir for CSV/inventory output (default qa/stress/sec/results)
Like qa/blackbox: login is OAuth2 form, replay checks are STATELESS (explicit Cookie header,
never a cookie jar, which would silently present the rotated cookie and invert the result).
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

COOKIE_NAME = "clarion_refresh_token"
UA = "clarion-sec-suite/1.0"
HERE = Path(__file__).resolve().parent


def env(name, default=""):
    return os.environ.get(name, default).strip()


BASE = env("BASE_URL").rstrip("/")
API = env("API_PREFIX", "/api").rstrip("/")
VERIFY = env("SEC_INSECURE") != "1"
IS_DEMO = env("APP_ENV").lower() == "demo"
OUT = Path(env("SEC_OUT") or HERE / "results")


def url(path, api=True):
    return f"{BASE}{API if api else ''}{path}"


def client(**kw):
    kw.setdefault("timeout", 20)
    kw.setdefault("verify", VERIFY)
    kw.setdefault("follow_redirects", False)
    kw.setdefault("headers", {"User-Agent": UA})
    return httpx.Client(**kw)


_last_step = [0]


def _totp(secret_b32):
    """RFC 6238 code. The server refuses a step it already accepted, so a second login in the same 30 s step waits."""
    step = int(time.time() // 30)
    if step <= _last_step[0]:
        time.sleep(30 - time.time() % 30 + 0.5)
        step = int(time.time() // 30)
    _last_step[0] = step
    s = secret_b32.strip().replace(" ", "").upper()
    d = hmac.new(base64.b32decode(s + "=" * (-len(s) % 8)), struct.pack(">Q", step), hashlib.sha1).digest()
    o = d[-1] & 15
    return str((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def login(user, password, tries=2):
    """-> (response, body_dict). Retries once past a per-IP 429. If the account is an MFA role and SEC_TOTP_SECRET is set
    (admin / clinician on a production build), the TOTP step is answered too and the returned response is the one that
    carries the tokens and the refresh cookie (/auth/mfa/verify)."""
    with client() as c:
        for i in range(tries):
            r = c.post(url("/auth/login"), data={"username": user, "password": password})
            if r.status_code != 429:
                break
            time.sleep(65)
        try:
            body = r.json()
        except ValueError:
            body = {}
        secret = os.environ.get("SEC_TOTP_SECRET")
        if r.status_code == 200 and body.get("mfa_required") and secret and not body.get("mfa_enrol"):
            for attempt in (0, 1):          # a code from a step another process used is refused: retry on the next step
                r = c.post(url("/auth/mfa/verify"), json={"mfa_token": body["mfa_token"], "code": _totp(secret)})
                if r.status_code != 401 or attempt:
                    break
                _last_step[0] = int(time.time() // 30)
            try:
                body = r.json()
            except ValueError:
                body = {}
    return r, body


def parse_set_cookie(raw):
    """'name=v; Path=/; HttpOnly' -> dict with lower-cased attrs ('' for flags)."""
    parts = [p.strip() for p in raw.split(";")]
    name, _, val = parts[0].partition("=")
    attrs = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        attrs[k.strip().lower()] = v.strip()
    return {"name": name, "value": val, "attrs": attrs, "raw": raw}


def cookies_of(resp):
    return [parse_set_cookie(c) for c in resp.headers.get_list("set-cookie")]


def refresh_cookie(resp):
    for c in cookies_of(resp):
        if c["name"] in (COOKIE_NAME, "__Host-" + COOKIE_NAME, "__Secure-" + COOKIE_NAME):
            return c
    return None


def with_cookie(tok, **extra):
    return {"Cookie": f"{COOKIE_NAME}={tok}", "User-Agent": UA, **extra}


def hsts_max_age(headers):
    v = headers.get("strict-transport-security", "")
    for p in v.split(";"):
        p = p.strip().lower()
        if p.startswith("max-age="):
            try:
                return int(p.split("=", 1)[1].strip('"'))
            except ValueError:
                return None
    return None


def _need_base():
    if not BASE:
        pytest.skip("BASE_URL not set")


@pytest.fixture(scope="session", autouse=True)
def _base_required():
    _need_base()


def _creds(prefix):
    u, p = env(f"{prefix}_USER"), env(f"{prefix}_PASS")
    return (u, p) if u and p else None


@pytest.fixture(scope="session")
def creds():
    c = _creds("SEC")
    if not c:
        pytest.skip("SEC_USER/SEC_PASS not set")
    return c


@pytest.fixture()
def session(creds):
    """A fresh login per test (own refresh family). -> dict(access, refresh, cookie, resp)."""
    r, body = login(*creds)
    if r.status_code != 200 or not body.get("access_token"):
        pytest.skip(f"login did not yield a token (status {r.status_code}; MFA account?)")
    ck = refresh_cookie(r)
    tok = (ck and ck["value"]) or body.get("refresh_token")
    if not tok:
        pytest.skip("login returned no refresh token (cookie or body)")
    return {"access": body["access_token"], "refresh": tok, "cookie": ck, "resp": r}


def role_tokens():
    """{role: access_token} for every SEC_<ROLE>_USER/PASS pair that logs in without MFA."""
    out = {}
    for role in ("ADMIN", "CLINICIAN", "PHARMACIST", "RECEPTIONIST", "PATIENT", "OTHERFAC"):
        c = _creds(f"SEC_{role}")
        if not c:
            continue
        r, body = login(*c)
        if r.status_code == 200 and body.get("access_token"):
            out[role.lower()] = body["access_token"]
    return out


@pytest.fixture(scope="session")
def tokens():
    return role_tokens()


def bearer(t):
    return {"Authorization": f"Bearer {t}", "User-Agent": UA}


def host():
    return urlsplit(BASE).hostname
