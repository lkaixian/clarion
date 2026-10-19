"""Central MPI (backend/mpi) + the hospital-side client and federation routes."""
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest

# The MPI engine is created at import time -- point it at a throwaway file
# BEFORE importing it.
_mpi_db = os.path.join(tempfile.mkdtemp(), "mpi.db")
os.environ["MPI_DATABASE_URL"] = f"sqlite:///{_mpi_db}"
os.environ["MPI_ADMIN_TOKEN"] = "admin-token-for-tests-0123456789"
os.environ["MPI_ALLOW_HTTP"] = "1"  # the test peers are http://*.test

from starlette.testclient import TestClient  # noqa: E402

from app import models, mpi_client  # noqa: E402
from mpi import main as mpi_main, sigs  # noqa: E402

ADMIN = {"Authorization": "Bearer admin-token-for-tests-0123456789"}
PEPPER = "shared-hospital-pepper"


@pytest.fixture(scope="module")
def central():
    with TestClient(mpi_main.app) as c:
        yield c


def _facility(central, fid, endpoint="http://hosp.test"):
    seed, pub = sigs.generate_keypair()
    r = central.post("/admin/facilities", headers=ADMIN, json={
        "facility_id": fid, "name": f"{fid} name", "public_key": pub, "endpoint": endpoint})
    assert r.status_code == 200, r.text
    return seed


def _signed(central, fid, seed, method, path, json_body=None, ts=None):
    import json
    raw = json.dumps(json_body, separators=(",", ":")).encode() if json_body is not None else b""
    headers = sigs.sign_headers(fid, seed, method, path, raw)
    if ts is not None:  # re-sign with a chosen timestamp
        headers["X-Timestamp"] = str(ts)
        headers["X-Signature"] = sigs.sign(
            seed, sigs.request_message(method, path, ts, headers["X-Nonce"], sigs.CENTRAL_AUDIENCE, raw))
    if raw:
        headers["Content-Type"] = "application/json"
    return central.request(method, path, content=raw, headers=headers)


def _pointer(fid, seed, pkey, ref, when, chash=None):
    chash = chash or secrets.token_hex(32)
    return {
        "patient_key": pkey, "visit_ref": ref, "visited_at": when, "content_hash": chash,
        "signature": sigs.sign(seed, sigs.pointer_message(pkey, fid, ref, when, chash)),
    }


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _consent(db, patient_id, granted):
    """Append a cross_facility_sharing ledger row (newest wins)."""
    db.add(models.ConsentRecord(
        patient_id=patient_id, purpose="cross_facility_sharing", granted=granted,
        source="portal", created_at=datetime.now(timezone.utc)))
    db.commit()


def _audit_actions(db, patient_id):
    return [r.action for r in db.query(models.AuditLog).filter_by(patient_id=patient_id)]


# ---- central ---------------------------------------------------------------

def test_registration_needs_the_admin_token(central):
    r = central.post("/admin/facilities", json={
        "facility_id": "evil", "name": "x", "public_key": sigs.generate_keypair()[1],
        "endpoint": "http://x.test"})
    assert r.status_code == 403


def test_unsigned_or_unknown_callers_are_rejected(central):
    pkey = secrets.token_hex(32)
    assert central.get(f"/patients/{pkey}").status_code == 401
    stranger_seed, _ = sigs.generate_keypair()
    assert _signed(central, "nobody", stranger_seed, "GET", f"/patients/{pkey}").status_code == 401


def test_stale_and_replayed_requests_are_rejected(central):
    seed = _facility(central, "fac-replay")
    pkey = secrets.token_hex(32)
    path = f"/patients/{pkey}"
    assert _signed(central, "fac-replay", seed, "GET", path, ts=int(time.time()) - 3600).status_code == 401

    headers = sigs.sign_headers("fac-replay", seed, "GET", path)
    assert central.get(path, headers=headers).status_code == 200
    assert central.get(path, headers=headers).status_code == 401  # same signature again


def test_pointer_signature_must_verify_and_ring_keeps_three(central):
    seed = _facility(central, "fac-ring")
    pkey = secrets.token_hex(32)

    bad = _pointer("fac-ring", seed, pkey, "v-bad", _iso(1))
    bad["content_hash"] = "0" * 64  # signature no longer matches
    assert _signed(central, "fac-ring", seed, "PUT", "/pointers", bad).status_code == 422

    future = _pointer("fac-ring", seed, pkey, "v-future", _iso(-30))  # 30 days ahead
    assert _signed(central, "fac-ring", seed, "PUT", "/pointers", future).status_code == 422

    for i, days in enumerate((10, 8, 6, 4)):  # oldest first
        r = _signed(central, "fac-ring", seed, "PUT", "/pointers", _pointer("fac-ring", seed, pkey, f"v{i}", _iso(days)))
        assert r.status_code == 200, r.text

    got = _signed(central, "fac-ring", seed, "GET", f"/patients/{pkey}").json()
    assert [p["visit_ref"] for p in got] == ["v3", "v2", "v1"]  # newest first, oldest pruned
    assert got[0]["facility_id"] == "fac-ring" and got[0]["endpoint"]


def test_one_hospital_cannot_evict_another_hospitals_pointers(central):
    seed_a, seed_b = _facility(central, "fac-evict-a"), _facility(central, "fac-evict-b")
    pkey = secrets.token_hex(32)
    assert _signed(central, "fac-evict-a", seed_a, "PUT", "/pointers",
                   _pointer("fac-evict-a", seed_a, pkey, "genuine", _iso(30))).status_code == 200
    for i in range(6):  # B floods the ring with newer pointers
        assert _signed(central, "fac-evict-b", seed_b, "PUT", "/pointers",
                       _pointer("fac-evict-b", seed_b, pkey, f"junk{i}", _iso(1 + i))).status_code == 200
    with mpi_main.SessionLocal() as db:
        kept = {p.visit_ref for p in db.query(mpi_main.Pointer).filter_by(patient_key=pkey)}
    assert "genuine" in kept and len([k for k in kept if k.startswith("junk")]) == 3


def test_http_endpoint_and_short_admin_token_are_refused(central, monkeypatch):
    monkeypatch.setattr(mpi_main, "_ALLOW_HTTP", False)
    r = central.post("/admin/facilities", headers=ADMIN, json={
        "facility_id": "plain-http", "name": "x", "public_key": sigs.generate_keypair()[1],
        "endpoint": "http://insecure.test"})
    assert r.status_code == 422
    monkeypatch.setenv("MPI_ADMIN_TOKEN", "short")
    r = central.post("/admin/facilities", headers={"Authorization": "Bearer short"}, json={
        "facility_id": "short-tok", "name": "x", "public_key": sigs.generate_keypair()[1],
        "endpoint": "https://ok.test"})
    assert r.status_code == 403


def test_a_visit_ref_cannot_be_repointed_to_another_patient(central):
    seed = _facility(central, "fac-bind")
    k1, k2 = secrets.token_hex(32), secrets.token_hex(32)
    assert _signed(central, "fac-bind", seed, "PUT", "/pointers",
                   _pointer("fac-bind", seed, k1, "same-ref", _iso(1))).status_code == 200
    r = _signed(central, "fac-bind", seed, "PUT", "/pointers", _pointer("fac-bind", seed, k2, "same-ref", _iso(1)))
    assert r.status_code == 409


def test_lookups_are_audited(central):
    seed = _facility(central, "fac-audit")
    pkey = secrets.token_hex(32)
    _signed(central, "fac-audit", seed, "GET", f"/patients/{pkey}")
    with mpi_main.SessionLocal() as db:
        rows = db.query(mpi_main.Lookup).filter_by(requester="fac-audit").all()
    assert len(rows) == 1 and rows[0].patient_key_prefix == pkey[:12]


# ---- hospital client end to end --------------------------------------------

@contextmanager
def _identity(fid, seed, name=None):
    old = {k: os.environ.get(k) for k in (
        "MPI_BASE_URL", "CLARION_FACILITY_ID", "CLARION_FACILITY_PRIVATE_KEY",
        "CLARION_MPI_PEPPER", "CLARION_FACILITY_NAME")}
    os.environ.update({
        "MPI_BASE_URL": "http://central.test", "CLARION_FACILITY_ID": fid,
        "CLARION_FACILITY_PRIVATE_KEY": seed, "CLARION_MPI_PEPPER": PEPPER,
        "CLARION_FACILITY_NAME": name or fid,
    })
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_publish_lookup_fetch_and_tamper_detection(central, test_client, db_session, make_user, monkeypatch):
    signer = make_user(role="clinician", facility="Hospital A")
    seed_a = _facility(central, "hosp-a", endpoint="http://hosp-a.test")
    seed_b = _facility(central, "hosp-b", endpoint="http://hosp-b.test")
    mpi_client._key_cache.clear()

    nric = f"90{secrets.randbelow(10**10):010d}"
    patient = models.Patient(full_name="Fed Patient", date_of_birth="1990-01-01", national_id=nric)
    db_session.add(patient)
    db_session.commit()
    _consent(db_session, patient.id, True)
    enc = models.Encounter(
        patient_id=patient.id, facility_name="Hospital A", encounter_type="outpatient",
        reason="cough", notes="rest and fluids", started_at=datetime.now(timezone.utc) - timedelta(days=1),
        signed_by=signer.id, signed_by_name="Dr A", signed_by_role="clinician",
    )
    db_session.add(enc)
    db_session.commit()

    tampered = {"on": False}

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "central.test":
            r = central.request(request.method, request.url.path, content=request.content,
                                headers=dict(request.headers))
        else:  # a peer hospital's backend: serve as hospital A
            with _identity("hosp-a", seed_a, name="Hospital A"):
                mpi_client._key_cache.clear()
                r = test_client.request(request.method, request.url.path, content=request.content,
                                        headers=dict(request.headers))
            if tampered["on"] and r.status_code == 200:
                body = r.json()
                body["notes"] = "altered in transit"
                return httpx.Response(200, json=body)
        return httpx.Response(r.status_code, content=r.content,
                              headers={"content-type": r.headers.get("content-type", "application/json")})

    monkeypatch.setattr(mpi_client, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(route)))

    # Hospital A publishes the visit.
    with _identity("hosp-a", seed_a, name="Hospital A"):
        mpi_client._publish_job({"encounter_id": enc.id})

    # Hospital B asks where the patient has been, then fetches and verifies.
    with _identity("hosp-b", seed_b):
        mpi_client._key_cache.clear()
        pointers = mpi_client.lookup(nric)
        assert [p["visit_ref"] for p in pointers] == [enc.id]
        assert pointers[0]["facility_id"] == "hosp-a"

        doc = mpi_client.fetch_visit(nric, pointers[0])
        assert doc["notes"] == "rest and fluids" and doc["consultation"] is None

        # The same NRIC with a different pepper is a different, unknown key.
        os.environ["CLARION_MPI_PEPPER"] = "some-other-pepper"
        assert mpi_client.lookup(nric) == []
        os.environ["CLARION_MPI_PEPPER"] = PEPPER

        # Peer pinning: a key central hands out that differs from the pin is refused.
        mpi_client._key_cache.clear()
        wrong = sigs.generate_keypair()[1]
        os.environ["CLARION_PEER_KEYS"] = '{"hosp-a": {"public_key": "%s"}}' % wrong
        with pytest.raises(mpi_client.MpiError, match="pinned"):
            mpi_client.fetch_visit(nric, pointers[0])
        os.environ.pop("CLARION_PEER_KEYS")
        mpi_client._key_cache.clear()

        # A record altered after signing no longer matches the pointer's hash.
        tampered["on"] = True
        with pytest.raises(mpi_client.MpiError, match="content hash"):
            mpi_client.fetch_visit(nric, pointers[0])


def test_peer_route_rejects_unregistered_callers(central, test_client, monkeypatch):
    seed = _facility(central, "hosp-serve", endpoint="http://hosp-serve.test")
    mpi_client._key_cache.clear()

    def to_central(request: httpx.Request) -> httpx.Response:
        r = central.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    monkeypatch.setattr(mpi_client, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(to_central)))
    stranger_seed, _ = sigs.generate_keypair()
    with _identity("hosp-serve", seed):
        path = "/federation/visits/" + "a" * 64 + "/x"
        headers = sigs.sign_headers("stranger", stranger_seed, "GET", path, audience="hosp-serve")
        assert test_client.get(path, headers=headers).status_code == 401
        assert test_client.get(path).status_code == 401


# ---- patient consent --------------------------------------------------------

def test_origin_refuses_to_serve_a_visit_without_consent_and_audits_it(
        central, test_client, db_session, make_user, monkeypatch):
    signer = make_user(role="clinician", facility="Hospital C")
    seed_c = _facility(central, "hosp-c", endpoint="http://hosp-c.test")
    seed_d = _facility(central, "hosp-d", endpoint="http://hosp-d.test")
    mpi_client._key_cache.clear()

    nric = f"91{secrets.randbelow(10**10):010d}"
    patient = models.Patient(full_name="Consent Patient", date_of_birth="1991-01-01", national_id=nric)
    db_session.add(patient)
    db_session.commit()
    enc = models.Encounter(
        patient_id=patient.id, facility_name="Hospital C", encounter_type="outpatient",
        reason="rash", notes="cream", started_at=datetime.now(timezone.utc) - timedelta(days=1),
        signed_by=signer.id, signed_by_name="Dr C", signed_by_role="clinician",
    )
    db_session.add(enc)
    db_session.commit()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "central.test":
            r = central.request(request.method, request.url.path, content=request.content,
                                headers=dict(request.headers))
        else:
            with _identity("hosp-c", seed_c, name="Hospital C"):
                mpi_client._key_cache.clear()
                r = test_client.request(request.method, request.url.path, content=request.content,
                                        headers=dict(request.headers))
        return httpx.Response(r.status_code, content=r.content,
                              headers={"content-type": r.headers.get("content-type", "application/json")})

    monkeypatch.setattr(mpi_client, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(route)))
    # Without consent nothing is published: central never learns the visit exists.
    with _identity("hosp-c", seed_c, name="Hospital C"):
        mpi_client._publish_job({"encounter_id": enc.id})
    with _identity("hosp-d", seed_d):
        mpi_client._key_cache.clear()
        assert mpi_client.lookup(nric) == []

    # Consent given at sign-off time (pointer published), then withdrawn.
    _consent(db_session, patient.id, True)
    with _identity("hosp-c", seed_c, name="Hospital C"):
        mpi_client._publish_job({"encounter_id": enc.id})
    _consent(db_session, patient.id, False)

    with _identity("hosp-d", seed_d):
        mpi_client._key_cache.clear()
        pointer = mpi_client.lookup(nric)[0]

        # Withdrawn -> denied, and it looks like an unknown visit to the caller.
        with pytest.raises(mpi_client.MpiError):
            mpi_client.fetch_visit(nric, pointer)
        assert "federation_peer_denied_no_consent" in _audit_actions(db_session, patient.id)
        assert "federation_visit_served" not in _audit_actions(db_session, patient.id)

        # Granted -> served.
        _consent(db_session, patient.id, True)
        mpi_client._key_cache.clear()
        assert mpi_client.fetch_visit(nric, pointer)["notes"] == "cream"

        # Withdrawn later -> denied again (newest ledger row wins).
        _consent(db_session, patient.id, False)
        mpi_client._key_cache.clear()
        with pytest.raises(mpi_client.MpiError):
            mpi_client.fetch_visit(nric, pointer)


def test_staff_federation_routes_need_the_patients_consent(
        test_client, db_session, make_user, auth_headers, monkeypatch):
    from app.routers import federation

    clin = make_user(role="clinician", facility="Hospital B")
    patient = models.Patient(full_name="Staff Consent", date_of_birth="1990-02-02",
                             national_id=f"92{secrets.randbelow(10**10):010d}")
    db_session.add(patient)
    db_session.commit()
    monkeypatch.setattr(mpi_client, "enabled", lambda: True)
    monkeypatch.setattr(federation, "_patient_present_at", lambda *a, **k: True)
    monkeypatch.setattr(mpi_client, "lookup", lambda nric: [])
    monkeypatch.setattr(mpi_client, "_cfg", lambda: {"facility_id": "hosp-b"})
    url = f"/federation/patients/{patient.id}/other-visits"
    fetch_url = f"/federation/patients/{patient.id}/visits/hosp-a/some-ref"

    for u in (url, fetch_url):
        resp = test_client.get(u, headers=auth_headers(clin))
        assert resp.status_code == 403, resp.text
        assert "consented" in resp.json()["detail"]
    assert _audit_actions(db_session, patient.id).count("federation_denied_no_consent") == 2

    _consent(db_session, patient.id, True)
    assert test_client.get(url, headers=auth_headers(clin)).status_code == 200

    _consent(db_session, patient.id, False)  # withdrawn
    assert test_client.get(url, headers=auth_headers(clin)).status_code == 403


def test_a_hospital_can_retract_only_its_own_pointers_for_a_patient(central):
    seed_a = _facility(central, "hosp-w-a")
    seed_b = _facility(central, "hosp-w-b")
    pkey = secrets.token_hex(32)
    for fid, seed, ref in (("hosp-w-a", seed_a, "va1"), ("hosp-w-b", seed_b, "vb1")):
        r = _signed(central, fid, seed, "PUT", "/pointers", _pointer(fid, seed, pkey, ref, _iso(1)))
        assert r.status_code == 200, r.text

    assert _signed(central, "hosp-w-a", seed_a, "DELETE", f"/patients/{pkey}").json() == {"removed": 1}
    left = _signed(central, "hosp-w-b", seed_b, "GET", f"/patients/{pkey}").json()
    assert [p["facility_id"] for p in left] == ["hosp-w-b"]
    assert _signed(central, "hosp-w-a", seed_a, "DELETE", f"/patients/{pkey}").json() == {"removed": 0}
    assert central.delete(f"/patients/{pkey}").status_code == 401  # unsigned


class _FakeRedis:
    def __init__(self, store, fail=False):
        self.store, self.fail = store, fail

    def set(self, name, value, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("down")
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True


def test_replay_cache_is_shared_through_redis_and_degrades_to_local():
    shared = {}
    a, b = sigs.ReplayCache(), sigs.ReplayCache()
    a._redis, b._redis = _FakeRedis(shared), _FakeRedis(shared)
    assert a.first_time(("f", "sig"), 1000.0) is True
    assert b.first_time(("f", "sig"), 1000.0) is False  # a second worker sees the replay

    down = sigs.ReplayCache()
    down._redis = _FakeRedis({}, fail=True)
    assert down.first_time(("f", "s2"), 1000.0) is True
    assert down.first_time(("f", "s2"), 1000.0) is False  # local memory still catches it
