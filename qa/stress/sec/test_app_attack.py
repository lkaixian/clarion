"""A1-A8, A12, A13: application attack surface against a LIVE url (protocol section E3).

Non-destructive by construction: anonymous probes only hit operations the OpenAPI marks as secured (they must
be refused), role probes are GET-only, IDOR/SSRF/upload/burst tests are opt-in via env (see README).
Spec source, first hit wins: SEC_OPENAPI_FILE, GET {BASE}{API}/openapi.json, in-process `import app.main`
(throwaway SQLite, never the real DB). The public edge blocks /api/openapi.json, so the in-process path is
the normal one against the Pi.
"""

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import pytest

from conftest import (API, BASE, HERE, OUT, UA, bearer, client, env, login, role_tokens, url)

BACKEND = HERE.parents[2] / "backend"
UUID0 = "00000000-0000-0000-0000-000000000000"
METHODS = ("get", "post", "put", "patch", "delete")
DELAY = float(env("SEC_MATRIX_DELAY", "1.1"))  # global limiter is 60/min; set 0 against a no-limit dev stack


# --- spec ----------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_spec():
    f = env("SEC_OPENAPI_FILE")
    if f:
        return json.load(open(f, encoding="utf8"))
    if BASE:
        try:
            with client() as c:
                r = c.get(url("/openapi.json"))
            if r.status_code == 200 and "paths" in r.json():
                return r.json()
        except Exception:  # noqa: BLE001
            pass
        try:
            return _inprocess_spec()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[sec] no OpenAPI spec available: {e!r}\n")
    return {"paths": {}}


def _inprocess_spec():
    tmp = tempfile.mkdtemp(prefix="sec_spec_")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/spec.db"  # forced: never touch a real DB
    os.environ["APP_ENV"] = "demo"
    os.environ.setdefault("SECRET_KEY", "0" * 64)
    os.environ.setdefault("OTP_HMAC_KEY", "1" * 64)
    os.environ["CLARION_STORAGE_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))
    from app.main import app  # noqa: PLC0415
    return app.openapi()


def ops(spec=None):
    spec = spec or load_spec()
    out = []
    for path, item in spec.get("paths", {}).items():
        for m in METHODS:
            op = item.get(m)
            if op:
                out.append({"method": m.upper(), "path": path, "secured": bool(op.get("security")),
                            "params": re.findall(r"{(\w+)}", path), "op": op,
                            "ptypes": {p["name"]: p.get("schema", {}).get("type") for p in
                                       (item.get("parameters", []) + op.get("parameters", [])) if p.get("in") == "path"}})
    return out


def fill(o, values=None):
    values = values or {}
    p = o["path"]
    for name in o["params"]:
        v = values.get(name) or ("1" if o["ptypes"].get(name) == "integer" else UUID0)
        p = p.replace("{" + name + "}", str(v))
    return p


def send(c, method, path, headers=None, **kw):
    """One request, politely: spaced out and retried past a 429."""
    for _ in range(4):
        time.sleep(DELAY)
        r = c.request(method, url(path), headers=headers or {}, **kw)
        if r.status_code != 429:
            return r
        time.sleep(20)
    return r


ALL_OPS = ops() if BASE else []
SECURED = [o for o in ALL_OPS if o["secured"]]


def _id(o):
    return f"{o['method']} {o['path']}"


@pytest.fixture(scope="module")
def http():
    with client(timeout=30) as c:
        yield c


def _write_csv(name, header, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# --- A1: access control matrix -------------------------------------------------------------------
@pytest.mark.parametrize("o", SECURED, ids=_id)
def test_a1_anonymous_refused_on_every_secured_route(http, o):
    kw = {} if o["method"] == "GET" else {"json": {}}
    r = send(http, o["method"], fill(o), **kw)
    assert r.status_code in (401, 403), f"anonymous {_id(o)} -> {r.status_code}"


def test_a1_public_route_inventory():
    """Every non-secured operation, written to results/public_routes.csv. Fails only for obviously
    sensitive prefixes (override with SEC_PUBLIC_ALLOW=<regex>)."""
    public = [o for o in ALL_OPS if not o["secured"]]
    _write_csv("public_routes.csv", ["method", "path"], [(o["method"], o["path"]) for o in public])
    allow = re.compile(env("SEC_PUBLIC_ALLOW", r"^$"))
    sensitive = re.compile(r"^/(admin|billing|payments|reports?|pharmacy|purchasing|orders|fhir|pacs|drugs|products|"
                           r"fee-schedules|price-tiers|reference|registry|forms|ancillary)\b")
    bad = [_id(o) for o in public if sensitive.search(o["path"]) and not allow.search(o["path"])]
    assert not bad, f"unauthenticated operations under sensitive prefixes: {bad}"


GET_NOPARAM = [o for o in SECURED if o["method"] == "GET" and not o["params"]]
STAFF_ONLY = ("/admin", "/reports", "/reporting", "/purchasing", "/pharmacy", "/fee-schedules", "/price-tiers", "/orders")


def test_a1_role_matrix(tokens):
    if len(tokens) < 2:
        pytest.skip("need >= 2 SEC_<ROLE>_USER/PASS pairs")
    rows, five_xx, leaks = [], [], []
    with client(timeout=30) as c:
        for o in GET_NOPARAM:
            row = [o["path"]]
            for role, t in tokens.items():
                r = send(c, "GET", o["path"], headers=bearer(t))
                row.append(r.status_code)
                if r.status_code >= 500:
                    five_xx.append(f"{role} GET {o['path']} -> {r.status_code}")
                if role in ("patient", "otherfac") and r.status_code < 300 and o["path"].startswith(STAFF_ONLY):
                    leaks.append(f"{role} GET {o['path']} -> {r.status_code}")
                if env("SEC_STRICT_ADMIN") == "1" and role not in ("admin",) and r.status_code < 300 \
                        and o["path"].startswith("/admin"):
                    leaks.append(f"{role} GET {o['path']} -> {r.status_code}")
            rows.append(row)
    _write_csv("role_matrix.csv", ["path"] + list(tokens), rows)
    assert not five_xx, five_xx[:10]
    assert not leaks, leaks[:10]


# --- A2: IDOR ------------------------------------------------------------------------------------
def test_a2_idor_foreign_ids_refused(tokens):
    """SEC_FOREIGN_<PARAM>=<id belonging to someone the low-privilege users must NOT see>,
    e.g. SEC_FOREIGN_PATIENT_ID, SEC_FOREIGN_BILL_ID. Probed with the patient and other-facility tokens."""
    foreign = {k[len("SEC_FOREIGN_"):].lower(): v for k, v in os.environ.items() if k.startswith("SEC_FOREIGN_") and v}
    low = {r: t for r, t in tokens.items() if r in ("patient", "otherfac")}
    if not foreign or not low:
        pytest.skip("set SEC_FOREIGN_PATIENT_ID (etc.) and SEC_PATIENT_USER/PASS or SEC_OTHERFAC_USER/PASS")
    hits, tried = [], 0
    with client(timeout=30) as c:
        for o in SECURED:
            if o["method"] != "GET" or not o["params"] or not all(p in foreign for p in o["params"]):
                continue
            for role, t in low.items():
                r = send(c, "GET", fill(o, foreign), headers=bearer(t))
                tried += 1
                if r.status_code < 300 or r.status_code >= 500:
                    hits.append(f"{role} {_id(o)} -> {r.status_code}")
    assert tried, "no GET operation takes only the supplied foreign ids"
    assert not hits, hits[:15]


# --- A3: rate limit + spoofed XFF (opt-in: it locks YOUR IP out for ~1 min) ----------------------
def test_a3_rate_limit_and_spoofed_forwarded_for():
    if env("SEC_RUN_BURST") != "1":
        pytest.skip("SEC_RUN_BURST=1 to run (trips the per-IP login limiter)")
    codes = []
    try:
        with client() as c:
            for i in range(int(env("SEC_RL_N", "80"))):
                r = c.post(url("/auth/login"), data={"username": f"nobody{i}@invalid.example", "password": "x" * 12})
                codes.append(r.status_code)
                if r.status_code == 429:
                    break
            assert 429 in codes, f"no 429 after {len(codes)} bad logins: {sorted(set(codes))}"
            spoofed = []
            for i in range(1, 11):
                spoofed.append(c.post(url("/auth/login"),
                                      data={"username": f"spoof{i}@invalid.example", "password": "x" * 12},
                                      headers={"X-Forwarded-For": f"203.0.113.{i}", "X-Real-IP": f"203.0.113.{i}",
                                               "CF-Connecting-IP": f"203.0.113.{i}", "User-Agent": UA}).status_code)
            assert all(s == 429 for s in spoofed), f"spoofed X-Forwarded-For bypassed the limiter: {spoofed}"
    finally:
        time.sleep(65)


# --- A4 (cheap slice): injection strings at the login door ---------------------------------------
@pytest.mark.parametrize("payload", ["' OR '1'='1' --", "admin'--", "*)(uid=*))(|(uid=*", "\x00", "a" * 5000])
def test_a4_login_injection_strings_rejected(http, payload):
    r = send(http, "POST", "/auth/login", data={"username": payload, "password": "wrongwrong12"})
    assert r.status_code in (400, 401, 422, 429), f"{r.status_code}"
    assert "Traceback" not in r.text and "sqlalchemy" not in r.text.lower() and "ldap" not in r.text.lower()


# --- A5: traversal + upload abuse ----------------------------------------------------------------
TRAVERSAL = ["/../../../../etc/passwd", "/..%2f..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd",
             "/%252e%252e/%252e%252e/etc/passwd", "/....//....//etc/passwd", "/assets/..%2f..%2f..%2fetc/passwd",
             "/static/../../etc/passwd", "/maintenance/..%2f..%2fetc/passwd", "/maintenance/../../etc/passwd"]


@pytest.mark.parametrize("p", TRAVERSAL)
@pytest.mark.parametrize("api", [True, False])
def test_a5_path_traversal_not_served(http, p, api):
    r = http.get(BASE + (API if api else "") + p)
    assert "root:x:0:0" not in r.text and "daemon:" not in r.text, f"/etc/passwd served via {p}"
    assert r.status_code < 500


@pytest.mark.parametrize("seg", ["../../etc/passwd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..\\..\\windows\\win.ini", "x\x00.png"])
def test_a5_traversal_in_path_params(tokens, seg):
    t = tokens.get("admin") or next(iter(tokens.values()), None)
    if not t:
        pytest.skip("no role tokens")
    cands = [o for o in SECURED if o["method"] == "GET" and len(o["params"]) == 1 and
             re.search(r"(file|document|download|image|photo|thumbnail|object)", o["path"], re.I)][:6]
    with client() as c:
        for o in cands:
            p = o["path"].replace("{" + o["params"][0] + "}", seg)
            r = send(c, "GET", p, headers=bearer(t))
            assert r.status_code < 500 and "root:x:0:0" not in r.text, f"{p} -> {r.status_code}"


def test_a5_upload_abuse():
    """SEC_UPLOAD='/path:fieldname' (multipart endpoint you may write to as SEC_USER, e.g. a profile photo)."""
    spec, user, pw = env("SEC_UPLOAD"), env("SEC_USER"), env("SEC_PASS")
    if not (spec and user and pw):
        pytest.skip("SEC_UPLOAD (+SEC_USER/PASS) not set")
    path, _, field = spec.partition(":")
    field = field or "file"
    r0, b0 = login(user, pw)
    if not b0.get("access_token"):
        pytest.skip("login failed")
    h = bearer(b0["access_token"])
    cases = {
        "traversal_name": (("../../etc/x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png"), None),
        "mime_lie": (("a.png", b"<?php echo 1; ?>", "image/png"), "reject"),
        "svg_script": (("a.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml"), "reject"),
        "oversize": (("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * (16 * 1024 * 1024 + 1), "image/png"), "reject"),
    }
    with client(timeout=120) as c:
        for name, (f, expect) in cases.items():
            r = send(c, "POST", path, headers=h, files={field: f})
            assert r.status_code < 500, f"{name}: {r.status_code}"
            if name == "traversal_name" and r.status_code < 300:
                assert "../" not in r.text, f"stored/echoed a traversal filename: {r.text[:150]}"
            if expect == "reject":
                assert r.status_code in (400, 413, 415, 422), f"{name} accepted: {r.status_code}"


# --- A6: info leakage ----------------------------------------------------------------------------
LEAKS = {  # path -> signature that proves the real file/page (the SPA fallback returns 200 html for anything)
    "/.git/HEAD": "ref:", "/.git/config": "[core]", "/.env": "=", "/.env.docker": "=", "/.env.tunnel": "TUNNEL",
    "/backend/.env": "=", "/docker-compose.yml": "services:", "/docker-compose.pi.yml": "services:",
    "/proxy/Caddyfile": "reverse_proxy", "/backup.sql": "INSERT", "/dump.sql": "INSERT", "/clarion.db": "SQLite",
    "/openapi.json": '"openapi"', "/docs": "swagger", "/redoc": "redoc", "/server-status": "Apache",
    "/.DS_Store": "Bud1", "/requirements.txt": "fastapi",
}


@pytest.mark.parametrize("p", sorted(LEAKS))
@pytest.mark.parametrize("api", [True, False])
def test_a6_no_sensitive_paths(http, p, api):
    r = http.get(BASE + (API if api else "") + p)
    assert not (r.status_code == 200 and LEAKS[p].lower() in r.text.lower()), f"{p} exposed ({'api' if api else 'root'})"


def test_a6_errors_do_not_leak_internals(http, tokens):
    probes = [("GET", "/definitely-not-a-route", {}), ("POST", "/auth/login", {"content": b"{not json",
              "headers": {"Content-Type": "application/json"}}), ("GET", "/patients/%00", {}),
              ("POST", "/auth/refresh", {"json": {"refresh_token": 12345}})]
    for m, p, kw in probes:
        r = send(http, m, p, **kw)
        low = r.text.lower()
        assert r.status_code < 500, f"{m} {p} -> {r.status_code}"
        for needle in ("traceback", 'file "', "sqlalchemy", "pymysql", "uvicorn", "starlette", "/app/app/"):
            assert needle not in low, f"{m} {p} leaks '{needle}'"
        assert "x-powered-by" not in r.headers


# --- A7: JWT -------------------------------------------------------------------------------------
def _b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def forge(token):
    h, p, s = token.split(".")
    claims = json.loads(_unb64(p))
    elevated = dict(claims, role="admin")
    expired = dict(claims, exp=1)

    def hs(hdr, pl, key):
        si = f"{_b64(json.dumps(hdr).encode())}.{_b64(json.dumps(pl).encode())}"
        return f"{si}.{_b64(hmac.new(key, si.encode(), hashlib.sha256).digest())}"

    out = {
        "alg_none": f"{_b64(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}.{p}.",
        "alg_None_elevated": f"{_b64(json.dumps({'alg': 'None', 'typ': 'JWT'}).encode())}.{_b64(json.dumps(elevated).encode())}.",
        "tampered_claims_orig_sig": f"{h}.{_b64(json.dumps(elevated).encode())}.{s}",
        "stripped_signature": f"{h}.{p}.",
        "wrong_key": hs({"alg": "HS256", "typ": "JWT"}, claims, b"secret"),
        "wrong_key_elevated": hs({"alg": "HS256", "typ": "JWT"}, elevated, b"changeme"),
        "expired_wrong_key": hs({"alg": "HS256", "typ": "JWT"}, expired, b"secret"),
        "garbage": "a.b.c",
        "empty": "",
    }
    return out


def test_a7_jwt_forgeries_rejected(session, http):
    real = send(http, "GET", "/auth/me", headers=bearer(session["access"]))
    assert real.status_code == 200, f"positive control failed: {real.status_code}"
    bad = {}
    for name, tok in forge(session["access"]).items():
        r = send(http, "GET", "/auth/me", headers=bearer(tok))
        if r.status_code != 401 and r.status_code != 403 and r.status_code != 422:
            bad[name] = r.status_code
    assert not bad, f"forged tokens accepted/misrouted: {bad}"


# --- A8: SSRF ------------------------------------------------------------------------------------
SSRF = ["http://169.254.169.254/latest/meta-data/", "http://169.254.169.254.nip.io/", "http://mariadb:3306/",
        "http://redis:6379/", "http://minio:9000/", "http://127.0.0.1:8000/metrics", "http://localhost:8100/",
        "http://[::1]/", "http://0x7f000001/", "http://2130706433/", "http://localhost@evil.example/",
        "file:///etc/passwd", "gopher://redis:6379/_PING"]


def test_a8_ssrf_candidates_listed():
    """Informational: request-body string fields whose name looks like a URL. Written to results/ssrf_candidates.csv."""
    rows = []
    comp = load_spec().get("components", {}).get("schemas", {})
    for o in ALL_OPS:
        body = (o["op"].get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}))
        ref = body.get("$ref", "").rsplit("/", 1)[-1]
        for fld in comp.get(ref, {}).get("properties", {}):
            if re.search(r"url|uri|webhook|endpoint|callback|href|link|host", fld, re.I):
                rows.append((o["method"], o["path"], fld))
    _write_csv("ssrf_candidates.csv", ["method", "path", "field"], rows)


def test_a8_ssrf_targets_refused(tokens):
    """SEC_SSRF='PUT /admin/settings campus_url;POST /x field' (explicit, because a 2xx would STORE the URL).
    Uses the admin token. Any 2xx or 5xx fails; restore the setting by hand if one slipped through."""
    spec = env("SEC_SSRF")
    t = tokens.get("admin")
    if not (spec and t):
        pytest.skip("SEC_SSRF and SEC_ADMIN_USER/PASS not set")
    bad = []
    with client() as c:
        for item in filter(None, (s.strip() for s in spec.split(";"))):
            m, path, field = item.split()
            for target in SSRF:
                r = send(c, m, path, headers=bearer(t), json={field: target})
                if r.status_code < 300 or r.status_code >= 500:
                    bad.append(f"{m} {path} {field}={target} -> {r.status_code}")
    assert not bad, bad[:15]


# --- A12: secrets --------------------------------------------------------------------------------
def test_a12_gitleaks_clean():
    if not shutil.which("gitleaks"):
        pytest.skip("gitleaks not installed")
    repo = HERE.parents[2]
    p = subprocess.run(["gitleaks", "detect", "--no-banner", "--redact", "-s", str(repo)], capture_output=True, text=True)
    assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]


def test_a12_container_env_has_no_default_secrets():
    if env("SEC_DOCKER") != "1" or not shutil.which("docker"):
        pytest.skip("SEC_DOCKER=1 and docker required (run on the Pi)")
    ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split()
    out = subprocess.run(["docker", "inspect", *ids, "--format",
                          "{{.Name}} {{range .Config.Env}}{{println .}}{{end}}"], capture_output=True, text=True).stdout
    weak = sorted({m.group(0)[:60] for m in re.finditer(r"(?i)\S*(change-me|clarion-dev-secret|admin123|password123)\S*", out)})
    assert not weak, f"container env still holds default secrets (names only shown): {[w.split('=')[0] for w in weak]}"


# --- A13: audit log integrity --------------------------------------------------------------------
def test_a13_audit_logs_append_only_as_app_account():
    pw = env("MARIADB_APP_PASSWORD")
    if not (pw and shutil.which("docker")):
        pytest.skip("MARIADB_APP_PASSWORD and docker required (run on the Pi)")
    cid = subprocess.run(["docker", "ps", "-q", "--filter", "name=mariadb"], capture_output=True, text=True).stdout.split()
    if not cid:
        pytest.skip("no mariadb container")
    db = env("MARIADB_DATABASE", "clarion")

    def sql(q):
        return subprocess.run(["docker", "exec", "-e", f"MYSQL_PWD={pw}", cid[0], "sh", "-c",
                               f'(mariadb || mysql) -uclarion_app {db} -N -e "{q}"'], capture_output=True, text=True)

    n = sql("SELECT COUNT(*) FROM audit_logs")
    if n.returncode != 0 or not n.stdout.strip().isdigit() or int(n.stdout) == 0:
        pytest.skip(f"cannot read audit_logs / empty: {n.stderr[:120]}")
    # Row-level triggers only fire when a row is touched; UPDATE sets a column to itself, DELETE is rolled back.
    upd = sql("UPDATE audit_logs SET id = id ORDER BY id DESC LIMIT 1")
    dele = sql("START TRANSACTION; DELETE FROM audit_logs ORDER BY id DESC LIMIT 1; ROLLBACK;")
    after = sql("SELECT COUNT(*) FROM audit_logs")
    assert dele.returncode != 0, "DELETE on audit_logs succeeded for the app account (rolled back, but no trigger/grant stopped it)"
    assert upd.returncode != 0, "UPDATE on audit_logs succeeded for the app account"
    assert after.stdout.strip() == n.stdout.strip(), "audit_logs row count changed"
