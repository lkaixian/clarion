"""Black-box QA harness for CLARION (tender the tender reference).

Executes the written suite in `healthcare/Security & Stability Test Suite.md`
without reading application source: the stack is booted as a subprocess
(SQLite demo topology, exactly as the 2026-09-16 run report did) and every
test observes behaviour only through HTTP, raw sockets, or the throwaway DB file.

Rules encoded here (from the run report's method notes):
- login contract is OAuth2 *form* (username=/password= urlencoded)
- replay tests must use STATELESS httpx calls (a cookie-jar client silently
  presents the rotated refresh cookie and inverts every assertion)
- demo credentials are constructed at RUNTIME, never written literally
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

_IS_WIN = os.name == "nt"
_VENV_PY = BACKEND_DIR / ("venv/Scripts/python.exe" if _IS_WIN else "venv/bin/python")
PY = _VENV_PY if _VENV_PY.exists() else Path(sys.executable)

QA_DB_NAME = "_qa_blackbox.db"
QA_ROUNDTRIP_DB_NAME = "_qa_blackbox_roundtrip.db"
_PW_SUFFIX = "12" + "3"  # demo suffix, built at runtime — never a literal in this file
ROLES = ("admin", "clinician", "pharmacist", "receptionist", "patient")


def demo_email(role: str) -> str:
    return f"{role}@clarion.demo"


def demo_password(role: str) -> str:
    return role + _PW_SUFFIX


def build_env() -> dict:
    """Subprocess env for seed/uvicorn/alembic against a throwaway SQLite DB."""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///./{QA_DB_NAME}"
    env["APP_ENV"] = "demo"
    env.setdefault("DEMO_MODE", "demo")
    env["CLARION_STORAGE_BACKEND"] = "local"
    env["LOG_FORMAT"] = "json"
    env["CLARION_DISABLE_LOCAL_AI"] = "1"
    # SECRET_KEY / OTP_HMAC_KEY come from backend/.env (required, no fallback)
    return env


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _remove_db(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(db_path) + suffix)
        for attempt in range(5):  # Windows: the dying server may hold the lock briefly
            try:
                p.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(1.0)


class Stack:
    """The running backend process + everything a test needs to poke it."""

    def __init__(self, port: int, log_path: Path, db_path: Path, env: dict):
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.log_path = log_path
        self.db_path = db_path
        self.env = env
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._log_handle = open(self.log_path, "ab")
        self.proc = subprocess.Popen(
            [
                str(PY), "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                # 1 worker: the 4-gunicorn-workers-on-one-SQLite-file race is a
                # POSIX-flock fix and the documented Docker/demo topology — it is
                # a docker-marked case, not a Windows-local one.
                "--workers", "1",
                "--log-level", "warning",
            ],
            cwd=BACKEND_DIR,
            env=self.env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        if getattr(self, "_log_handle", None):
            self._log_handle.close()

    def restart(self) -> None:
        self.stop()
        time.sleep(1.0)
        self.start()
        self.wait_healthy(timeout=180)

    def wait_healthy(self, timeout: float = 180) -> None:
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(
                    f"backend exited rc={self.proc.returncode}; log tail:\n"
                    + self.log_tail(4000)
                )
            try:
                r = httpx.get(f"{self.base_url}/healthz", timeout=3)
                if r.status_code == 200:
                    return
            except Exception as e:  # noqa: BLE001
                last_err = e
            time.sleep(1.0)
        raise RuntimeError(
            f"backend never became healthy: {last_err}; log tail:\n" + self.log_tail(4000)
        )

    def log_tail(self, n: int = 2000) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except OSError:
            return "<no log>"


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    """Boot once per session: fresh throwaway DB -> seed -> uvicorn."""
    db_path = BACKEND_DIR / QA_DB_NAME
    _remove_db(db_path)
    log_dir = tmp_path_factory.mktemp("qa_blackbox")
    env = build_env()

    seed = subprocess.run(
        [str(PY), "seed.py"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=900,
    )
    assert seed.returncode == 0, (
        "seed.py failed against the throwaway DB:\n"
        + (seed.stdout + seed.stderr)[-4000:]
    )

    st = Stack(port=_free_port(), log_path=log_dir / "uvicorn.log",
               db_path=db_path, env=env)
    st.start()
    st.wait_healthy(timeout=180)
    yield st
    st.stop()
    _remove_db(db_path)
    _remove_db(BACKEND_DIR / QA_ROUNDTRIP_DB_NAME)


def login(stack_or_url, username: str, password: str, retries: int = 2) -> dict:
    """OAuth2-form login. Builds credentials at runtime; retries once past a
    per-IP 429 (a burst test may have just consumed this minute's bucket)."""
    base = getattr(stack_or_url, "base_url", stack_or_url)
    last = None
    for attempt in range(retries + 1):
        r = httpx.post(
            f"{base}/auth/login",
            data={"username": username, "password": password},
            timeout=20,
        )
        if r.status_code == 200:
            body = r.json()
            return {
                "status": 200,
                "access_token": body.get("access_token"),
                "refresh_token": body.get("refresh_token"),
                "set_cookies": r.headers.get_list("set-cookie"),
                "body": body,
            }
        last = r
        if r.status_code == 429 and attempt < retries:
            time.sleep(65)
    return {
        "status": last.status_code if last is not None else -1,
        "access_token": None,
        "refresh_token": None,
        "set_cookies": last.headers.get_list("set-cookie") if last is not None else [],
        "body": last.json() if last is not None else {},
    }


@pytest.fixture(scope="session")
def tokens(stack):
    """Log in every demo role ONCE, at session start, before any burst test
    can poison the per-IP login bucket."""
    out = {}
    for role in ROLES:
        res = login(stack, demo_email(role), demo_password(role))
        assert res["status"] == 200, f"demo login failed for {role}: {res['status']}"
        out[role] = res
    return out


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class OpenApi:
    """Black-box endpoint discovery via /openapi.json — no source needed."""

    def __init__(self, spec: dict):
        self.paths = spec.get("paths", {})

    def find(self, *needles: str, method: str = "get", exclude=()) -> list[str]:
        hits = []
        for path, ops in self.paths.items():
            low = path.lower()
            if all(n.lower() in low for n in needles) and not any(
                x.lower() in low for x in exclude
            ):
                if method.lower() in (k.lower() for k in ops.keys()):
                    hits.append(path)
        return hits


@pytest.fixture(scope="session")
def openapi(stack) -> OpenApi:
    r = httpx.get(f"{stack.base_url}/openapi.json", timeout=15)
    assert r.status_code == 200, "openapi.json unavailable — suite cannot discover endpoints"
    return OpenApi(r.json())


def pytest_addoption(parser):
    parser.addoption("--run-docker", action="store_true", default=False,
                     help="also run cases that need the composed Docker stack")
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="also run slow gates (alembic round-trip etc.)")


def pytest_configure(config):
    for name, desc in (
        ("docker", "needs the composed Docker stack (proxy/TLS/networks/MinIO/MariaDB)"),
        ("slow", "multi-minute gate; opt in with --run-slow"),
        ("burst", "deliberately trips per-IP rate limits; ordered last on purpose"),
    ):
        config.addinivalue_line("markers", f"{name}: {desc}")


def pytest_collection_modifyitems(config, items):
    skip_docker = pytest.mark.skip(reason="needs the composed Docker stack (qa/blackbox README)")
    skip_slow = pytest.mark.skip(reason="slow gate — run with --run-slow")
    for item in items:
        if "docker" in item.keywords and not config.getoption("--run-docker"):
            item.add_marker(skip_docker)
        if "slow" in item.keywords and not config.getoption("--run-slow"):
            item.add_marker(skip_slow)
