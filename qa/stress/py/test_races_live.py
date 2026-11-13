"""Live-URL races R1, R2, R4, R8, R9, R10, R11 (spec: docs/stress-and-security-test-protocol.md section C).

Needs BASE_URL + ADMIN_EMAIL/ADMIN_PASSWORD (a STAGING admin with a facility). Creates its own
patients/bills and leaves them behind (staging data). Payment races need the mock gateway
(APP_ENV=demo or PAYMENTS_ALLOW_MOCK=1) and skip otherwise.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import login_tokens
from race import histogram, run


def _n(res, code):
    return sum(1 for r in res if isinstance(r, httpx.Response) and r.status_code == code)


def _ok(res):
    return sum(1 for r in res if isinstance(r, httpx.Response) and 200 <= r.status_code < 300)


def _post(client, path, headers, **kw):
    r = client.post(path, headers=headers, **kw)
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text[:200]}"
    return r.json()


def _nric():
    return f"900101-14-{secrets.randbelow(10000):04d}"


def _patient_account(client, ah, name):
    pat = _post(client, "/patients", ah, json={"full_name": name, "national_id": _nric()})
    acct = _post(client, f"/auth/patients/{pat['id']}/issue-account", ah)
    return pat, acct


def _patient_headers(client, acct):
    """Temporary password -> forced change -> real login. The password policy needs a special character (! @ # $ * . ?)."""
    tok = client.post("/auth/login", data={"username": acct["email"], "password": acct["temporary_password"]}).json()
    newpw = "Race-" + secrets.token_urlsafe(12) + "9!"
    r = client.post("/auth/change-password", headers={"Authorization": f"Bearer {tok['access_token']}"}, json={"new_password": newpw})
    assert r.status_code == 200, f"password change refused: {r.status_code} {r.text[:120]}"
    tok = client.post("/auth/login", data={"username": acct["email"], "password": newpw}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


@pytest.fixture(scope="module")
def bill_world(client, admin):
    """A patient account with one finalized RM 50.00 bill: (patient_headers, bill_id, admin_headers)."""
    ah = admin["headers"]
    pat, acct = _patient_account(client, ah, "Race Live")
    ph = _patient_headers(client, acct)
    item = _post(client, "/billing/charge-master", ah,
                 json={"category": "consultation", "name": "Race consult", "unit_price_cents": 5000})
    bill = _post(client, "/billing/bills", ah, json={"patient_id": pat["id"]})
    _post(client, f"/billing/bills/{bill['id']}/items", ah,
          json={"source_type": "charge_master", "charge_master_item_id": item["id"], "quantity": 1})
    _post(client, f"/billing/bills/{bill['id']}/finalize", ah)
    return ph, bill["id"], ah


def _paid_cents(client, ah, bill_id):
    return client.get(f"/billing/bills/{bill_id}", headers=ah).json()["paid_cents"]


def test_r1_parallel_simulate_one_payment(client, base, bill_world):
    ph, bill_id, ah = bill_world
    i = client.post(f"/payments/bills/{bill_id}/intents", headers=ph, json={})
    assert i.status_code in (200, 201), i.text
    res = run("POST", f"{base}/payments/intents/{i.json()['id']}/simulate", 20, headers=ph,
              json={"outcome": "succeeded"})
    if _n(res, 403) == len(res):
        pytest.skip("mock gateway disabled on this node")
    assert _paid_cents(client, ah, bill_id) == 5000, histogram(res)


def test_r2_parallel_pay_never_exceeds_bill(client, base, bill_world):
    ph, bill_id, ah = bill_world
    res = run("POST", f"{base}/payments/bills/{bill_id}/intents", 20, headers=ph,
              per_request=lambda i: {"json": {"amount_cents": 1000, "idempotency_key": uuid.uuid4().hex}})
    ids = {r.json()["id"] for r in res if isinstance(r, httpx.Response) and r.status_code in (200, 201)}
    for iid in ids:
        client.post(f"/payments/intents/{iid}/simulate", headers=ph, json={"outcome": "succeeded"})
    assert _paid_cents(client, ah, bill_id) <= 5000 and len(ids) <= 1, histogram(res)


def test_r11_same_nric_one_patient(base, admin):
    nric = _nric()  # all 20 requests share it
    res = run("POST", f"{base}/patients", 20, headers=admin["headers"], json={"full_name": "Dup", "national_id": nric})
    assert _ok(res) == 1, histogram(res)


def test_r4_double_booking_one_slot(client, base, admin):
    """One patient fires 20 self-books for the same clinician slot; the unique constraint admits one."""
    ah = admin["headers"]
    fac = client.get("/auth/me", headers=ah).json().get("facility")
    if not fac:
        pytest.skip("admin has no facility")
    pat, acct = _patient_account(client, ah, "Slot Race")
    ph = _patient_headers(client, acct)
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    slots = client.get("/patients/appointment-slots", headers=ph, params={"facility_name": fac, "date": day}).json()
    if not slots:
        pytest.skip("no bookable clinician slot tomorrow on this facility")
    s = slots[0]
    res = run("POST", f"{base}/patients/{pat['id']}/appointments/self-book", 20, headers=ph,
              json={"facility_name": fac, "clinician_id": s.get("clinician_id"), "scheduled_at": s["scheduled_at"]})
    assert _ok(res) <= 1, histogram(res)


def test_r8_refresh_rotation_single_winner(client, base, admin):
    tok = login_tokens(client, admin["email"], admin["password"])
    rt = tok.get("refresh_token")
    if not rt:
        pytest.skip("login returned no refresh_token")
    res = run("POST", f"{base}/auth/refresh", 5, json={"refresh_token": rt})
    assert _ok(res) == 1, histogram(res)  # spec: exactly one new pair


def test_r9_lockout_not_bypassed_by_parallelism(client, base, admin):
    """Throwaway patient account, so the real admin is never locked."""
    _, acct = _patient_account(client, admin["headers"], "Lock Race")
    res = run("POST", f"{base}/auth/login", 30, data={"username": acct["email"], "password": "definitely-wrong-1"})
    if _n(res, 429) >= 28:
        pytest.skip(f"per-IP limiter answered first; lockout not observable from one IP: {histogram(res)}")
    ok = client.post("/auth/login", data={"username": acct["email"], "password": acct["temporary_password"]})
    assert ok.status_code == 429, f"account not locked after 30 parallel wrong passwords: {histogram(res)}"


def test_r10_rate_limit_holds(base):
    res = run("POST", f"{base}/auth/login", 200, data={"username": "nobody@x.test", "password": "x"})
    h = histogram(res)
    # limit 20/min; without Redis each of 4 workers counts alone, so allow 4x
    assert 429 in h and _n(res, 401) <= 20 * 4, h
