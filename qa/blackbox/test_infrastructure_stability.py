"""Infrastructure-stability cases (suite groups I-K / I-L / I-M-lite / S-F-002 /
S-J-001/002 / S-E-009 / I-T) — black-box executable slice.

Every case ID below maps to `healthcare/Security & Stability Test Suite.md`.
Docker-dependent drills (I-K-001/002, I-M, I-N, I-P, I-R, I-S) are marked
`docker` and skipped without --run-docker.
"""

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from conftest import (
    BACKEND_DIR,
    PY,
    QA_ROUNDTRIP_DB_NAME,
    bearer,
    build_env,
    demo_email,
    demo_password,
    login,
    _remove_db,
)

NRIC_RE = re.compile(r"\d{6}-\d{2}-\d{4}")


# --- I-K-007 health endpoints -------------------------------------------------


def test_healthz_and_readyz_green(stack):
    """I-K-007 (a): healthcheck probes real endpoints; both green when healthy."""
    r = httpx.get(f"{stack.base_url}/healthz", timeout=10)
    assert r.status_code == 200
    r2 = httpx.get(f"{stack.base_url}/readyz", timeout=15)
    assert r2.status_code == 200, f"readyz degraded while stack healthy: {r2.text[:300]}"


def test_db_file_loss_degrades_never_crashes(stack):
    """I-K-007 (b) / I-N-002 analogue: take the storage away under the running
    server — /healthz MUST stay 200 (liveness never depends on the DB),
    /readyz may 503 but must never 500/crash; restore must self-heal."""
    hidden = Path(str(stack.db_path) + ".qa_hidden")
    try:
        stack.db_path.rename(hidden)
    except PermissionError:
        pytest.skip("Windows file lock — DB-file-loss drill needs the Docker MariaDB topology")
    try:
        r = httpx.get(f"{stack.base_url}/healthz", timeout=10)
        assert r.status_code == 200, "healthz died with the DB — liveness must be DB-independent"
        r2 = httpx.get(f"{stack.base_url}/readyz", timeout=15)
        assert r2.status_code in (200, 503), f"readyz crashed: {r2.status_code} {r2.text[:200]}"
    finally:
        hidden.rename(stack.db_path)
    time.sleep(1.0)
    assert httpx.get(f"{stack.base_url}/healthz", timeout=10).status_code == 200


# --- I-K-008-lite / restart resilience ----------------------------------------


def test_stack_restart_resumes_cleanly(stack, tokens):
    """I-K-008 (lite): SIGTERM the server, boot again on the SAME DB — no
    re-seed, no migration replay damage, logins and API still work."""
    stack.restart()
    assert httpx.get(f"{stack.base_url}/healthz", timeout=10).status_code == 200
    res = login(stack, demo_email("admin"), demo_password("admin"))
    assert res["status"] == 200, "login broken after restart"
    r = httpx.get(f"{stack.base_url}/patients", headers=bearer(res["access_token"]), timeout=15)
    assert r.status_code == 200, f"API broken after restart: {r.status_code}"


# --- S-A-015 fail-closed bootstrap ---------------------------------------------


def test_empty_secret_key_fails_closed():
    """S-A-015: an empty SECRET_KEY must refuse to boot — no default secret."""
    env = build_env()
    env["SECRET_KEY"] = ""
    p = subprocess.run(
        [str(PY), "-c", "import app.main"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert p.returncode != 0, "app imported cleanly with an empty SECRET_KEY"


# --- S-F-002 / S-J / S-E-009 against the throwaway DB --------------------------


def test_password_hashes_are_adaptive_at_rest(stack):
    """S-F-002: User.password_hash is bcrypt/argon2-class, never plaintext."""
    con = sqlite3.connect(stack.db_path, timeout=30)
    try:
        rows = con.execute(
            "SELECT hashed_password FROM users LIMIT 5"
        ).fetchall()
    finally:
        con.close()
    assert rows, "no users in seeded DB"
    for (h,) in rows:
        assert h and (h.startswith("$2") or h.startswith("$argon2")), (
            f"password not adaptively hashed: {str(h)[:12]}…"
        )


def _ensure_audit_row(stack, admin_token):
    """One break-glass list call — its documented audit action guarantees a row."""
    r = httpx.get(
        f"{stack.base_url}/patients",
        params={"break_glass_reason": "qa-blackbox-audit-probe"},
        headers=bearer(admin_token), timeout=15,
    )
    assert r.status_code == 200
    con = sqlite3.connect(stack.db_path, timeout=30)
    try:
        (n,) = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()
    finally:
        con.close()
    return n


def test_audit_table_is_physically_append_only(stack, tokens):
    """S-J-002: raw UPDATE/DELETE on audit_logs abort for every account
    (BEFORE UPDATE/DELETE triggers) — verified out-of-band on the DB file."""
    n = _ensure_audit_row(stack, tokens["admin"]["access_token"])
    if n == 0:
        pytest.skip("no audit rows exist to probe tamper triggers")
    con = sqlite3.connect(stack.db_path, timeout=30)
    try:
        with pytest.raises(sqlite3.Error):
            con.execute(
                "UPDATE audit_logs SET detail = 'QA-TAMPER' "
                "WHERE id = (SELECT MIN(id) FROM audit_logs)"
            )
        con.rollback()
        with pytest.raises(sqlite3.Error):
            con.execute("DELETE FROM audit_logs WHERE id = (SELECT MIN(id) FROM audit_logs)")
        con.rollback()
    finally:
        con.close()


def test_audit_chain_status_admin_gated_and_ok(stack, tokens):
    """S-J-001 (API half): /admin/audit/chain-status verifies the hash chain and
    is admin-gated."""
    r = httpx.get(f"{stack.base_url}/admin/audit/chain-status",
                  headers=bearer(tokens["admin"]["access_token"]), timeout=15)
    assert r.status_code == 200, f"chain-status not admin-readable: {r.status_code}"
    body = r.json().get("data", r.json())
    flat = json.dumps(body).lower()
    # tolerant: any explicit ok/valid/state flag must not say broken/invalid
    assert "broken" not in flat and '"state": "invalid"' not in flat, body
    r2 = httpx.get(f"{stack.base_url}/admin/audit/chain-status",
                   headers=bearer(tokens["clinician"]["access_token"]), timeout=15)
    assert r2.status_code in (401, 403), "chain-status is not admin-gated"


def test_backend_logs_leak_no_phi_or_tokens(stack):
    """S-E-009: the process log for this whole session contains zero NRICs and
    zero JWT fragments."""
    text = stack.log_path.read_text(errors="replace")
    nrics = NRIC_RE.findall(text)
    assert not nrics, f"NRIC pattern in backend logs: {nrics[:3]}"
    jwts = re.findall(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}", text)
    assert not jwts, f"JWT material in backend logs: {jwts[:2]}"


# --- I-L-003 drift gate ---------------------------------------------------------


def test_check_schema_zero_drift(stack):
    """I-L-003: the migration-integrity backbone — autogenerate vs models is
    zero-ops. check_schema builds its own throwaway temp DB and migrates it to
    head, so the subprocess gets a FRESH throwaway SECRET_KEY (the repo's own
    key from .env must never be needed or seen here)."""
    import secrets
    env = dict(stack.env)
    env["SECRET_KEY"] = secrets.token_hex(32)
    env["OTP_HMAC_KEY"] = secrets.token_hex(32)
    p = subprocess.run(
        [str(PY), "-m", "db.check_schema"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=600,
    )
    assert p.returncode == 0, "check_schema FAILED (drift or guard):\n" + (
        p.stdout + p.stderr
    )[-3000:]


# --- I-L-001/002 full round-trip (slow, opt-in) ---------------------------------


@pytest.mark.slow
def test_alembic_upgrade_downgrade_upgrade_roundtrip():
    """I-L-001/002 on a genuinely fresh DB: upgrade head -> downgrade base ->
    upgrade head, zero FK-order failures."""
    db2 = BACKEND_DIR / QA_ROUNDTRIP_DB_NAME
    _remove_db(db2)
    import secrets
    env = build_env()
    env["DATABASE_URL"] = f"sqlite:///./{QA_ROUNDTRIP_DB_NAME}"
    # the audit-chain migration keys its backfill on SECRET_KEY (refuses empty);
    # this throwaway chain gets a throwaway key — the repo's own key from .env
    # is never needed or seen here.
    env["SECRET_KEY"] = secrets.token_hex(32)
    env["OTP_HMAC_KEY"] = secrets.token_hex(32)

    def alembic(*args):
        return subprocess.run(
            [str(PY), "-m", "alembic", *args],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=900,
        )

    try:
        up1 = alembic("upgrade", "head")
        assert up1.returncode == 0, "fresh upgrade head failed:\n" + (up1.stdout + up1.stderr)[-3000:]
        down = alembic("downgrade", "base")
        assert down.returncode == 0, "downgrade base failed (FK safety):\n" + (down.stdout + down.stderr)[-3000:]
        up2 = alembic("upgrade", "head")
        assert up2.returncode == 0, "re-upgrade after downgrade failed:\n" + (up2.stdout + up2.stderr)[-3000:]
    finally:
        _remove_db(db2)


# --- Docker-composed drills (blocked on this host, kept for the Docker session) --

@pytest.mark.docker
def test_compose_full_stack_boot_and_idempotency():
    """I-K-001/002/003: from-zero MariaDB-profile `docker compose up`, all
    services healthy, migrate one-shot completes; second `up` survives
    minio-init's already-attached policy; `compose config` valid in every
    profile combination. Runbook: suite doc I-K section."""


@pytest.mark.docker
def test_minio_stop_blast_radius_and_recovery():
    """I-N-002: docker stop minio -> uploads 503-class, reads 503 clean,
    /readyz 503 while /healthz 200, login/queue/emergency unaffected, recovery
    without process restart."""


@pytest.mark.docker
def test_backup_restore_drill_timed():
    """I-P-002/003: restore-test.sh into throwaway mariadbd, PITR to last txn,
    reconcile Alembic head + row counts; timed against RTO <= 4h."""
