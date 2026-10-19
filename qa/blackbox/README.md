# qa/blackbox — CLARION black-box executable test suite

Executable slice of **`healthcare/Security & Stability Test Suite.md`** (the
209-case doc-only suite). Like the written suite, it was authored **without
reading application source**: the stack is booted as a subprocess against a
throwaway SQLite DB and every case observes behaviour through HTTP, raw
sockets, or that DB file only. Endpoint paths are discovered at runtime from
`/openapi.json`, so the suite survives refactors and stays valid for the
mandated PHP/CI4 port.

## Run

```bash
# from repo root, using the backend venv
backend/venv/Scripts/python -m pytest qa/blackbox -v          # Windows
backend/venv/bin/python -m pytest qa/blackbox -v              # POSIX

backend/venv/Scripts/python -m pytest qa/blackbox -v --run-slow    # + alembic round-trip
backend/venv/Scripts/python -m pytest qa/blackbox -v --run-docker  # + composed-stack drills
```

The harness (`conftest.py`) seeds a scratch `_qa_blackbox.db` via `seed.py`,
boots `uvicorn app.main:app` on a free localhost port (SQLite demo topology,
1 worker — the 4-worker race case is Docker/POSIX-only), and tears both down.
Nothing in `backend/` is modified; `.env` supplies `SECRET_KEY`/`OTP_HMAC_KEY`.

## Files

| File | Suite groups | Cases |
|---|---|---|
| `test_infrastructure_stability.py` | I-K-007/008, I-L-001/002/003, I-T smoke, S-A-015, S-F-002, S-J-001/002, S-E-009, docker: I-K-001/002, I-N-002, I-P-002/003 | 13 |
| `test_network_penetration.py` | S-H-005/007/008, S-D-010, S-I-007, docker: S-F-008 + S-H-001..006 edge matrix | 10 |
| `test_security_compromise.py` | S-A-007/008/009/012/013/014/015*, S-A-019, S-B-001/002, S-C-001/002, S-D-001/008/012, S-G-001, S-I-001/002/003 | 17 |

(*S-A-015 lives in the infrastructure file.)

## Method notes (from the 2026-09-16 run report — do not relearn these)

- Login contract is **OAuth2 form** (`username=`/`password=` urlencoded).
- Replay tests use **stateless** `httpx.post` — a cookie-jar client silently
  presents the rotated refresh cookie and inverts every assertion.
- Demo credentials are **built at runtime** (`role + suffix`), never literals.
- Burst tests (`@pytest.mark.burst`, names prefixed `test_zz`/`test_zzz`) run
  **last** so they don't poison the shared per-IP rate-limit buckets; session
  logins happen once, at session start, before any burst.
- The per-account lockout (5 strikes / 20 min) is real: probes use dedicated
  fake accounts, and the enumeration test spends exactly one strike.

## Known environment limits (Windows host, no Docker)

- 4-worker SQLite race (I-K-004), edge TLS/headers/port surface (S-F-008,
  S-H-001..006), MinIO/MariaDB/Orthanc/backup drills (I-M/I-N/I-P), and the
  Branch WAN drills (I-R) need the composed stack — `--run-docker` placeholders
  document the runbook in each case.
- The P2.9 audit triggers are asserted on the SQLite scratch DB; the MariaDB
  `SIGNAL`-trigger + `b2d7e4a9c1f6` run remains the owed Docker-session item.
