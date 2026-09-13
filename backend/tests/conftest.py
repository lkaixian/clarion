"""Shared pytest fixtures for HTTP-level backend tests (P1.12).

Before P1.12, the only HTTP-level test file (test_ldap_auth.py, P1.10)
rolled its own throwaway-SQLite-DB + TestClient setup at the top of the
file. This consolidates that into one place so the next router-level test
file (auth/RBAC/cross-facility immutability -- the actual P1.12 goal) can
just use these fixtures instead of repeating it.

pytest ALWAYS imports a directory's conftest.py before collecting any test
module in that directory, so the module-level env-var block below runs
before any test file's own imports -- including test_ldap_auth.py's own
(now redundant, but harmless: `app.database`'s engine is a module-level
global fixed at first import, so setting DATABASE_URL again afterward is a
no-op) copy of this same guard. This block MUST stay at the very top of
the file, before any `from app...` import anywhere in this conftest.
"""
import os
import tempfile

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="clarion_test_")
os.close(_TMP_DB_FD)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _TMP_DB_PATH.replace("\\", "/"))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-any-real-deployment")
os.environ.setdefault("OTP_HMAC_KEY", "test-only-otp-hmac-key-not-for-any-real-deployment")
os.environ.setdefault("APP_ENV", "demo")

import atexit  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth as auth_module  # noqa: E402
from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402 -- importing this runs _ensure_schema() against _TMP_DB_PATH


@atexit.register
def _cleanup_tmp_db():
    try:
        os.remove(_TMP_DB_PATH)
    except OSError:
        pass


@pytest.fixture(scope="session")
def test_client():
    """One TestClient for the whole session -- cheap to share. Real
    per-IP rate limits now exist (Security Audit M1/M2) and TestClient's
    requests all share one fake client IP, so slowapi's counters
    accumulate across every test in the run unless reset -- see
    _reset_rate_limiter below, which handles that."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Security Audit M1/M2 added real per-IP limits (e.g. 20/minute on
    POST /auth/login) that previously didn't exist. Every test shares one
    TestClient -> one fake client IP, so without a reset here, cumulative
    login/OTP calls across the FULL test run (127+ tests, many logging in
    at least once) trip those limits well before any individual test's own
    logic is at fault -- this bit the very first run after adding them.
    Reset before every test rather than once per session so test order/
    selection (`pytest -k ...`, a single file, etc.) can never change
    whether a given test sees a fresh limiter."""
    from app.rate_limit import limiter
    limiter.reset()


@pytest.fixture
def db_session():
    """A fresh SQLAlchemy session per test, against the shared temp DB. Not
    wrapped in a transaction-rollback (this DB is throwaway/session-scoped,
    not a shared fixture other tests read concurrently) -- tests that write
    rows are responsible for their own cleanup, same discipline
    test_ldap_auth.py's _isolate_ldap_state already follows."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db_session):
    """Factory fixture: `make_user(role="clinician")` -> a persisted
    models.User with a known plaintext password stashed on
    `user.plaintext_password` (convenience for a subsequent login POST --
    never a real column, just an attribute on the Python object). Every
    user created through this factory is deleted again at teardown, so
    tests can run in any order without accumulating rows.

        clinician = make_user(role="clinician", facility="Main Hospital")
        resp = test_client.post("/auth/login", data={
            "username": clinician.email, "password": clinician.plaintext_password,
        })
    """
    created: list[models.User] = []

    def _make(role: str = "clinician", password: str = "TestPass123!", **overrides):
        email = overrides.pop("email", None) or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        full_name = overrides.pop("full_name", role.replace("_", " ").title())
        user = models.User(
            email=email,
            hashed_password=auth_module.hash_password(password),
            full_name=full_name,
            role=role,
            **overrides,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        user.plaintext_password = password
        created.append(user)
        return user

    yield _make

    for user in created:
        row = db_session.query(models.User).filter_by(id=user.id).first()
        if row is not None:
            db_session.delete(row)
    db_session.commit()


def _facility(label="Facility"):
    """A fresh, collision-proof facility name. RolePagePermission is
    unique per (facility_name, role) and gets lazily-created as a side
    effect of any authenticated request through a page-gated router (see
    app/permissions.py::get_or_create_role_permission). This DB is
    session-scoped and shared across every test module (db_session above
    has no per-test rollback), so a literal facility name like "Facility A"
    reused for the same role across files/tests risks a stale accumulated
    row -- or, worse, a UNIQUE-constraint collision with another test file
    that inserts its own row for that exact (facility, role) pair
    unconditionally. Extracted from test_ancillary.py/test_dental.py's
    byte-for-byte-identical copies (2026-09-13, P3.3 housekeeping -- both
    files' own comments flagged this duplication as due for extraction
    once a third P3.x test file needed it)."""
    return f"{label} {uuid.uuid4().hex[:8]}"


def _make_patient(db_session, **overrides):
    """Bare-minimum persisted models.Patient for a router test that only
    needs a valid patient_id, not a full clinical record. Same extraction
    note as _facility above."""
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Test Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


# A genuine 4x4 white PNG (Pillow-decodable) -- required by
# save_signature_from_b64 -> _persist_signature_bytes -> _validate_png_bytes
# on the FIRST sign-off call from a user with no saved signature yet. Same
# extraction note as _facility above.
_TEST_SIGNATURE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGP8//8/AwwwwVl4"
    "OQCWbgMF7ZjH1AAAAABJRU5ErkJggg=="
)


@pytest.fixture
def auth_headers(test_client):
    """`auth_headers(user)` -> {"Authorization": "Bearer ..."} by actually
    logging in through POST /auth/login (not by hand-minting a token), so a
    test exercises the real login path rather than assuming
    create_access_token's internals."""

    def _headers(user: models.User) -> dict:
        resp = test_client.post(
            "/auth/login",
            data={"username": user.email, "password": user.plaintext_password},
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _headers
