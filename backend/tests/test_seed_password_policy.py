"""Security Audit finding H3 — seed.py's demo passwords
(admin123/clinician123/etc.) must never leak into a real deployment.
Runs backend/seed.py as a real subprocess (it's a standalone script with
module-level side effects, not an importable function -- this is the
faithful way to test its actual behavior) against a throwaway SQLite file,
once in each mode, and inspects both stdout and the resulting DB rows.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from passlib.context import CryptContext
from sqlalchemy import create_engine, text

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_SEEDED_EMAILS = [
    "admin@clarion.demo",
    "clinician@clarion.demo",
    "pharmacist@clarion.demo",
    "receptionist@clarion.demo",
    "patient@clarion.demo",
]


def _run_seed(env_overrides: dict) -> tuple[str, Path]:
    fd, path_str = tempfile.mkstemp(suffix=".db", dir=_BACKEND_DIR)
    os.close(fd)  # Windows can't unlink a still-open file descriptor
    db_fd_path = Path(path_str)
    db_fd_path.unlink()  # seed.py/alembic create it fresh
    # Inherit the full parent environment (Windows subprocesses can need
    # more than PATH -- SYSTEMROOT etc. -- for the interpreter to even
    # start) rather than constructing a minimal one from scratch; only
    # override what this test actually needs to control. Explicitly drop
    # any DEMO_MODE the outer shell might have set so env_overrides={}
    # reliably means "the production path", not an inherited leftover.
    env = dict(os.environ)
    env.pop("DEMO_MODE", None)
    env.pop("APP_ENV", None)
    env.update({
        "DATABASE_URL": "sqlite:///" + str(db_fd_path).replace("\\", "/"),
        "SECRET_KEY": "test-only-secret-key-not-for-any-real-deployment",
        "OTP_HMAC_KEY": "test-only-otp-hmac-key-not-for-any-real-deployment",
        **env_overrides,
    })
    result = subprocess.run(
        [sys.executable, "seed.py"],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"seed.py failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    return result.stdout, db_fd_path


def _query_users(db_path: Path):
    engine = create_engine("sqlite:///" + str(db_path).replace("\\", "/"))
    placeholders = ",".join(f":email{i}" for i in range(len(_SEEDED_EMAILS)))
    params = {f"email{i}": email for i, email in enumerate(_SEEDED_EMAILS)}
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT email, hashed_password, must_change_password FROM users WHERE email IN ({placeholders})"),
            params,
        ).fetchall()
    engine.dispose()
    return {r[0]: {"hashed_password": r[1], "must_change_password": bool(r[2])} for r in rows}


@pytest.fixture(scope="module")
def demo_seed_run():
    stdout, db_path = _run_seed({"APP_ENV": "demo"})
    try:
        yield stdout, _query_users(db_path)
    finally:
        db_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def production_seed_run():
    stdout, db_path = _run_seed({})  # no APP_ENV=demo -- the production path
    try:
        yield stdout, _query_users(db_path)
    finally:
        db_path.unlink(missing_ok=True)


def test_demo_mode_uses_known_passwords_no_forced_change(demo_seed_run):
    stdout, users = demo_seed_run
    assert "admin@clarion.demo / admin123" in stdout
    assert "GENERATED SEED CREDENTIALS" not in stdout

    admin = users["admin@clarion.demo"]
    assert admin["must_change_password"] is False
    assert _pwd_context.verify("admin123", admin["hashed_password"])


def test_production_mode_generates_random_passwords_forces_change(production_seed_run):
    stdout, users = production_seed_run
    assert "GENERATED SEED CREDENTIALS" in stdout
    assert "admin123" not in stdout  # the demo password must never appear here
    for email in _SEEDED_EMAILS:
        assert f"Login: {email} /" not in stdout  # the demo-mode line format must not appear

    for email in _SEEDED_EMAILS:
        row = users[email]
        assert row["must_change_password"] is True
        # The stored hash must NOT validate against the well-known demo
        # password -- this is the actual regression H3 is about.
        demo_password_guess = email.split("@")[0] + "123"
        assert not _pwd_context.verify(demo_password_guess, row["hashed_password"])


def test_production_mode_printed_passwords_actually_match_stored_hashes(production_seed_run):
    """The password printed to the operator must be the SAME one that was
    actually hashed and stored -- not a decoy/placeholder."""
    stdout, users = production_seed_run
    printed = dict(re.findall(r"^\s*(\S+@clarion\.demo) / (\S+)\s*$", stdout, re.MULTILINE))
    assert set(printed.keys()) == set(_SEEDED_EMAILS)
    for email, plaintext in printed.items():
        assert _pwd_context.verify(plaintext, users[email]["hashed_password"])


def test_generated_passwords_meet_the_length_policy(production_seed_run):
    """auth.generate_temp_password() must satisfy schemas.MIN_PASSWORD_LENGTH
    -- if the policy is ever raised further, seed.py must not silently fall
    below it."""
    stdout, _ = production_seed_run
    printed = dict(re.findall(r"^\s*(\S+@clarion\.demo) / (\S+)\s*$", stdout, re.MULTILINE))
    from app.schemas import MIN_PASSWORD_LENGTH
    for plaintext in printed.values():
        assert len(plaintext) >= MIN_PASSWORD_LENGTH
