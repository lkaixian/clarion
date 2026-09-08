# CLARION -- Container Deployment (demo topology)

Roadmap tasks **P1.11 + P1.9**. This is the **demo-capable, single-host**
version of the on-prem stack described in `healthcare/On-Prem Architecture.md`
-- the "Single-VM fallback for the pilot via the same Compose file" line. It is
**not** the final hardened production deployment (no Docker secrets, MinIO
console reachable on the internal network, Orthanc auth disabled). As of P1.9
there **is** a TLS edge proxy (Caddy) -- it is the only service that publishes
host ports; `web` and `backend` sit behind it. The three least-privilege
MariaDB accounts (P1.3) *are* created on init, but `REQUIRE SSL` / host-scoping
wait on wiring the DB into that TLS story. See
**[What is wired now vs. TODO](#what-is-wired-now-vs-todo)**.

---

## TL;DR

```bash
cp .env.docker.example .env.docker
# edit .env.docker: set SECRET_KEY and OTP_HMAC_KEY (required), change passwords
python -c "import secrets; print(secrets.token_hex(32))"   # run twice

docker compose --env-file .env.docker config          # validate
docker compose --env-file .env.docker up -d --build    # start

# first run only -- seed demo data into the fresh SQLite volume:
docker compose exec backend python /app/seed.py

# demo TLS uses Caddy's local CA -- trust it to drop the browser warning:
docker compose exec proxy caddy trust
```

- Web console: <https://localhost/>  (HTTP -> HTTPS auto-redirect)
- API:         <https://localhost/api/>  (docs at `/api/docs`)
- `backend` and `web` no longer publish host ports -- everything is via the
  proxy. For ad-hoc direct access: `docker compose run --service-ports backend`.

Stop / wipe:

```bash
docker compose down            # keep volumes (data survives)
docker compose down -v         # also delete all named volumes
```

> Add `.env.docker` to `.gitignore` before committing anything -- it holds real
> secrets. (`.gitignore` was not touched by this task.)

---

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | The whole stack. `name: clarion`. One bridge network (`172.28.0.0/16`, dynamic IPs from `.10.0/24`). |
| `.env.docker.example` | Every env var the compose file reads, with comments. Copy to `.env.docker`. |
| `proxy/Caddyfile` | The edge (P1.9). TLS termination, HTTP->HTTPS, HSTS + CSP + security headers, routes `/api/*` -> backend and the rest -> web. |
| `proxy/README.md` | Demo (`tls internal`) vs production (CAMPUS-CA cert in `proxy/certs/`) setup; cert rotation. |
| `backend/Dockerfile` | Multi-stage: `python:3.12-slim` builder venv -> slim non-root runtime, `gunicorn` + uvicorn workers. |
| `backend/.dockerignore` | Keeps `venv/`, `*.db`, `uploads/`, `backups/`, `.env`, `_debug_photos/`, tests out of the build context. |
| `web/Dockerfile` | Multi-stage: `node:20-alpine` build -> `nginx:1.27-alpine`. |
| `web/nginx.conf` | SPA fallback (`try_files ... /index.html`) + `/api` reverse proxy to `backend:8000`. |
| `web/entrypoint.sh` | Writes `window.__CLARION_API_BASE__` from `$API_BASE` into `/config.js` at container start (no rebuild to repoint the API). |
| `web/.dockerignore` | `node_modules/`, `dist/`, `.env`. |

---

## Services

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `proxy` | `caddy:2.8-alpine` | **80 / 443** | Edge (P1.9). TLS, HTTP->HTTPS, HSTS/CSP/security headers, `/api/*` -> `backend`, rest -> `web`. Fixed IP `172.28.0.2`. The **only** service with host ports. |
| `backend` | built from `./backend` | internal (8000) | FastAPI API. `gunicorn -k uvicorn_worker.UvicornWorker -w 4 app.main:app`. Non-root. Trusts `X-Forwarded-*` only from `172.28.0.2`. |
| `web` | built from `./web` | internal (8080) | React 19 / Vite console, static build served by nginx. |
| `mariadb` | `mariadb:11.4` | internal | **Provisioned, not yet used.** Target DB for the SQLite cutover (P1.3 / P1.4). |
| `minio` | `minio/minio:RELEASE.2025-04-22T22-12-26Z` | internal (9000 API / 9001 console) | S3-compatible object store for documents, signatures, medicine photos, thumbnails, DICOM. `ObjectStore` code landed (P1.6); set `CLARION_STORAGE_BACKEND=minio` + provision WORM buckets (see TODO below) to switch the backend off the local-filesystem default. |
| `redis` | `redis:7.4-alpine` | internal | Cache; later rate-limit / session / worker broker. AOF persistence on a volume. |
| `orthanc` | `orthancteam/orthanc:24.10.1` | internal (8042 HTTP+DICOMweb / 4242 DIMSE) | PACS. DICOMweb plugin on; **auth disabled (demo only)**; SQLite index for now. |
| `orthanc-postgres` | `postgres:16-alpine` | internal | PostgreSQL index for Orthanc. Wired to a volume; the Orthanc PG plugin itself is still a TODO. |

Only `proxy` publishes host ports (80/443). Two internal networks:
**`edge`** (`proxy` <-> `web`/`backend`; fixed subnet `172.28.0.0/16`, proxy
at `172.28.0.2`) and **`internal`** (`backend` <-> `mariadb`/`minio`/`redis`/
`orthanc`/`orthanc-postgres`). `backend` is on both; `web` cannot reach the
data tier. Every service has a healthcheck. Every stateful service has a named
volume: `clarion_db`, `clarion_uploads`, `mariadb_data`, `minio_data`,
`redis_data`, `orthanc_data`, `orthanc_pg_data`, `caddy_data`, `caddy_config`.

---

## How the web console finds the API

With the P1.9 edge proxy the browser talks only to Caddy: it calls
`https://<host>/api/...`, Caddy strips `/api` and forwards to `backend:8000`
on the internal network. Same origin, so no CORS. `API_BASE` stays `/api`.

`web/nginx.conf` keeps its own `/api` -> `backend:8000` proxy too -- it is a
no-op behind Caddy (Caddy intercepts `/api` first) but keeps the `web`
container usable standalone and documents the non-edge fallback. A full URL
in `API_BASE` still switches the SPA to a direct cross-origin call (then set
`CORS_ALLOWED_ORIGINS` + `APP_ENV` -- see "CORS and reverse-proxy trust").

`web/entrypoint.sh` writes the chosen value into `/config.js` as
`window.__CLARION_API_BASE__` on every container start, so one built image
works in every environment.

`web/index.html` loads `/config.js` (classic script, ahead of the module
bundle) and `web/src/api/client.js` resolves the API base in this order:

1. `window.__CLARION_API_BASE__` (from `/config.js` -- prod),
2. `import.meta.env.VITE_API_BASE` (build-time dev override),
3. `http://localhost:8000` (dev default).

A trailing slash is trimmed, so `API_BASE=/api` and `API_BASE=/api/` behave
identically. The committed `web/public/config.js` sets an empty value so
local dev / a static `dist/` preview fall through to steps 2-3; the container
overwrites that copy. For `npm run dev` against the same-origin model, set
`VITE_API_BASE=/api` -- the Vite dev server proxies `/api` to
`VITE_DEV_API_PROXY` (default `http://localhost:8000`). See `web/.env.example`.

`web/entrypoint.sh` validates `$API_BASE` (empty, `/`-rooted, or `http(s)://`
from URL-safe chars) before writing it, so a malformed value can't inject
script into `/config.js` -- it's dropped and the SPA falls back to its
default with a warning in the container log.

## CORS and reverse-proxy trust

- **`APP_ENV` / `CORS_ALLOWED_ORIGINS` (backend).** CORS fails **closed**.
  `allow_origins=["*"]` needs an explicit `APP_ENV=demo` (or
  `DEMO_MODE` in `demo`/`1`/`true`); with a non-demo `APP_ENV` and no
  `CORS_ALLOWED_ORIGINS`, cross-origin browser calls are refused (logged at
  startup). The same-origin `/api` proxy needs neither. For a direct
  cross-origin deployment set `CORS_ALLOWED_ORIGINS=https://<web-host>` and
  `APP_ENV=production`. `allow_credentials=False` (auth is a Bearer header,
  never a cookie).
- **`FORWARDED_ALLOW_IPS` (backend).** gunicorn only trusts `X-Forwarded-*`
  from this hop; the per-IP rate limiter keys on the resulting client IP.
  The compose default is `172.28.0.2` -- the edge proxy's fixed address.
  Change it only in lock-step with the proxy's `ipv4_address` / the network
  subnet. Never `*`. Verified: an `X-Forwarded-For` injected by a browser is
  dropped (real client used); a spoofed one on a direct hit to `backend:8000`
  from any non-`172.28.0.2` peer is ignored entirely.
- **TLS / CSP / HSTS (edge).** `proxy/Caddyfile` is the single source of truth
  for the security-header set (the app's own `_security_headers_middleware` is
  a no-edge fallback that Caddy overrides). `CLARION_TLS_DIRECTIVE` picks the
  demo internal CA vs a mounted CAMPUS-CA cert (TLS floor pinned `tls1.2 tls1.3`);
  `CLARION_HSTS` is the HSTS value (demo `max-age=300`, no `preload` -- ramp
  for prod); `CLARION_CSP_CONNECT_EXTRA` adds `connect-src` entries (the
  workstation NFC bridge on reception kiosks). See `proxy/README.md`.

---

## Data / persistence notes

- **Alembic is the only schema path (P1.5).** `create_all()` and the old
  `_migrate_lightweight()` startup DDL are gone. At boot the app calls
  `_ensure_schema()`: on SQLite it runs `alembic upgrade head` on the local file
  automatically (a *pre-Alembic* `clarion.db` with tables but no
  `alembic_version` is refused — `rm backend/clarion.db && python backend/seed.py`
  to rebuild); on MariaDB it only **verifies** head and refuses to serve
  otherwise, since the runtime account has no DDL rights.
- **SQLite by default (demo).** `backend/app/database.py` reads `DATABASE_URL`
  (P1.3) and falls back to `sqlite:///./clarion.db`. The backend container runs
  with working directory `/app/data` (a named volume), so the demo DB file
  lands at `/app/data/clarion.db` and survives restarts.
- **MariaDB (production).** Point `DATABASE_URL` at
  `mysql+pymysql://clarion_app:...@mariadb:3306/clarion?charset=utf8mb4` and run
  `alembic upgrade head` with the `clarion_migrate` account **before** the app
  starts (see "MariaDB cutover" below). The three least-privilege accounts
  (`clarion_app` DML, `clarion_migrate` DDL, `clarion_report` read-only) are
  created by `backend/db/mariadb/10-accounts.sh` on first container init.
- **Uploads** go to `/app/uploads` (`UPLOAD_ROOT`), backed by the
  `clarion_uploads` volume. Migrated into MinIO in P1.6.
- **Demo data.** Run `docker compose exec backend python /app/seed.py` once.
  Security Audit H3: the memorable `admin123`-style demo passwords only get
  used when `APP_ENV=demo` — in any real deployment (`APP_ENV` unset or
  anything else) `seed.py` instead generates a fresh random password per
  seeded account, forces a password change on first login, and prints each
  one to the console exactly once (never logged to a file). Capture that
  output from the `docker compose exec` run and hand it off through a
  secure channel — it will not be shown again.

---

## Audit hash chain (P2.9, the tender)

`audit_logs` is tamper-evident and physically append-only.

- **Append-only, enforced at the DB.** The `b2d7e4a9c1f6` migration installs
  `BEFORE UPDATE` / `BEFORE DELETE` triggers on `audit_logs` (`SIGNAL
  SQLSTATE '45000'` on MariaDB, `RAISE(ABORT)` on SQLite). `clarion_app`
  keeps schema-wide `UPDATE`/`DELETE` for the other tables; the trigger is
  what makes `audit_logs` the exception, and because `clarion_app` has **no**
  `DROP`/`ALTER`/`TRIGGER` grant it can neither `TRUNCATE` the table nor drop
  the trigger. A DDL-capable account (`clarion_migrate`, used only at deploy
  time; or root) *can* still bypass — the hash chain + the off-box daily seal
  (below) are what make that detectable. Keep `clarion_migrate` credentials
  out of the running app's environment.
- **Hash chain.** Every row carries `seq` (gap-free, 1-based), `prev_hash`,
  and `row_hash` = `HMAC-SHA256(SECRET_KEY, "audit-chain-v1:" || seq || prev_hash
  || canonical_json(row))`. `app/audit.py::log_access` — the single
  audit-write path — advances a singleton `audit_chain_state` tip row inside
  the same transaction (`SELECT ... FOR UPDATE` on MariaDB, a process lock on
  SQLite) so concurrent workers cannot fork the chain. `SECRET_KEY` must be
  set to run the `b2d7e4a9c1f6` migration (it back-fills the chain over
  existing rows).
- **Verify** any time — read-only, safe against production:
  ```
  python -m db.verify_audit_chain --worm     # nightly: also re-reads the WORM seals
  python -m db.verify_audit_chain --json
  ```
  or `GET /admin/audit/chain-status` (admin token). Wire the CLI into the
  nightly cron **with `--worm`** (without it a DDL-capable wipe that also
  rewrote `audit_chain_state` + the `audit_seals` rows verifies clean — the
  WORM copy is the only thing that then still disagrees) and into CI (P2.11).
- **Daily WORM seal.** Run `db/seal_audit_day.py` from cron just after
  midnight UTC — it writes one `audit_seals` row per day (the day's
  `[from_seq, to_seq]` range + the range-end `row_hash`) and, best-effort,
  mirrors that digest to the `clarion-reports-archive` WORM bucket, so a
  wholesale replacement of `audit_logs` (e.g. a restore from a doctored
  backup) is caught even if the in-DB chain was also rewritten.
  ```
  5 0 * * *  cd /app/backend && python -m db.seal_audit_day >> /var/log/clarion/audit-seal.log 2>&1
  ```
  `python -m db.seal_audit_day --backfill` seals every past unsealed day.
- **Retention / partitioning.** Because the triggers block `DELETE`,
  audit-log retention is a **DDL** operation done by `clarion_migrate`, not a
  `DELETE` job. On MariaDB, range-partition `audit_logs` by month
  (`ALTER TABLE audit_logs PARTITION BY RANGE (TO_DAYS(timestamp)) (...)`)
  and drop whole past partitions once their days are sealed **and** the seals
  are shipped off-box. Set the policy (e.g. 7 years online per the tender)
  before go-live; the seals remain the permanent record after a partition
  drop. Do not shorten retention below the tender's clinical-record floor.
- **Known residuals** (security review 2026-09-08, accepted for now):
  - The triggers cover `UPDATE`/`DELETE` but not `INSERT`. An account with
    `INSERT` on `audit_logs` (i.e. `clarion_app`, or an app-level SQL-i —
    none currently known) can insert one row at the next `seq` without
    advancing `audit_chain_state`, which then collides the next real
    `log_access` on `uq_audit_logs_seq` and 500s that request until a
    DDL-capable operator removes the forged row. `verify_chain` flags the
    forged row. A `BEFORE INSERT` trigger validating `NEW.seq` / `NEW.prev_hash`
    against `audit_chain_state` would close this — deferred (needs a MariaDB
    test pass).
  - `log_access` calls `db.commit()` on the caller's session — the contract
    is **"log last, after your own commit"**. A future caller that logs
    mid-transaction would have its partial work committed. It also opens a
    theoretical deadlock window (state-row X-lock vs an uncommitted
    `UPDATE patients`) that the commit-before-log pattern currently closes.

---

## Data-quality monitoring (P2.12, the tender)

`app/data_quality.py` is a registry of independent batch validators —
missing values, probable-duplicate patients, out-of-range coding, anomalous
dates. `run_scan()` UPSERTs findings into `data_quality_alerts` keyed on
`(rule, entity_type, entity_id)`: a repeat sighting bumps `last_seen_at` /
`times_seen`, a finding that stops firing is **auto-resolved**
(`resolved_by='system'`), and a manual admin resolve is never reopened by a
later scan.

- **Run it from cron** (hourly or nightly — it's read-heavy, write-light):
  ```
  0 * * * *  cd /app/backend && python -m db.data_quality_scan >> /var/log/clarion/data-quality.log 2>&1
  ```
  or on demand: `POST /admin/data-quality/scan` (admin).
- **Review**: `GET /admin/data-quality` (filter `status` open|acknowledged|
  resolved|all, `category`, `severity`, `patient_id`), `GET
  /admin/data-quality/summary` (counts). An admin `acknowledge`s a known /
  accepted issue (stays listed, off the open count) or `resolve`s it by hand.
  No web UI yet — API only.
- **Scoped like the rest of the admin console**: an admin sees alerts for
  patients their facility has a relationship to, plus the cross-facility
  `patient_probable_duplicate` alerts, plus non-patient alerts. A platform
  admin (`facility` unset), or an explicit `break_glass_reason`, sees every
  facility's — audit-logged (`list_data_quality_break_glass`), same as
  `list_patients`. Every read is `log_access`-ed.
- **Configurable** (the clause's word): `DATA_QUALITY_DISABLED_RULES` = a
  comma-separated list of rule keys to skip (`python -m db.data_quality_scan
  --list-rules` prints them). A disabled rule's existing alerts are left
  untouched, not auto-resolved.
- `detail` strings name the field + the bad value's *shape*, never a
  diagnosis / drug / allergen — same "no clinical values in a second store"
  rule as `audit_logs` (M8).

---

## LDAP / Active Directory (P1.10, the tender)

A SECOND, opt-in auth provider next to local password accounts
(`backend/app/ldap_auth.py`) — never a replacement. Local accounts always
keep working: break-glass admin, service integrations, and every patient
login stay local regardless of LDAP config (see
`healthcare/Integration Engine and LDAP.md`).

**Enabling it:**
1. Set the `LDAP_*` vars in `backend/.env` (see `backend/.env.example` for
   the full list and defaults) — server URI, a service-account bind DN +
   password, the search base, and the search filter (default
   `(mail={username})` — see the identity-key note below if you use a
   different one, e.g. the realistic `(sAMAccountName={username})`).
2. **Enable TLS.** With both `LDAP_USE_SSL` and `LDAP_START_TLS` unset,
   `ldap_auth` **refuses to bind at all** rather than send passwords in
   cleartext — set one of them (`LDAP_USE_SSL=true` for `ldaps://`,
   `LDAP_START_TLS=true` for STARTTLS on a plain `ldap://` connection), and
   set `LDAP_CA_CERT_FILE` to pin a private/AD-CS CA in production (unset
   uses the OS default trust store). `LDAP_ALLOW_INSECURE_BIND=true` is an
   explicit, loud override for a lab/demo directory only — never set it in
   a campus/production deployment.
3. Map at least one AD group to a CLARION role via
   `POST /admin/ldap-role-mappings` (admin-only; also `GET`/`PUT`/`DELETE`).
   This table is deliberately **not** facility-scoped for *reads* — every
   admin, at any facility, sees the same global table, since it's a
   platform-level identity setting, not a per-hospital one — but a row's
   `facility` value (which campus a JIT-provisioned member of that group
   lands at) **is** restricted: it must be omitted or equal to the acting
   admin's own facility, the same boundary the rest of `admin.py` enforces
   everywhere else. `role` accepts staff roles + `admin`, but never
   `patient`/`emergency_responder` — LDAP is a staff-identity provider
   only. A directory bind that succeeds but matches no mapped group is
   **denied**, never given a default role (least privilege).

**How a login resolves once enabled:**
- No local account for that email/ldap_username, and it isn't a real
  patient's NRIC -> a full bind + group-resolve is attempted; on success a
  local `User` row is JIT-provisioned (`auth_source="ldap"`, a random
  unusable local password placeholder — this account can only ever
  authenticate via LDAP from then on).
- An existing `auth_source="ldap"` account -> re-authenticates against the
  directory on every login (never the local placeholder), and re-syncs
  role/facility/full name from **current** group membership, so a revoked
  AD group takes effect on the very next login.
- A local (`auth_source="local"`, the default) account, or any identifier
  that resolves to a real patient's NRIC -> completely unaffected; LDAP is
  never consulted.
- Failed LDAP binds count against the same per-account lockout as a wrong
  local password (`LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES`) — an
  LDAP-backed account is not exempt from brute-force protection.

**Security notes:**
- An empty password is rejected before any bind is even attempted — most
  directories (including AD) treat an unauthenticated bind (empty
  password) as an automatic anonymous-bind success regardless of the DN, a
  classic LDAP auth bypass.
- The username is passed through `ldap3.utils.conv.escape_filter_chars`
  before being substituted into the search filter, so it can't be used for
  LDAP filter injection.
- **TLS certificate validation is explicit, not ldap3's default.** ldap3's
  own default `Tls()` accepts any certificate unvalidated (`CERT_NONE`) —
  `ldap_auth.py` always passes `validate=ssl.CERT_REQUIRED` whenever
  `LDAP_USE_SSL`/`LDAP_START_TLS` is on. Note ldap3 does not verify
  hostname/SAN even so; pin a private CA via `LDAP_CA_CERT_FILE` rather
  than relying on hostname matching.
- **Identity key is `User.ldap_username`, not `User.email`.** `email` is
  informational (from the directory's `mail` attribute); the stable lookup
  key for an LDAP-backed account is the exact string typed as the login
  username, captured once at JIT-provision time. This matters under any
  `LDAP_USER_SEARCH_FILTER` other than the mail-based default — a
  `sAMAccountName`-based login has a `mail` attribute that differs from the
  login string, and keying on `email` there breaks re-login entirely.
- The service-account bind only ever proves the *service* credential; the
  actual authentication is a second, separate bind as the found user's own
  DN with the password the caller supplied.
- **Bounded concurrency.** `LDAP_MAX_CONCURRENT_BINDS` (default 8) caps how
  many LDAP binds can be in flight at once, process-wide — an
  unauthenticated identifier that doesn't match any local account still
  triggers a real, slow (`LDAP_CONNECT_TIMEOUT_SECONDS`) directory round
  trip, and `/auth/login` is otherwise exempt from the global per-IP rate
  limit (its own per-account lockout doesn't apply to an identifier with no
  `User` row yet).
- Every directory/network error is caught inside `ldap_auth.py` and turned
  into a plain "authentication failed" outcome — a directory outage looks
  identical to a wrong password from the outside (same
  account-enumeration-safety discipline as the rest of `auth_router.py`),
  and no stack trace containing directory details ever reaches a log a
  lower-privileged process might read. Note this parity is content-only,
  not timing — a known LDAP branch does at least one real network round
  trip where a local-account failure does not, an observable (if minor)
  side channel not yet mitigated.

---

## Session / refresh tokens (P2.5, Security Audit M4)

Access tokens are short-lived (`ACCESS_TOKEN_EXPIRE_MINUTES`, 15 minutes) —
down from the original 8 hours. Staying logged in past that is a separate,
longer-lived **refresh token** (`REFRESH_TOKEN_EXPIRE_DAYS`, 30 days,
`backend/app/models.RefreshToken`), delivered two ways depending on the
client:

- **Web console** — an `HttpOnly`, `SameSite=Strict` cookie
  (`clarion_refresh_token`, scoped to `path=/auth`) set by `POST /auth/login`.
  JavaScript can never read it — the entire point, since it closes the
  "8-hour JWT sitting in `localStorage`" exposure the audit named. `secure`
  is off only under `APP_ENV=demo` (so local plain-HTTP dev still works);
  a real deployment always sits behind the TLS-terminating Caddy proxy
  (P1.9), so it's on there. **Requires `CORS_ALLOWED_ORIGINS` to be set for
  a cross-origin deployment** — `main.py` only sends
  `Access-Control-Allow-Credentials` when an explicit origin allowlist is
  configured (the CORS spec forbids combining credentials with a wildcard
  origin), so the demo-wildcard and same-origin-tunnel modes simply don't
  get the refresh cookie cross-origin; that degrades to "re-login every 15
  minutes" rather than misbehaving.
- **Native (Flutter) client** — no cookie jar concept, so the same refresh
  token comes back as a plain `refresh_token` JSON field on the
  login/refresh response instead, stored via `flutter_secure_storage` (the
  OS keychain/keystore) — the web client must never read or persist this
  field even though it's present in the response it gets too.

`POST /auth/refresh` mints a fresh access token from a still-valid refresh
token and **rotates** it (revokes the old one, issues a new one) — both
clients' interceptors call this automatically on a 401 and retry the
original request once, so an expired access token is invisible to the
user in normal use. Presenting an **already-rotated-away** token (a stolen
or duplicated copy still in use after the legitimate client moved past it)
is treated as a compromise signal: every refresh token for that user is
revoked, forcing a fresh login on every device.

`POST /auth/logout` is real server-side revocation (there was none before
P2.5) — it kills the one presented refresh token. A password change
(`POST /auth/change-password`, the forgot-password flow) now also revokes
**every** refresh token for that account, not just the access-token
watermark that already existed — "change your password" now really does
mean "log out everywhere."

---

## What is wired now vs. TODO

### Wired now
- Backend + web build and run, non-root, healthchecked, on one bridge network.
- SQLite on a volume; uploads on a volume.
- Redis, MinIO, MariaDB, Orthanc + Postgres all start healthy and are ready to
  be adopted.
- Runtime API-base injection mechanism (`/config.js`).
- nginx SPA routing + `/api` proxy.

### TODO (tracked in `healthcare/Implementation Roadmap.md`)
- **P1.4 -- MariaDB Data Migration.** SQLite to MariaDB data migration is the next follow-up for an existing DB.
  Once migrated, cut over by pointing the backend at MariaDB:
  1. Run schema migrations using the deploy-time account, **before** `backend`
     starts. In the Compose stack this is the dedicated one-shot service:
     `docker compose --profile migrate run --rm migrate` (runs `alembic upgrade
     head` as `clarion_migrate`). Standalone equivalent:
     `DATABASE_URL=mysql+pymysql://clarion_migrate:PASSWORD@mariadb:3306/clarion?charset=utf8mb4 alembic upgrade head`.
     Note (code-review follow-up 2026-09-07): the P1.6 legacy-column drop
     (`b7f1c0d94a2e`) now **aborts** if any `*_path` blob has not first been
     moved to the object store -- run step 5 under the P1.6 item below in that
     window, or set
     `CLARION_FORCE_DROP_LEGACY_PATH_COLUMNS=1` to drop the columns and accept
     the loss.
  2. Run the app using the runtime account: `DATABASE_URL=mysql+pymysql://clarion_app:PASSWORD@mariadb:3306/clarion?charset=utf8mb4`
  3. (TODO P2.7) enable `--log-bin=ROW` for point-in-time recovery.
- **P1.6 -- ObjectStore: DONE in code, MinIO wiring + WORM provisioning owed.**
  `backend/app/storage.py` (abstraction), `*_object_key`/`_sha256`/`_bytes`/`_mime`
  columns, Alembic `84f653e6c999`+`b7f1c0d94a2e`, and
  `backend/db/migrate_uploads_to_objectstore.py` all landed and verified. Still
  owed for a real deployment:
  1. Point the backend at MinIO: `CLARION_STORAGE_BACKEND=minio`,
     `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` (see
     `backend/.env.example`). `MINIO_SECURE` defaults to TLS-on.
  2. **Provision the WORM buckets BEFORE first app start** — object-lock can
     only be set at bucket creation. For `clarion-documents`, `clarion-signatures`,
     `clarion-dicom`, `clarion-reports-archive`:
     `mc mb --with-lock local/clarion-documents` then
     `mc retention set --default COMPLIANCE 7y local/clarion-documents` and
     `mc version enable local/clarion-documents`. The app's `put` then also
     stamps a per-object COMPLIANCE date; **until this is done, and always on
     the local-filesystem backend, blobs are rewritable/deletable** — a hard
     go-live gate for the tender's 7-year record retention.
  3. Give the runtime MinIO credential only `s3:GetObject`/`PutObject`/
     `DeleteObject`/`ListBucket` (+ `PutObjectRetention` on the WORM buckets) —
     NOT `CreateBucket`. Set `ensure_buckets=False` semantics by provisioning
     out-of-band (the auto-create path is a dev fallback only).
  4. Enable server-side encryption at rest on the MinIO server (KES/Vault) — the
     app does not request per-object SSE.
  5. Data migration for an existing DB: `alembic upgrade 84f653e6c999` →
     `python -m db.migrate_uploads_to_objectstore` → `alembic upgrade head`,
     then delete `backend/uploads/`.
- **P1.7 -- image normalisation: DONE in code.** `backend/app/imaging.py`
  (Pillow: EXIF/GPS strip, auto-orient, cap long edge 2500px, progressive JPEG
  q82) + `backend/app/derived.py` (thumbnails). Medicine photos are normalised
  in place on upload; clinical-document originals are never modified (only a
  derived preview). Owed at deploy: a MinIO **ILM rule on `clarion-derived`** --
  `mc ilm rule add --expire-days 30 local/clarion-derived` -- and exclude that
  bucket from the backup job. Thumbnails self-heal (regenerated from the
  original on a cache miss), so aggressive expiry is safe.
- **P1.8 -- runtime config.** ✅ done -- SPA reads `window.__CLARION_API_BASE__`
  (then `VITE_API_BASE`, then localhost). Backend CORS is env-driven and fails
  **closed** (wildcard needs `APP_ENV=demo`). Mobile (Flutter) already
  runtime-configurable via its Settings screen. See "CORS and reverse-proxy
  trust" above.
- **P1.9 -- TLS reverse proxy.** ✅ done (+ voltagent infra-security review
  actioned) -- `proxy/Caddyfile` (Caddy 2.8): TLS termination with a pinned
  `tls1.2 tls1.3` floor, HTTP->HTTPS, env-driven HSTS (`CLARION_HSTS`, demo
  `max-age=300`, no `preload`), CSP + the security-header set, edge timeouts +
  `max_header_size` + `strict_sni_host` + HTTP/1.1+2 only. Routes `/api/*` ->
  backend (16 MB body cap), rest -> web. `web` + `backend` no longer publish
  host ports; `FORWARDED_ALLOW_IPS` pinned to the proxy's fixed IP. **Two
  networks** now: `edge` (proxy<->web/backend) and `internal`
  (backend<->data/PACS). Plain-HTTP `/healthz` for the container healthcheck.
  **Owed for production:** drop the CAMPUS-CA cert in `proxy/certs/` + set
  `CLARION_TLS_DIRECTIVE` to the file form + ramp `CLARION_HSTS`
  (`proxy/README.md`); DB `REQUIRE SSL` / MinIO TLS (P2.7); a full `style-src`
  tighten off `'unsafe-inline'`; per-service network isolation so the data
  tier can't reach `backend:8000` (P1.11-remainder / P5.3 -- the 3rd
  `observability` net).
- **P1.11 remainder -- offline image bundle + Docker secrets.**
  Pin every image by **digest**, produce a `docker save` tarball (or push to a
  private `registry:2` / Harbor on VM-BACKUP), and move
  `SECRET_KEY` / `OTP_HMAC_KEY` / DB / MinIO creds from `env_file` to
  `docker secret` / `secrets:`. Nothing pulled from the internet at deploy time.
- **P4.7 -- Orthanc.** Enable the PostgreSQL index plugin (env block is stubbed
  in the compose file) and the S3 storage plugin against the `clarion-dicom`
  bucket; turn authentication back on with per-user credentials; add Modality
  Worklist + the OHIF viewer.
- **Observability (P5.1).** `/healthz` + `/readyz` endpoints (the healthchecks
  currently probe `/`), JSON logging, Promtail/Loki, Prometheus, Grafana.
- **Backup/DR (P2.8).** Nothing in this file backs anything up.

---

## Image pinning -- verify before an offline build

Images are pinned by **tag**, not digest. Before building the offline bundle,
confirm these tags resolve (they were chosen from memory) and replace them with
`name@sha256:...` digests:

- `minio/minio:RELEASE.2025-04-22T22-12-26Z`
- `orthancteam/orthanc:24.10.1`
- `mariadb:11.4`, `redis:7.4-alpine`, `postgres:16-alpine`,
  `python:3.12-slim`, `node:20-alpine`, `nginx:1.27-alpine`

`gunicorn==23.0.0` and `uvicorn-worker==0.4.0` are both in
`backend/requirements.txt`. `caddy:2.8-alpine` is the edge image.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `backend` unhealthy, logs `SECRET_KEY` / `OTP_HMAC_KEY` error | Not set in `.env.docker`. Generate with `secrets.token_hex(32)`. |
| `proxy` won't start: `failed to set up container networking: Address already in use` | Host 80/443 taken (set `HTTP_PORT`/`HTTPS_PORT`), or the proxy's static `172.28.0.2` is held by a stale container -- `docker compose down --remove-orphans` then up. |
| Browser: `NET::ERR_CERT_AUTHORITY_INVALID` on the demo | `tls internal` uses Caddy's local CA. `docker compose exec proxy caddy trust`, or export the root from the `caddy_data` volume. |
| `502` / `503` from the proxy on `/` or `/api/...` | `web` / `backend` not healthy yet (the proxy `depends_on` web healthy). `docker compose logs backend`. |
| Login works but API calls 404/blocked | Stale `/config.js` cached, or `API_BASE` unset (empty -> SPA falls back to `http://localhost:8000`). `curl -k https://<host>/config.js` should show `/api`; it is served `no-store`, so a hard refresh clears the client. |
| CSP blocks something in the console (check DevTools) | Add the origin to `CLARION_CSP_CONNECT_EXTRA` (network calls) or adjust `proxy/Caddyfile`. The NFC bridge needs `http://localhost:8770` there. |
| `backend` crash-loops: `setup_event_loop ... replaced by get_loop_factory` | `uvicorn-worker` older than 0.4.0 against uvicorn >= 0.36. `requirements.txt` pins 0.4.0 -- rebuild the image. |
| Need the MinIO console during a demo | Uncomment the `ports:` block under `minio` in `docker-compose.yml`. |
