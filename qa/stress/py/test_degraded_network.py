"""RN1-RN10 (docs/stress-and-security-test-protocol.md C2) through Toxiproxy.

Needs BASE_URL (plain-http backend, see toxiproxy_scenarios.py), ADMIN_EMAIL/ADMIN_PASSWORD, and a
Toxiproxy at TOXIPROXY_URL. Optional: PAYMENTS_WEBHOOK_SECRET (RN7), REFRESH_REUSE_GRACE_SECONDS (RN2, default 8).

Gaps the backend has today are `xfail` with the reason, not silent passes:
  RN1  no generic Idempotency-Key header (only POST /payments/bills/{id}/intents has idempotency_key in the body)
  RN2  a refresh token replayed inside the grace window gets 401 (no re-issue of the lost pair)
  RN7  webhook events carry no timestamp, so "old timestamp rejected" cannot hold
"""
import concurrent.futures as cf
import hashlib
import hmac
import json
import os
import secrets
import time

import httpx
import pytest

from test_races_live import _nric, _post, bill_world  # noqa: F401  (bill_world is a fixture)
from conftest import login_tokens
from toxiproxy_scenarios import Proxy, available

GRACE = int(os.environ.get("REFRESH_REUSE_GRACE_SECONDS", "8"))


@pytest.fixture(scope="module")
def px(base):
    if not available():
        pytest.skip("Toxiproxy not reachable at TOXIPROXY_URL")
    with Proxy(base) as p:
        yield p


def via(px, **kw):
    return httpx.Client(base_url=px.url, verify=False, timeout=kw.pop("timeout", 4), **kw)


def _login(client, email, pw):
    return login_tokens(client, email, pw)


# RN1 ------------------------------------------------------------------------
def test_rn1_lost_response_retry_same_intent(px, bill_world):
    """Server commits, response is lost, client times out and retries with the same idempotency_key."""
    ph, bill_id, _ = bill_world
    key = secrets.token_hex(8)
    with px.toxic("timeout", stream="downstream", timeout=0), via(px, timeout=2) as c:
        with pytest.raises(httpx.TimeoutException):
            c.post(f"/payments/bills/{bill_id}/intents", headers=ph, json={"amount_cents": 1500, "idempotency_key": key})
    with via(px) as c:
        retry = c.post(f"/payments/bills/{bill_id}/intents", headers=ph, json={"amount_cents": 1500, "idempotency_key": key})
    assert retry.status_code in (200, 201), retry.text
    mine = [b for b in httpx.get(f"{px.url}/payments/my-bills", headers=ph, verify=False).json() if b["id"] == bill_id][0]
    assert mine["pending_intent"]["id"] == retry.json()["id"]  # one open attempt, the original


@pytest.mark.xfail(strict=False, reason="GAP: no generic Idempotency-Key header; POST /patients (and other non-payment "
                                         "POSTs) create a duplicate when a lost response is retried")
def test_rn1b_generic_idempotency_key_header(px, admin):
    key, name = secrets.token_hex(8), "Idem " + secrets.token_hex(4)
    ids = []
    for _ in range(2):
        with via(px) as c:
            r = c.post("/patients", headers={**admin["headers"], "Idempotency-Key": key}, json={"full_name": name, "date_of_birth": "1990-01-01"})
        ids.append(r.json().get("id"))
    assert ids[0] and ids[0] == ids[1]


# RN2 ------------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="GAP: replaying a just-rotated refresh token inside the grace window returns 401 "
                                         "(auth._is_concurrent_refresh_race only avoids chain revocation); a client whose "
                                         "rotate response was lost cannot recover the new pair without re-login")
def test_rn2_lost_refresh_response_is_recoverable(px, client, admin):
    t1 = _login(client, admin["email"], admin["password"])["refresh_token"]
    with px.toxic("limit_data", stream="downstream", bytes=0), via(px) as c:  # server rotates, response is cut
        try:
            c.post("/auth/refresh", json={"refresh_token": t1})
        except httpx.HTTPError:
            pass
    retry = client.post("/auth/refresh", json={"refresh_token": t1})  # the client only knows t1
    assert retry.status_code == 200


def test_rn2b_replay_after_grace_revokes_family(client, admin):
    t1 = _login(client, admin["email"], admin["password"])["refresh_token"]
    t2 = client.post("/auth/refresh", json={"refresh_token": t1}).json()["refresh_token"]
    time.sleep(GRACE + 2)
    assert client.post("/auth/refresh", json={"refresh_token": t1}).status_code == 401  # stale replay
    assert client.post("/auth/refresh", json={"refresh_token": t2}).status_code == 401  # family revoked


# RN3 ------------------------------------------------------------------------
def test_rn3_double_submit_on_slow_link_one_record(px, bill_world):
    ph, bill_id, _ = bill_world
    key = secrets.token_hex(8)

    def tap(_):
        with via(px, timeout=20) as c:
            return c.post(f"/payments/bills/{bill_id}/intents", headers=ph, json={"amount_cents": 1200, "idempotency_key": key})
    with px.toxic("bandwidth", stream="upstream", rate=1), cf.ThreadPoolExecutor(2) as ex:
        res = list(ex.map(tap, range(2)))
    ids = {r.json()["id"] for r in res if r.status_code in (200, 201)}
    assert len(ids) == 1, [r.status_code for r in res]


# RN4 / RN5 ------------------------------------------------------------------
@pytest.mark.skip(reason="RN4 is a UI race (stale response painted last): covered by the Playwright suite, not the API")
def test_rn4_out_of_order_responses():
    ...


@pytest.mark.skip(reason="RN5 needs a 15-minute access token to expire mid-upload: rerun manually with a short "
                         "ACCESS_TOKEN_EXPIRE_MINUTES on staging and a 100 kbit/s bandwidth toxic")
def test_rn5_token_expiry_during_slow_request():
    ...


# RN6 ------------------------------------------------------------------------
def test_rn6_two_clients_refreshing_on_flaky_link(px, client, admin):
    t1 = _login(client, admin["email"], admin["password"])["refresh_token"]

    def go(_):
        with via(px, timeout=10) as c:
            try:
                return c.post("/auth/refresh", json={"refresh_token": t1}).status_code
            except httpx.HTTPError:
                return "net"
    with px.toxic("latency", latency=300, jitter=200), px.toxic("reset_peer", stream="upstream", toxicity=0.05, timeout=50), \
            cf.ThreadPoolExecutor(2) as ex:
        res = list(ex.map(go, range(2)))
    assert all(r in (200, 401, "net") for r in res) and (200 in res or "net" in res), res  # no 5xx, no loop


# RN7 ------------------------------------------------------------------------
def test_rn7_webhook_bad_signature_rejected_under_brownout(px):
    body = json.dumps({"provider_ref": "nope", "status": "succeeded", "amount_cents": 1}).encode()
    with px.toxic("latency", latency=500, jitter=500), via(px, timeout=10) as c:
        r = c.post("/payments/webhook/mock", content=body, headers={"X-Signature": "00" * 32})
    assert r.status_code in (401, 404)


@pytest.mark.skipif(not os.environ.get("PAYMENTS_WEBHOOK_SECRET"), reason="PAYMENTS_WEBHOOK_SECRET not provided")
def test_rn7b_signed_webhook_replayed_10x_settles_once(px, client, bill_world):
    ph, bill_id, ah = bill_world
    paid0 = client.get(f"/billing/bills/{bill_id}", headers=ah).json()["paid_cents"]
    i = client.post(f"/payments/bills/{bill_id}/intents", headers=ph, json={"amount_cents": 700}).json()
    body = json.dumps({"provider_ref": i["provider_ref"], "status": "succeeded", "amount_cents": 700}).encode()
    sig = hmac.new(os.environ["PAYMENTS_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()

    def hit(_):
        time.sleep(secrets.randbelow(2000) / 1000)
        with via(px, timeout=15) as c:
            return c.post("/payments/webhook/mock", content=body, headers={"X-Signature": sig}).status_code
    with px.toxic("latency", latency=300, jitter=300), cf.ThreadPoolExecutor(10) as ex:
        list(ex.map(hit, range(10)))
    assert client.get(f"/billing/bills/{bill_id}", headers=ah).json()["paid_cents"] == paid0 + 700


@pytest.mark.xfail(run=False, reason="GAP: webhook events carry no timestamp, so an old-but-validly-signed event cannot be "
                                      "rejected for age; replay safety rests only on the intent-state compare-and-set")
def test_rn7c_old_timestamp_rejected():
    ...


# RN8 ------------------------------------------------------------------------
def test_rn8_stalled_clients_do_not_starve_workers(px, client):
    """Approximates a half-open peer: 30 requests stall in the proxy, clients give up; the backend must stay responsive."""
    def stall(_):
        with via(px, timeout=1.5) as c:
            try:
                c.get("/healthz")
            except httpx.HTTPError:
                pass
    with px.toxic("timeout", stream="downstream", timeout=0), cf.ThreadPoolExecutor(30) as ex:
        list(ex.map(stall, range(30)))
    t0 = time.time()
    assert client.get("/healthz").status_code == 200 and time.time() - t0 < 2


# RN9 ------------------------------------------------------------------------
def test_rn9_retry_storm_after_blackout(px):
    def retry(_):
        with via(px, timeout=5) as c:
            for backoff in (0.2, 0.4, 0.8, 1.6, 3.2):  # capped, jittered
                try:
                    return c.get("/healthz").status_code
                except httpx.HTTPError:
                    time.sleep(backoff * (0.5 + secrets.randbelow(100) / 100))
        return "gave_up"
    with cf.ThreadPoolExecutor(100) as ex:
        with px.down():
            futs = [ex.submit(retry, i) for i in range(100)]
            time.sleep(3)
        res = [f.result() for f in futs]
    assert not [r for r in res if isinstance(r, int) and r >= 500], "5xx cascade after recovery"
    assert res.count(200) >= 95, {r: res.count(r) for r in set(res)}


# RN10 -----------------------------------------------------------------------
def _chain(n, uid):
    prev, out = "0" * 64, []
    for seq in range(n):
        at = f"2026-10-10T08:{seq:02d}:00Z"
        h = hashlib.sha256("|".join([prev, str(seq), at, uid, "1", "decrypted"]).encode()).hexdigest()
        out.append({"seq": seq, "read_at": at, "nfc_uid": uid, "key_id": 1, "outcome": "decrypted",
                    "prev_hash": prev, "entry_hash": h})
        prev = h
    return out


def test_rn10_offline_queue_replay_exactly_once(px, client, admin):
    body = {"device_id": "dev-" + secrets.token_hex(4), "entries": _chain(25, secrets.token_hex(7).upper())}
    done = False
    for _ in range(6):  # lossy link: the response is cut after the server commits, so the client retries
        with px.toxic("limit_data", stream="downstream", bytes=40), via(px) as c:
            try:
                done = c.post("/emergency/offline-reads", headers=admin["headers"], json=body).status_code == 200
            except httpx.HTTPError:
                done = False
        if done:
            break
    final = client.post("/emergency/offline-reads", headers=admin["headers"], json=body).json()
    assert final["stored"] == 0 and final["duplicates"] == 25 and final["chain_broken"] == 0, final
