# P5.2 — Load testing

the tender ("secure, scalable, performance-optimised configuration").
Locust scenarios simulating CLARION's realistic clinic traffic — see `locustfile.py`'s
own docstring for the user mix and how it maps to the ~23k-user/~150-encounters-per-day
population in `healthcare/On-Prem Architecture.md` (a literal 23,000 concurrent
connections is not the real target; see "Scope and honest limitations" below).

## Run it

```bash
pip install -r backend/requirements-dev.txt   # adds locust
bash backend/db/mariadb/generate-encryption-key.sh   # once
docker compose --env-file .env.docker --profile mariadb up -d mariadb redis
docker compose --env-file .env.docker --profile mariadb --profile migrate run --rm migrate
docker compose --env-file .env.docker --profile mariadb up -d --build backend
docker compose --env-file .env.docker exec -e APP_ENV=demo backend python /app/seed.py
locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
    --headless -u 18 -r 1 -t 3m --csv=backend/loadtest/results/run1
```

Backend's port isn't published by default (`docker-compose.yml`'s P1.9 network
split) — a local `docker-compose.override.yml` with a `ports: ["8000:8000"]`
override on `backend` (untracked, delete when done) is the sanctioned way to hit
it directly for a test like this; `docs/deployment.md` documents the same pattern.

## What this found and fixed

Standing the MariaDB-backed stack up to actually run this test (not the SQLite
demo path) surfaced three real, previously-undiscovered bugs — none are
load/capacity bugs themselves, but load-testing setup is exactly what exercises
"first real run of the full stack cold" and caught them:

1. **`docker-compose.yml`'s `mariadb` service silently created ZERO database
   accounts.** P5.1 added the `clarion_metrics` account to `10-accounts.sh`'s
   required-var check but never passed `MARIADB_METRICS_PASSWORD` through in
   the compose service's `environment:` block — the script aborts on any
   missing required var *before* creating anything, so `clarion_app` /
   `clarion_migrate` / `clarion_report` never existed either, on a from-scratch
   volume. Fixed by adding the missing env line.
2. **`migrate` one-shot service ran `alembic upgrade head` from the wrong
   directory and silently did nothing** ("No 'script_location' key found").
   `backend/Dockerfile`'s runtime image sets `WORKDIR /app/data` (so the
   `backend` service's relative SQLite path resolves there); alembic only
   looks for `alembic.ini` in the CWD, with no `-c` flag on the command. Fixed
   with `working_dir: /app` on the `migrate` service.
3. **The P1.2b `a1b2c3d4e5f6` migration (MariaDB `DATETIME(6)` precision,
   written 2026-08-30) failed on a genuinely fresh `alembic upgrade head`**
   with `Table 'audit_chain_state' doesn't exist`. It walked the *live*
   `app.models` ORM metadata instead of reflecting the database at its actual
   position in the migration chain, so every table added after it was written
   (audit_chain_state, security_alerts, ...) got swept in even though this
   revision runs before those tables' own CREATE TABLE migrations. This is the
   exact "P2.9 leftover" the roadmap had flagged as owed (a MariaDB run had
   never been done end-to-end from empty) — turned out a different, earlier
   migration broke first. Fixed by reflecting the live bind instead of
   importing `app.models`.
4. **P2.9's `audit_logs` append-only trigger failed with error 1419**
   ("You do not have the SUPER privilege and binary logging is enabled").
   MariaDB refuses `CREATE TRIGGER` from a non-`SUPER` account (`clarion_migrate`,
   deliberately not `SUPER` — least privilege) while binlogging is on, to guard
   against non-deterministic routines breaking `STATEMENT`-replicated replicas.
   Irrelevant here (`--binlog-format=ROW` already), so the standard remedy —
   `--log-bin-trust-function-creators=1` on the server — was added.

A fifth, more significant finding came from the load test itself:

5. **slowapi's rate limiting had two independent, compounding bugs**, both
   security-relevant, not just performance:
   - **Multi-worker bypass.** slowapi/`limits`' default storage is in-process
     memory; gunicorn runs 4 worker processes (`backend/Dockerfile`), so each
     kept its own independent counter for the same key. A 100-request burst of
     wrong-password `POST /auth/login` (limit "20/minute") only started
     429-ing after ~50+ attempts, not 20 — the opposite of fail-safe for the
     exact brute-force/credential-spray case Security Audit M1 named. Fixed:
     `app/rate_limit.py`'s `Limiter` now points at the `redis` container this
     stack already provisions (previously unused) via `storage_uri`, so every
     worker shares one counter.
   - **`SlowAPIMiddleware` was a complete no-op.** Traced directly: its
     `_find_route_handler()` call returned `None` for literally every route
     (including `/auth/login`) against this app's installed fastapi/starlette
     versions, so `default_limits=["60/minute"]` was never actually enforced
     on any undecorated route — most of the API (dashboard, patients,
     pharmacy, reception, ...) had no rate limiting at all beyond auth. Fixed
     with a new `enforce_rate_limits` FastAPI dependency (wired globally via
     `FastAPI(dependencies=[...])`) that reuses the one code path already
     confirmed working (the explicit-decorator path), reading the matched
     route off `request.scope["route"]` instead of the broken
     `_find_route_handler`. `SlowAPIMiddleware` itself removed as dead weight.

   Both fixed together, verified with repeatable bursts (20-request login
   burst → exactly 10 succeed then 10 429; 75-request GET burst against an
   undecorated route → exactly 60 succeed then 15 429) and against the full
   531-test backend suite (no regressions — `_reset_rate_limiter` in
   `tests/conftest.py` already resets the shared `Limiter` between tests, so
   this was a safe change to make blind to test-suite side effects, verified
   after the fact anyway).

   **voltagent security-auditor caught a sixth bug this introduced, CRITICAL,
   before it shipped:** with no `in_memory_fallback_enabled=True`, a Redis
   outage didn't just degrade rate limiting — since `enforce_rate_limits` is
   a *global* FastAPI dependency, slowapi's default behavior on a storage
   error is to re-raise, turning a Redis blip into a 500 on **every request
   site-wide**, including `GET /healthz` (whose own docstring promises a
   dependency-free liveness answer) and the unauthenticated emergency-scan
   endpoints — the one part of this "Emergency-first" system explicitly
   designed to stay reachable no matter what else is down. Fixed with
   `in_memory_fallback_enabled=True` (degrades to the pre-Redis
   per-worker-undercounting behavior for the outage's duration, then
   recovers automatically); verified live by actually stopping the `redis`
   container and confirming `/healthz` and `POST /auth/login` both still
   return 200, then restarting it and confirming recovery.

## Tuning applied (the other half of "tune pools + workers")

- **`backend/Dockerfile`**: `--timeout 60` (the CPU-bound local-LLM/whisper
  paths — CDS hint, voice-to-soap, narrative — risked gunicorn SIGKILLing a
  worker mid-inference at the 30s default on hardware with no GPU guarantee),
  `--graceful-timeout 30`, `--max-requests 2000 --max-requests-jitter 200`
  (periodic worker recycling, jittered so all 4 don't restart at once).
  Corrected a stale comment claiming `max_overflow=10` (database.py has used
  30 since P1.3; the Dockerfile comment was never updated).
- DB pool math (`database.py`, unchanged, re-verified): `pool_size=10 +
  max_overflow=30` × 4 workers = 160 connections, under MariaDB's
  `max_connections=200` with headroom for `clarion_migrate`/`clarion_report`/
  exporters/root — this test never got close to exercising that ceiling (see
  below), so it stands as verified-by-math, not verified-by-load.

## Results (`run2`, 18 users, 1/s ramp, 3 minutes, real MariaDB 11.4)

1238 requests, 6.9 req/s aggregate. Every failure was an intentional,
correctly-firing rate limit (`/patients/announcements` and `/booking-options`
hit their per-route 60/min ceiling — expected, `PatientUser` is the heaviest-
weighted class); **zero database errors, zero timeouts, zero connection-pool
exhaustion signals.** Median latency 9-28ms across every route; `POST
/auth/login` medians ~220ms (bcrypt/argon2 hashing is deliberately slow — not
a regression, not DB-bound). Full CSVs in `results/run2_*.csv`.

## Scope and honest limitations

This is a **single test-machine run**, so every request shares one apparent
client IP. That's exactly what the P5.2-turned-up rate-limit fixes above now
correctly defend against — which means this test could not, and should not
try to, push the DB pool or gunicorn workers anywhere near their real ceiling:
18 concurrent users with 1-4s think-time between requests never has more than
a handful of connections open at once, nowhere near the 160-connection pool
math above. A real capacity ceiling test needs one of:

- a **distributed load generator** (multiple real source IPs — e.g. Locust's
  own distributed/worker mode run from several machines or cloud regions), or
- a **deliberately-authorized rate-limit bypass**, run only in a controlled
  staging environment with an operator's explicit sign-off (this session's
  own attempt to widen `FORWARDED_ALLOW_IPS` for exactly this purpose was
  correctly declined by Claude Code's own safety controls as a security-
  weakening action — the right call; that decision is not this repo's to make
  unilaterally).

What this run *does* support: the app, DB pool, and gunicorn tuning show no
signs of strain at the traffic level a single origin can generate, and the
security fixes above are now demonstrably load-bearing rather than
decorative. Recommended next step if a harder capacity number is needed:
re-run this same locustfile from Locust's distributed mode against a staging
deployment, with the University's own sign-off to temporarily raise or bypass the
per-IP limits for that one authorized window.
