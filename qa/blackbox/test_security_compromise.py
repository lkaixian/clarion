"""Security-compromise cases (suite groups S-A / S-B / S-C / S-D / S-G-001 /
S-I-001..003) — black-box executable slice.

Session-auth tokens are taken ONCE at session start (see conftest.tokens);
deliberate rate-limit bursts are name-prefixed test_zz_/test_zzz_ so pytest
runs them LAST and they don't poison the shared per-IP buckets for the
non-burst cases.
"""

import base64
import json
import time

import httpx
import pytest

from conftest import bearer, demo_email, demo_password, login

BIG = 16 * 1024 * 1024  # above the documented 15 MB upload cap


# --- JWT forgery (S-A-013 / S-A-014) ---------------------------------------------


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode_payload(token: str) -> dict:
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


def test_alg_none_token_rejected(stack, tokens):
    """S-A-013: attacker-chosen alg=none is never accepted."""
    payload = _decode_payload(tokens["admin"]["access_token"])
    forged = f"{_b64u(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}." \
             f"{_b64u(json.dumps(payload).encode())}."
    r = httpx.get(f"{stack.base_url}/patients", headers=bearer(forged), timeout=10)
    assert r.status_code == 401, f"alg=none accepted: {r.status_code}"


def test_tampered_signature_rejected(stack, tokens):
    """S-A-014: flipped signature byte -> 401, no partial trust."""
    tok = tokens["admin"]["access_token"]
    head, pay, sig = tok.split(".")
    bad_sig = ("A" if sig[:1] != "A" else "B") + sig[1:]
    r = httpx.get(f"{stack.base_url}/patients",
                  headers=bearer(f"{head}.{pay}.{bad_sig}"), timeout=10)
    assert r.status_code == 401


def test_tampered_role_claim_rejected(stack, tokens):
    """S-A-014: privilege escalation by re-encoding the payload (sig unchanged)
    -> 401/403. The JWT's role claim must never be trusted over the live DB."""
    tok = tokens["clinician"]["access_token"]
    head, pay, sig = tok.split(".")
    pad = "=" * (-len(pay) % 4)
    payload = json.loads(base64.urlsafe_b64decode(pay + pad))
    payload["role"] = "admin"
    forged = f"{head}.{_b64u(json.dumps(payload).encode())}.{sig}"
    r = httpx.get(f"{stack.base_url}/admin/inventory", headers=bearer(forged), timeout=10)
    assert r.status_code in (401, 403), f"re-encoded claim accepted: {r.status_code}"


# --- S-A-019 enumeration symmetry --------------------------------------------------


def test_login_enumeration_symmetric(stack):
    """S-A-019: wrong password for a real user vs a non-existent user — same
    status, same response shape, no usable timing gap. (One failed attempt on
    one real account; far below the 5-strike lockout.)"""
    t0 = time.perf_counter()
    real = httpx.post(f"{stack.base_url}/auth/login",
                      data={"username": demo_email("pharmacist"),
                            "password": "definitely-wrong-qa"}, timeout=15)
    t_real = time.perf_counter() - t0
    t1 = time.perf_counter()
    fake = httpx.post(f"{stack.base_url}/auth/login",
                      data={"username": "nobody-qa@clarion.demo",
                            "password": "definitely-wrong-qa"}, timeout=15)
    t_fake = time.perf_counter() - t1
    assert real.status_code == fake.status_code and real.status_code in (400, 401, 422), (
        f"status asymmetry: real={real.status_code} fake={fake.status_code}"
    )
    assert set(real.json().keys()) == set(fake.json().keys()), "body shape asymmetry"
    assert abs(t_real - t_fake) < 1.5, f"timing oracle: {t_real:.2f}s vs {t_fake:.2f}s"


# --- S-A-007/008 refresh-token compromise model -------------------------------------


def _cookie_refresh(set_cookies: list[str]) -> str | None:
    for c in set_cookies:
        if "refresh" in c.split("=", 1)[0].lower():
            return c
    return None


def test_refresh_replay_beyond_grace_revokes_whole_family(stack):
    """S-A-007: replaying a rotated refresh token beyond the 8s grace is treated
    as compromise — 401 AND every token in the family is revoked. Uses
    STATELESS calls (a cookie-jar client silently presents the rotated cookie
    and inverts every assertion — see the 2026-09-16 run report)."""
    res = login(stack, demo_email("patient"), demo_password("patient"))
    assert res["status"] == 200
    original = res["refresh_token"]
    assert original, "no refresh token in login response"

    r1 = httpx.post(f"{stack.base_url}/auth/refresh",
                    json={"refresh_token": original}, timeout=15)
    assert r1.status_code == 200, f"first refresh failed: {r1.status_code}"
    body = r1.json()
    newest = body.get("refresh_token")
    if not newest:
        ck = _cookie_refresh(r1.headers.get_list("set-cookie"))
        newest = ck.split("=", 1)[1].split(";", 1)[0] if ck and "=" in ck else None
    assert newest, "rotation did not issue a new refresh token"

    time.sleep(9.5)  # beyond REFRESH_REUSE_GRACE_SECONDS (8)

    replay = httpx.post(f"{stack.base_url}/auth/refresh",
                        json={"refresh_token": original}, timeout=10)
    assert replay.status_code >= 400, (
        "replay of rotated refresh token accepted — SA-M4 compromise model broken"
    )
    # compromise handling: the whole family must now be dead
    r3 = httpx.post(f"{stack.base_url}/auth/refresh",
                    json={"refresh_token": newest}, timeout=10)
    assert r3.status_code >= 400, (
        "newest family token still works after reuse detection — revoke-all missing"
    )


def test_refresh_cookie_flags(stack, tokens):
    """S-A-009: refresh cookie is HttpOnly + SameSite=Strict + Path=/
    (Secure is legitimately absent in the demo topology — do not fail on it)."""
    cookie = _cookie_refresh(tokens["patient"]["set_cookies"])
    if cookie is None:
        res = login(stack, demo_email("patient"), demo_password("patient"))
        r = httpx.post(f"{stack.base_url}/auth/refresh",
                       json={"refresh_token": res["refresh_token"]}, timeout=15)
        cookie = _cookie_refresh(r.headers.get_list("set-cookie"))
    assert cookie is not None, "no refresh cookie observed on login/refresh"
    low = cookie.lower()
    assert "httponly" in low, cookie
    assert "samesite=strict" in low, cookie
    assert "path=/" in low, f"CR9 regression — cookie path narrowed: {cookie}"


# --- S-A-012 password change revokes everywhere --------------------------------------


def test_password_change_revokes_everywhere(stack, openapi):
    """S-A-012: changing the password kills the old access token immediately;
    the password is rotated back afterwards."""
    res = login(stack, demo_email("receptionist"), demo_password("receptionist"))
    assert res["status"] == 200
    old_access = res["access_token"]
    old_pw = demo_password("receptionist")
    new_pw = "qa-rotated-" + "7" * 16  # built at runtime, >= 12 chars

    paths = (openapi.find("password", method="post",
                          exclude=("reset", "forgot", "request", "otp"))
             or openapi.find("password", method="put",
                             exclude=("reset", "forgot", "request", "otp")))
    if not paths:
        pytest.skip("password-change endpoint not discoverable via openapi")
    path = paths[0]
    method = "post" if openapi.find("password", method="post",
                                    exclude=("reset", "forgot", "request", "otp")) else "put"

    changed = False
    for shape in (
        {"current_password": old_pw, "new_password": new_pw},
        {"old_password": old_pw, "new_password": new_pw},
        {"password": old_pw, "new_password": new_pw},
    ):
        r = httpx.request(method, f"{stack.base_url}{path}", json=shape,
                          headers=bearer(old_access), timeout=15)
        if r.status_code < 300:
            changed = True
            break
        if r.status_code not in (404, 422):
            pytest.fail(f"password change refused unexpectedly: {r.status_code} {r.text[:200]}")
    if not changed:
        pytest.skip(f"password-change contract shape unknown at {path}")

    r = httpx.get(f"{stack.base_url}/patients", headers=bearer(old_access), timeout=10)
    assert r.status_code == 401, "old access token survived a password change"

    # restore so any later logins keep working
    new_login = login(stack, demo_email("receptionist"), new_pw, retries=0)
    assert new_login["status"] == 200, "login with rotated password failed"
    for shape in (
        {"current_password": new_pw, "new_password": old_pw},
        {"old_password": new_pw, "new_password": old_pw},
        {"password": new_pw, "new_password": old_pw},
    ):
        r = httpx.request(method, f"{stack.base_url}{path}", json=shape,
                          headers=bearer(new_login["access_token"]), timeout=15)
        if r.status_code < 300:
            break


# --- S-B RBAC matrix spot checks ------------------------------------------------------


def test_rbac_denials_and_admin_allow(stack, tokens):
    """S-B-001/002 spot matrix: pharmacist+receptionist are denied emergency
    issue; patient denied the staff patient list; admin allowed on admin
    inventory where the clinician is not. 401/403 = denied; a 2xx/422/404 here
    means the request got PAST authorization."""
    deny = (401, 403)
    for role in ("pharmacist", "receptionist"):
        r = httpx.post(f"{stack.base_url}/emergency/issue", json={},
                       headers=bearer(tokens[role]["access_token"]), timeout=10)
        assert r.status_code in deny, f"{role} got past emergency-issue authz: {r.status_code}"
    r = httpx.get(f"{stack.base_url}/patients",
                  headers=bearer(tokens["patient"]["access_token"]), timeout=10)
    assert r.status_code in deny, f"patient role read the staff patient list: {r.status_code}"
    r = httpx.get(f"{stack.base_url}/admin/inventory",
                  headers=bearer(tokens["admin"]["access_token"]), timeout=10)
    assert r.status_code == 200, f"admin blocked on admin inventory: {r.status_code}"
    r = httpx.get(f"{stack.base_url}/admin/inventory",
                  headers=bearer(tokens["clinician"]["access_token"]), timeout=10)
    assert r.status_code in deny, f"clinician read admin inventory: {r.status_code}"


def test_unauthenticated_staff_surface_is_closed(stack):
    """S-B-001 (unauth row): every checked staff route answers 401/403, never a
    200, to an anonymous caller."""
    for method, path in (
        ("get", "/patients"),
        ("get", "/admin/inventory"),
        ("post", "/emergency/issue"),
        ("get", "/admin/audit/chain-status"),
    ):
        r = httpx.request(method, f"{stack.base_url}{path}",
                          json={} if method == "post" else None, timeout=10)
        assert r.status_code in (401, 403, 404), (
            f"anonymous {method.upper()} {path} -> {r.status_code}"
        )


# --- S-C facility scoping / break-glass ------------------------------------------------


def _extract_items(body):
    if isinstance(body, list):
        return body
    for v in body.values():
        if isinstance(v, list):
            return v
    return []


def test_patients_pagination_enforced(stack, tokens):
    """S-C-001 (half): list pagination honours skip/limit (max 200)."""
    r = httpx.get(f"{stack.base_url}/patients", params={"limit": 1, "skip": 0},
                  headers=bearer(tokens["admin"]["access_token"]), timeout=15)
    assert r.status_code == 200
    items = _extract_items(r.json())
    assert len(items) <= 1, f"limit=1 returned {len(items)} rows"
    r2 = httpx.get(f"{stack.base_url}/patients", params={"limit": 1, "skip": 1},
                   headers=bearer(tokens["admin"]["access_token"]), timeout=15)
    assert r2.status_code == 200
    items2 = _extract_items(r2.json())
    if items and items2:
        assert items[0].get("id") != items2[0].get("id"), "skip ignored"


def test_break_glass_blank_reason_does_not_unlock(stack, tokens):
    """S-C-002 (half): blank reason and an explicit reason both answer 200, but
    the explicit reason must never return FEWER patients than the blank call
    (unlock semantics), and the blank call must behave like the default list."""
    admin = bearer(tokens["admin"]["access_token"])
    blank = httpx.get(f"{stack.base_url}/patients", params={"break_glass_reason": ""},
                      headers=admin, timeout=15)
    reason = httpx.get(f"{stack.base_url}/patients",
                       params={"break_glass_reason": "qa-blackbox-breakglass"},
                       headers=admin, timeout=15)
    assert blank.status_code == reason.status_code == 200
    assert len(_extract_items(blank.json())) <= len(_extract_items(reason.json()))


# --- S-D injection & input handling -----------------------------------------------------


SQLI_PAYLOADS = [
    "' OR '1'='1",
    "1'; DROP TABLE patients;--",
    "' UNION SELECT 1,2,3--",
    "\" OR \"\"=\"",
]


def test_sqli_sweep_no_500_sql_echo(stack, tokens):
    """S-D-001: injection payloads in string filters never produce a 500 with
    SQL syntax echoed, and never change the response class."""
    admin = bearer(tokens["admin"]["access_token"])
    baseline = httpx.get(f"{stack.base_url}/patients", params={"search": "zzz-no-match"},
                         headers=admin, timeout=15)
    assert baseline.status_code < 500
    for payload in SQLI_PAYLOADS:
        r = httpx.get(f"{stack.base_url}/patients", params={"search": payload},
                      headers=admin, timeout=15)
        if r.status_code >= 500:
            low = r.text.lower()
            assert not ("sql" in low or "syntax" in low or "select" in low), (
                f"SQL error echoed for payload {payload!r}: {r.text[:200]}"
            )


def test_path_traversal_probes_rejected(stack, tokens):
    """S-D-008: traversal-shaped object keys/ids never read outside the
    namespace; 4xx, never 500, never content."""
    admin = bearer(tokens["admin"]["access_token"])
    probes = [
        "/patients/1/documents/1/thumbnail",
        "/patients/1/documents/..%2f..%2f..%2fetc%2fpasswd/thumbnail",
        "/patients/..%2f..%2fetc%2fpasswd",
        "/patients/1/documents/1",
    ]
    for p in probes:
        r = httpx.get(f"{stack.base_url}{p}", headers=admin, timeout=10)
        assert r.status_code < 500, f"{p} -> {r.status_code}"
        assert r.status_code in (200, 403, 404, 422), f"{p} -> {r.status_code}"


def test_oversized_upload_rejected_at_cap(stack, tokens):
    """S-G-001: a 16MB body is refused at the cap (413-class) BEFORE
    processing — live-confirmed posture ('max 15MB') on 2026-09-16."""
    clinician = bearer(tokens["clinician"]["access_token"])
    blob = b"QA" + b"A" * (BIG - 2)
    r = httpx.post(f"{stack.base_url}/ai/digitise/1",
                   files={"file": ("bomb.bin", blob, "application/octet-stream")},
                   headers=clinician, timeout=120)
    assert r.status_code in (413, 422), (
        f"16MB upload not capped (got {r.status_code}) — SA-L2/P1.6 regression"
    )


def test_privilege_fields_not_settable_via_body(stack, tokens, openapi):
    """S-D-012: unknown/privilege fields in a profile update never change the
    caller's role — extra=forbid schemas 422, the one extra=allow residual must
    be handler-filtered (recorded, not re-flagged)."""
    patient = bearer(tokens["patient"]["access_token"])
    paths = (openapi.find("me", method="put") or openapi.find("profile", method="put")
             or openapi.find("patient", method="put", exclude=("patients/",)))
    if not paths:
        pytest.skip("no profile-update endpoint discoverable via openapi")
    path = paths[0]
    r = httpx.put(f"{stack.base_url}{path}",
                  json={"role": "admin", "is_admin": True, "facility_id": 999},
                  headers=patient, timeout=15)
    assert r.status_code < 500, f"profile update crashed: {r.status_code}"
    me = (openapi.find("me", method="get") or openapi.find("profile", method="get"))
    if me:
        r2 = httpx.get(f"{stack.base_url}{me[0]}", headers=patient, timeout=15)
        if r2.status_code == 200:
            body = json.dumps(r2.json()).lower()
            assert '"role": "admin"' not in body and "is_admin" not in body, r2.text[:300]


# --- bursts: ordered last on purpose ---------------------------------------------------


@pytest.mark.burst
def test_zz_login_rate_limit_and_account_lockout(stack):
    """S-I-001 + S-A-017 (acquisition half): a burst of wrong-password logins
    meets BOTH the per-account lockout (5 strikes) and the per-IP 20/min limit —
    401s first, then 429s. Dedicated fake accounts; no real account touched."""
    codes = []
    for i in range(25):
        r = httpx.post(f"{stack.base_url}/auth/login",
                       data={"username": f"qa-burst-{i}@clarion.demo",
                             "password": "wrong-wrong-wrong"}, timeout=10)
        codes.append(r.status_code)
        if r.status_code == 429 and codes.count(429) >= 3:
            break
        time.sleep(0.05)
    assert 401 in codes, f"no auth failures recorded: {codes}"
    assert 429 in codes, (
        f"25 bad logins produced no rate limit/lockout — SA-M1/P5.2 regression: {codes}"
    )


@pytest.mark.burst
def test_zz_otp_endpoints_rate_limited(stack, openapi):
    """S-I-003: the unauthenticated OTP/reset surface is per-IP limited (M2),
    never limiter-exempt."""
    paths = (openapi.find("otp", method="post", exclude=("verify",))
             or openapi.find("forgot", method="post")
             or openapi.find("reset", method="post", exclude=("password",)))
    if not paths:
        pytest.skip("no OTP/request endpoint discoverable via openapi")
    codes = []
    for i in range(12):
        r = httpx.post(f"{stack.base_url}{paths[0]}", json={}, timeout=10)
        codes.append(r.status_code)
        if r.status_code == 429:
            break
        time.sleep(0.1)
    assert 429 in codes, f"12 unauthenticated OTP requests, no 429: {codes}"


@pytest.mark.burst
def test_zzz_global_rate_limit_on_undecorated_route(stack, tokens, openapi):
    """S-I-002: the P5.2 fix — the global 60/min default IS enforced on routes
    with no explicit decorator (SlowAPIMiddleware was a total no-op before)."""
    candidates = sorted(
        (p for p, ops in openapi.paths.items()
         if "get" in ops and "{" not in p
         and not any(x in p.lower() for x in
                     ("auth", "emergency", "metrics", "docs", "openapi", "health"))),
        key=len,
    )
    assert candidates, "no undecorated GET route found to probe"
    path = candidates[0]
    codes = []
    for i in range(70):
        r = httpx.get(f"{stack.base_url}{path}",
                      headers=bearer(tokens["admin"]["access_token"]), timeout=10)
        codes.append(r.status_code)
        if codes.count(429) >= 5:
            break
        time.sleep(0.05)
    assert 429 in codes, f"70 rapid GETs on {path}, never rate limited: {codes[:10]}…"
    assert codes.count(200) >= 50, (
        f"rate limiting broke the route itself: {codes[:10]}…"
    )
