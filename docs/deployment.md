# CLARION -- Container Deployment (demo topology)

Roadmap tasks **P1.11 + P1.9**. This is the **demo-capable, single-host**
version of the on-prem stack described in `healthcare/On-Prem Architecture.md`
-- the "Single-VM fallback for the pilot via the same Compose file" line. It is
**not** the final hardened production deployment (no Docker secrets, MinIO
console reachable on the internal network). As of P1.9
there **is** a TLS edge proxy (Caddy) -- it is the only service that publishes
host ports; `web` and `backend` sit behind it. The three least-privilege
MariaDB accounts (P1.3) *are* created on init, but `REQUIRE SSL` / host-scoping
wait on wiring the DB into that TLS story. See
**[What is wired now vs. TODO](#what-is-wired-now-vs-todo)**.

---

## TL;DR

### Demo stack (SQLite, no DB service)

```bash
cp .env.docker.example .env.docker
# edit .env.docker: set SECRET_KEY and OTP_HMAC_KEY (required), change passwords
python -c "import secrets; print(secrets.token_hex(32))"   # run twice

docker compose --env-file .env.docker config           # validate
docker compose --env-file .env.docker up -d --build     # start
docker compose exec backend python /app/seed.py         # first run only
docker compose exec proxy caddy trust                   # trust the demo CA
```

Default `up` brings: `proxy` (Caddy, TLS), `web`, `backend` (SQLite on a
volume), `minio`, `redis`, `orthanc(+pg)`. `mariadb` / `migrate` / `backup`
are behind profiles.

### Adopt MariaDB (P1.3 / P2.7)

```bash
bash backend/db/mariadb/generate-encryption-key.sh                # P2.7, once
docker compose --env-file .env.docker --profile mariadb up -d mariadb
docker compose --env-file .env.docker --profile migrate run --rm migrate
# then point the backend at it: DATABASE_URL=mysql+pymysql://clarion_app:...@mariadb:3306/clarion
docker compose --env-file .env.docker --profile mariadb up -d --build backend
```

### Enable the backup service (P2.8)

```bash
# set RESTIC_REPOSITORY / RESTIC_PASSWORD / BACKUP_AGE_RECIPIENTS in .env.docker
docker compose --env-file .env.docker --profile backup up -d backup   # installs the cron
```

- Web console: <https://localhost/>  (HTTP -> HTTPS auto-redirect)
- API:         <https://localhost/api/>  (docs at `/api/docs`)
- `backend` and `web` do not publish host ports -- everything is via the
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
| `minio` | `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` | internal (9000 API / 9001 console) | S3-compatible object store for documents, signatures, medicine photos, thumbnails, DICOM. `ObjectStore` code landed (P1.6); set `CLARION_STORAGE_BACKEND=minio` + provision WORM buckets (see TODO below) to switch the backend off the local-filesystem default. Pulled from quay.io, not Docker Hub -- see the comment on this service in `docker-compose.yml` for why (MinIO archived upstream, Docker Hub org removed 2026-09-11) and the one accepted residual CVE. |
| `minio-init` | `quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z` | internal, one-shot | Provisions `clarion-backend`/`clarion-orthanc`/`clarion-backup` MinIO users, each scoped to its own bucket(s) via `backend/db/minio/policies/` -- `backend`/`orthanc`/`backup` no longer hold the MinIO root key. |
| `redis` | `redis:7.4-alpine` | internal | Cache; later rate-limit / session / worker broker. AOF persistence on a volume. |
| `orthanc` | `orthancteam/orthanc:24.10.1` | internal (8042 HTTP+DICOMweb / 4242 DIMSE) | PACS. DICOMweb plugin on; HTTP basic auth on (`ORTHANC_HTTP_USER`/`PASSWORD`); PostgreSQL index + S3 storage (`clarion-dicom` bucket on `minio`), not the built-in SQLite index. |
| `orthanc-postgres` | `postgres:16-alpine` | internal | PostgreSQL index for Orthanc. |
| `hl7-listener` | built from `./backend` (same image as `backend`) | internal (2575, MLLP) | Lab-analyser HL7 v2 result listener (P4.8). Own process, not a gunicorn worker. |

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
- **Role permissions on upgrade.** `alembic upgrade head` only carries schema
  DDL — it never touches `RolePagePermission` rows. Whenever a code change
  adds a new page to `backend/app/permissions.py::DEFAULT_ROLE_PAGES` (e.g.
  P3.1 added `ancillary`, P3.2 added `dental`, P3.3 added `billing`), an
  already-live facility's existing `RolePagePermission` row is created
  lazily on first request and is **not** automatically backfilled with the
  new page — only a `seed.py`-style backfill call (e.g.
  `add_ancillary_to_legacy_role_pages()` / `add_dental_to_legacy_role_pages()`
  / `add_billing_to_legacy_role_pages()`) does that, and `seed.py` itself is
  first-run-only (see "Demo data" above). On a real upgrade, either re-run
  the relevant backfill function once against the live DB, or have an admin
  enable the new page per facility via the Access Control admin tab —
  otherwise clinician/records_officer/receptionist/pharmacist accounts will
  see no menu entry for the new page and get 403s calling its API until one
  of those happens.

---

## Encryption at rest (P2.7, the tender)

Two layers, both expected for a healthcare / ISO-27001 deployment:

1. **LUKS / dm-crypt** on the data LUN (`/var/lib/mysql`, the MinIO volume,
   `/app/data`). Covers a stolen disk. It is transparent while the host is
   running — necessary but not sufficient on its own. This is a host / VM
   provisioning step (`On-Prem Architecture.md`), not something compose does.
2. **MariaDB transparent data encryption (TDE)** — covers a logical / OS-level
   read while the server is up (an attacker with filesystem access but not a
   DB session, a mis-scoped ops account, a copied datadir).

### MariaDB TDE — what compose does

`backend/db/mariadb/encryption.cnf` (mounted at
`/etc/mysql/mariadb.conf.d/99-encryption.cnf`) turns on:
`innodb_encrypt_tables=FORCE` (every InnoDB + Aria table, existing and new;
FORCE blocks creating an unencrypted one), `innodb_encrypt_log`,
`innodb_encrypt_temporary_tables`, `encrypt_tmp_files`, and `encrypt_binlog`
(the binlog carries full row images for PITR — it must be encrypted too).
Overhead is ~3–10%, lowest for our mostly memory-bound workload (the buffer
pool stays plaintext; encryption is at disk I/O).

### Key management

Community-server path: the **`file_key_management`** plugin with an
openssl-encrypted keyfile on the DB host.

```
bash backend/db/mariadb/generate-encryption-key.sh    # once, before first `up`
docker compose --env-file .env.docker up -d mariadb   # first start does the sweep
docker compose exec mariadb mariadb -uroot -p -e "SHOW STATUS LIKE 'Innodb_encryption%'"
```

The key material (`backend/db/mariadb/encryption/keyfile.{key,enc}`) is
git-ignored and **must be backed up separately from the database** — losing
it makes the data unrecoverable, and co-locating it with the DB backup
defeats the purpose. Rotation: see `backend/db/mariadb/encryption/README.md`
(`SET GLOBAL innodb_encryption_rotate_key_age = 1`).

For a hardware HSM or HashiCorp Vault / KMIP, the University moves to **MariaDB
Enterprise Server** — those key-management plugins are Enterprise-only; the
schema and `innodb_encrypt_*` settings are unchanged, only the plugin lines
in `encryption.cnf`. Whether that licence is worth it is a campus decision
(the tender makes the DBMS "subject to university licensing").

### Backups

`mariadb-backup` copies encrypted pages as-is but has **no `--encrypt`
flag** — the P2.8 backup pipeline pipes its `--stream` output through
`age`/openssl so the backup files themselves are encrypted at rest (tender
).

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
- **Cold storage (copy-only).** `python -m db.archive_audit_logs --verify`
  (cron, after the seal job) packs every completed day older than 90 days
  into a gzip JSONL object + manifest under `audit-archive/` in the WORM
  `clarion-reports-archive` bucket (7-year COMPLIANCE retention, ~8-10x
  smaller than the table). The manifest pins first/last seq, row count and
  the chain tip; `app.audit_archive.verify_archived_day` re-hashes the day
  from storage alone. Nothing is deleted from `audit_logs`: run the partition
  drop above only for months whose days all pass `--verify`. The patient
  audit tab loads a 7-day window by default (`?days=`), widening on demand.
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

## PDPA (P2.10, the tender)

Research settled the shape (`healthcare/Malaysia Health Regulation.md`):
**Malaysia's PDPA has no right to erasure.** Clinical records run on the
s.40 "medical purposes" basis and are kept per Act 586 / MMC. So CLARION
does **not** delete records on request — it does consent-for-optional-purposes,
data-subject requests (access / correction / portability / withdraw-consent),
a DPO register, and a flag-only retention schedule.

- **Consent** — `consent_records` is an append-only ledger; the newest row
  for a `(patient, purpose)` wins. Purposes: `pdpa_notice` (the notice
  acknowledgement), `research`, `marketing`, `sms_reminders`,
  `cross_facility_sharing`. `GET/POST /pdpa/consent` (patient acts on own;
  RO/admin on behalf).
- **Data-subject requests** — `POST /pdpa/requests` (patient or staff),
  `kind ∈ {access, correction, portability, withdraw_consent, objection}` —
  **`erasure` is rejected.** 21-day SLA (`due_at`), `+14` via
  `POST /pdpa/requests/{id}/extend` (once). RO/admin workflow: `assign` →
  `complete` / `reject`. `GET /pdpa/requests/{id}/export` returns the
  patient's record as portable JSON (`clarion-patient-record/v1`) for an
  `access` / `portability` request — the **subject** any time; a **staff
  handler only once the request is assigned to them and `in_progress`**.
  Staff DSR access (detail / workflow / export) is **facility-scoped** (own
  facility, a patient the facility has a P2.2 relationship to, or an audited
  `break_glass_reason`); a portal-filed request for a patient with no
  facility relationship surfaces only to a **platform admin**
  (`facility` unset).
- **DPO register** — `GET/PUT /admin/dpo-register` (per facility, create-on-read).
  PDPA 2024 makes a DPO **mandatory for the University** (>20k data subjects). Fill in
  the real name / JPDP registration ref at deploy.
- **Retention schedule** — `GET /admin/retention-policies` (any admin;
  seeded from the Malaysian defaults: 7 yr adult, 21 obstetric, indefinite
  medico-legal). `PUT /admin/retention-policies/{cat}`,
  `POST /admin/retention/scan`, `GET /admin/retention/review`, and
  `POST .../{id}/disposition` are **platform-admin only** (`facility` unset)
  — the scan and the schedule act platform-wide, and a bad `retain_years`
  could queue the whole system's history for disposal. **The scan never
  deletes** — it flags into `retention_review_items`; actual disposal is the
  MariaDB partition-drop (P2.9) by `clarion_migrate`, then `disposition`ed
  back here (there's no automated re-check that the drop happened — a
  follow-up).
- Every read/write is `log_access`-ed (`view_consent_ledger`,
  `view_data_subject_request`, `data_subject_export_generated`, …).

---

## Backup / DR (P2.8, the tender)

`backend/backup/` — `backup.sh` (scheduled), `restore-test.sh` (quarterly),
`pre-update-snapshot.sh` (deploy gate), `lib.sh`. Runs in the `backup`
compose service (profile `backup`) or standalone. The full runbook —
schedule, RPO/RTO, restore steps, contacts — is `backend/backup/README.md`.

- **Start it:** `docker compose --profile backup up -d backup` — builds the
  runner image (`mariadb-backup` + `mydumper` + `mc` + `restic` + `age`) and
  installs the cron: binlog every 15 min, `daily` (incr + logical +
  objectstore) Mon–Sat 01:15, `weekly` (full + prune + `restic check`)
  Sunday, `restore-test.sh` quarterly. Needs `RESTIC_REPOSITORY` /
  `RESTIC_PASSWORD` (and ideally `BACKUP_AGE_RECIPIENTS`) in `.env.docker`.
- **RPO** ≤ 1 h clinical (≈15 min real), ≤ 24 h object store. **RTO** ≤ 4 h
  full / ≤ 1 h app-tier. Retention: restic `--keep-daily 30 --keep-weekly 12
  --keep-monthly 84 --keep-yearly 7`; 7-yr WORM for records/audit/imaging via
  MinIO object-lock (P1.6).
- **Encrypted backup files:** `mariadb-backup` has no
  `--encrypt` — the DB dumps are streamed through `age` into the restic repo
  (itself encrypted). Store `RESTIC_PASSWORD` + the `age` key in the org
  secret manager, not on VM-BACKUP.
- **Pre-update gate:**
  `docker compose --profile backup run --rm backup "./pre-update-snapshot.sh '<change>'"`
  **must exit 0 before any `alembic upgrade` / image bump.** It records the
  fresh backup, the current Alembic head (the `downgrade` target), and the
  running image digests.
- **Success/failure reporting:** one JSON line per run to
  `/backup/status.jsonl` — feed it into P5.1 alerting.
- **3-2-1:** the restic repo on VM-BACKUP + a monthly `restic copy` to a
  rotated offline disk in another building.

---

## CI gate (P2.11, the tender)

One portable script — `ci/run.sh` — runs the whole gate and is what the
`Makefile` and `.woodpecker.yml` call. **No network required.**

| Gate | Tool | Hard |
|---|---|---|
| Lint (pyflakes-equivalent + mutable-default) | `ruff` (`ci/ruff.toml`) | ✓ |
| Python SAST | `bandit -ll` | ✓ |
| CLARION security patterns (SQL-i, `jwt.decode` alg, `shell=True`, …) | `semgrep` + `ci/semgrep/*.yml` | ✓ |
| Python dependency CVEs | `osv-scanner` (pre-downloaded OSV DB) | ✓ |
| FS / container CVEs + secrets | `trivy fs` (pre-fetched DB) | advisory |
| `alembic up→down→up` + no model drift | `python -m db.check_schema` | ✓ |
| Tests | `pytest` | ✓ |

```
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
make ci            # or:  bash ci/run.sh   /   ci/run.sh --fast
```

**Air-gapped:** `ci/README.md` has the per-tool setup — semgrep rules are
local; `osv-scanner` / `trivy` take a DB copied from a connected host.
`pip-audit` is deliberately **not** used (no offline mode); `osv-scanner`
covers the same ground offline.

**Forge:** Woodpecker CI is the recommendation for an air-gapped forge
(`.woodpecker.yml`, no marketplace-action dependency). Gitea/Forgejo Actions
also work if the runner images are pre-loaded and `DEFAULT_ACTIONS_URL`
points at the internal forge.

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

## On-prem AI engine (P4.3, the tender)

`backend/app/ai/local_llm.py` replaced every third-party AI call (the old
Anthropic-backed handover summary and MyKad OCR paths — Security Audit
finding **C1**, now resolved) with a call to a **local Ollama server**.
Nothing leaves the machine.

**One-time host setup** (not part of the container image — Ollama needs the
GPU directly):
```bash
# Install: https://ollama.com/download
ollama pull llama3.2   # text: handover brief
ollama pull llava      # vision: MyKad OCR
ollama serve           # or run as a system service; listens on :11434
```

- If Ollama isn't running or a model isn't pulled, both features degrade
  automatically to their existing deterministic/Tesseract fallback — a demo
  laptop with no GPU still works, just without the LLM-quality output.
- `CLARION_LOCAL_LLM_URL` (compose default `http://host.docker.internal:11434`,
  since Ollama runs on the host, not as a compose service),
  `CLARION_LOCAL_LLM_MODEL` / `CLARION_LOCAL_VISION_MODEL` (model names),
  `CLARION_DISABLE_LOCAL_AI` (force every feature to its fallback, e.g. no
  GPU available on stage) — see `backend/.env.example`.
- Swapping models (a smaller quantised one for a CPU-only demo box, a larger
  one for real deployment) is a config change only, no code change.

**Running Ollama on a separate GPU host** (e.g. a dedicated inference box on
the same private LAN, instead of the machine running the backend) needs no
code change either — `CLARION_LOCAL_LLM_URL` just points at that host's
`:11434` instead of `localhost`/`host.docker.internal`
(`http://<lan-ip>:11434`). `_is_on_prem_host` (`local_llm.py`) accepts any
loopback/private/link-local address, so an RFC1918 LAN address works exactly
like `localhost` does today — this is a supported topology, not a workaround.
Two things worth checking before relying on it:
- **AMD/ROCm GPUs**: Ollama's GPU acceleration on AMD needs ROCm, and ROCm's
  supported-device list typically lags a few months behind a brand-new GPU
  launch. If the card isn't yet in Ollama's ROCm support matrix, it silently
  falls back to CPU — confirm actual GPU utilization (`ollama ps`, or the
  card's own usage monitor) during a real inference call before depending on
  it for a live/timed demo; CPU is too slow for real-time voice-to-SOAP.
- **Model licensing**: MedGemma's terms explicitly prohibit autonomous
  diagnosis — a non-issue here since every AI feature in this codebase is a
  clinician reference aid, never autonomous (see `healthcare/On-Prem Clinical
  AI.md`'s licence table for the full comparison against Qwen2.5/Llama/etc).
  Confirm the exact model tag before `ollama pull` — Qwen's released line is
  1.5 → 2 → 2.5 → 3; there is no "Qwen 3.6".

If this second host is meant to be reachable **live on stage** (not just for
development), see `docs/exhibition-demo-script.md`'s network setup — the
"network cable unplugged" beat needs the AI host on a private link that's
separate from the venue's internet uplink, not the same one being cut.

**Voice → SOAP (P4.3c)** adds a second local model, `faster-whisper`
(installed via `requirements.txt`, no separate binary): first use downloads
the chosen Whisper model from Hugging Face and caches it under the
`HF_HOME`/default cache dir — a one-time step needing internet, same as
`ollama pull` above; transcription itself is fully offline afterwards.
`CLARION_WHISPER_MODEL` (default `small`), `CLARION_WHISPER_DEVICE`
(`cpu` default, or `cuda` on a GPU host — switches `compute_type` between
`int8`/`float16` automatically). If `faster-whisper` isn't installed or the
model fails to load, dictation degrades to "unavailable" and the clinician
just types the SOAP fields instead.

---

## PACS / DICOM imaging (P4.7, the tender)

Orthanc (docker-compose.yml's `orthanc` service, `internal` network only,
never host-exposed) is the DICOM archive; `backend/app/pacs.py` is a thin
REST client to it; `backend/app/routers/pacs.py` is the auth/facility-
scoping boundary in front of it. Orthanc's own HTTP basic auth
(`ORTHANC__AUTHENTICATION_ENABLED` + `ORTHANC__REGISTERED_USERS`, creds from
`ORTHANC_HTTP_USER`/`ORTHANC_HTTP_PASSWORD`, matched on the backend side by
`CLARION_ORTHANC_USER`/`CLARION_ORTHANC_PASSWORD`) is defense-in-depth on
top of that network boundary, not a substitute for it — the network
boundary is still what actually stops a browser from reaching Orthanc
directly. A study is uploaded against an already-placed X-ray
`ServiceRequest` (no real Modality Worklist hardware to auto-link from —
manual upload is the documented stand-in, same class of deploy-time gap as
this file's thermal-printer/TLS-cert notes elsewhere). The viewer is `dwv`
(MIT), embedded directly in the web app's Ancillary page — no separate
viewer deployment needed.

- `CLARION_ORTHANC_URL` (default `http://orthanc:8042`) — refused unless it
  resolves to loopback/private/link-local, same guard class as
  `CLARION_LOCAL_LLM_URL` above.
- `CLARION_ORTHANC_TIMEOUT` (default 30s).
- `CLARION_ORTHANC_USER` / `CLARION_ORTHANC_PASSWORD` — unset means the
  client sends no auth header, which is only safe against an Orthanc that
  also has auth off (e.g. a bare local `orthanc` binary in dev, not the
  compose stack).

### Orthanc's PostgreSQL index + S3 storage
Landed: `orthanc-postgres` (index) and the existing `minio` service's
`clarion-dicom` bucket (S3 storage) are wired into the `orthanc` service's
`ORTHANC__POSTGRESQL__*` / `ORTHANC__AWS_S3_STORAGE__*` env — Orthanc no
longer uses its built-in SQLite index. `clarion-dicom` itself is created by
the **backend's** `ObjectStore` bootstrap at its own startup (same
`_ensure_buckets()` as every other bucket, `app/storage.py`), not by
Orthanc or this compose file — on a cold `docker compose up` where
`orthanc`'s S3 plugin wins the race and starts before the backend has run
once, Orthanc's first PUT to a not-yet-existing bucket fails; a restart
(`docker compose restart orthanc`) after `backend` reports healthy clears
it. Same class of one-time-ordering caveat as this file's other cold-start
notes, not built out as compose-level wait machinery for a single restart.

### Real modality hardware / Modality Worklist
Wiring an actual X-ray machine via DICOM Modality Worklist +
accession-number auto-link is P4.7's full IHE Scheduled Workflow (see
`healthcare/PACS and DICOM.md` in the vault) — out of scope for this
environment. Manual upload is the working stand-in today.

---

## Lab-analyser HL7 v2 integration (P4.8, the tender)

The real-world protocol for "1-2 modern analysers" (`healthcare/Integration
Engine and LDAP.md`'s own scoping call) is HL7 v2 over MLLP, not the
tender's generic "REST/JSON" line — that describes this app's
own API, not what lab instruments actually speak on the wire.

- **Outbound (order push):** `app/hl7_client.py` sends an
  ORM^O01 message to `CLARION_HL7_ANALYSER_HOST:CLARION_HL7_ANALYSER_PORT`
  whenever a `module="laboratory"` `ServiceRequest` is created
  (`routers/ancillary.py::create_service_request`). Best-effort — an
  unreachable/unset analyser never fails order creation, same "advisory"
  rule as every optional integration in this codebase.
- **Inbound (result ingest):** `app/hl7_listener.py` is an MLLP
  TCP server, its OWN process (docker-compose.yml's `hl7-listener`
  service, port 2575, `internal` network only) — NOT one of the gunicorn
  web workers, which would either conflict on the listener socket or leave
  most workers silently without one. It parses an incoming ORU^R01,
  matches `OBR-2` against the `ServiceRequest.id` that was the placer
  order number on the original push, and stages the result as an
  `AnalyserResultInbox` row — **never** auto-creates a signed
  `ServiceResult`; a clinician reviews it (`GET
  /ancillary/analyser-inbox`, facility-scoped) and submits it through the
  existing, unchanged sign-off endpoint, or discards it (`POST
  /ancillary/analyser-inbox/{id}/discard`) if it doesn't warrant a result.
- **No real analyser exists in this environment** (/.6 — vendor
  compatibility + a test environment — need one). Verified instead against
  hand-crafted HL7 v2 messages and a real MLLP socket round-trip in
  `backend/tests/{test_hl7v2,test_hl7_client,test_hl7_listener,
  test_ancillary_analyser_inbox}.py`. Same class of "protocol built and
  tested, real hardware is a deploy-time step" gap as P4.7's Modality
  Worklist.
- API only, no admin web tab — same precedent as data-quality/security
  alerts (P2.12/P4.5).

To point this at a real analyser: set `CLARION_HL7_ANALYSER_HOST`/`PORT`
to the device's own MLLP listener address (outbound), and configure the
analyser itself to send its results to `hl7-listener:2575` on this stack's
`internal` network (inbound) — see `backend/.env.example`.

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
- **P4.7 -- PACS go-live.** Orthanc auth + the Postgres/S3 plugins are wired
  (above); real modality hardware (Modality Worklist) is still the
  documented gap before this leaves demo status.
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
  3. Before the first `up` of `mariadb`, provision the encryption key:
     `bash backend/db/mariadb/generate-encryption-key.sh` (P2.7 — see
     "Encryption at rest" above). `--log-bin` (ROW) is already in compose.
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
  3. **Landed 2026-09-14 (partial):** the compose stack no longer hands the
     runtime a MinIO root key — `minio-init` (`backend/db/minio/`) provisions
     `clarion-backend`/`clarion-orthanc`/`clarion-backup`, each scoped to
     only its own bucket(s) via IAM policy (`backend/db/minio/policies/`),
     no MinIO admin/user-management rights. **Still open:** `clarion-backend`
     itself still holds `s3:*` (incl. `CreateBucket`) on every `clarion-*`
     bucket, because `ObjectStore._ensure_buckets()` still runs at app
     startup in this topology (the demo-fallback auto-create path item 2
     above says to move off). Tightening it to
     `GetObject`/`PutObject`/`DeleteObject`/`ListBucket`/`PutObjectRetention`
     only is a follow-up **once** buckets are provisioned out-of-band per
     item 2 and `_ensure_buckets()` is disabled/bypassed for that
     deployment — doing it before that would just break app boot.
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
  `mc ilm rule add --expire-days 180 local/clarion-derived` -- and exclude that
  bucket from the backup job. Thumbnails self-heal (regenerated from the
  original on a cache miss), so aggressive expiry is safe.
- **P1.7b -- imaging follow-ups: DONE (partial, 2026-09-14).** PDF documents
  now get a real page-1 preview (`app/imaging.py` `render_pdf_first_page`,
  `pypdfium2`) instead of "no preview available", and the document thumbnail
  endpoint takes `?size=1400` for a readable "web preview" that avoids
  pulling a possibly-15MB original over the Branch WAN link. Both variants
  carry a strong ETag (content-addressed key, so `If-None-Match` -> 304 is
  safe) -- likewise for the medicine-photo thumbnail. ILM bumped 30 -> 180
  days above since page-render is pricier to regenerate than a raster resize.
  Deliberately not built: HEIC input (no confirmed real upload source --
  medicine-photo upload is browser `image/png,image/jpeg,image/webp` only,
  and a clinical-document original is kept regardless of whether a preview
  can be built) and an async normalisation worker (sync-at-upload has no
  reported latency/volume problem yet -- add when one shows up, not before).
  **voltagent security review actioned (2 of 3):** the size allowlist used
  to be duplicated (`derived._ALLOWED_SIZES` vs. a literal tuple in the
  router) -- now a single exported `derived.ALLOWED_THUMBNAIL_SIZES`, so a
  future drift can't surface as an unhandled 500; the medicine-photo
  thumbnail endpoint was missing `log_access` entirely (its sibling
  GET /image logs `view_medicine_image` -- the thumbnail route now logs
  `view_medicine_thumbnail` the same way). Left open, documented in
  `imaging.py` (`render_pdf_first_page` docstring) as a `ponytail:` comment:
  PDFium's internal cost to rasterize a page's content stream isn't
  wall-clock-bounded (only the rendered *output* size is, by construction) --
  bounded today only by the existing 15MB upload cap + 4-way concurrency
  gate on an internal, authenticated-only endpoint; a real fix needs a
  `ProcessPoolExecutor` worker with a timeout (a thread/signal timeout can't
  interrupt a blocking native call).
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
- **P4.7 -- Orthanc.** PostgreSQL index, S3 storage (`clarion-dicom` bucket)
  and HTTP basic auth are all wired; Modality Worklist (+ the OHIF viewer, if
  wanted alongside `dwv`) needs real hardware this environment doesn't have.
- ~~**Observability (P5.1).**~~ Done 2026-09-15 -- see the "Observability
  (P5.1)" section below. (This bullet predates that work; left struck
  through rather than deleted since the rest of this TODO list has its own
  staleness independent of this change -- not audited here.)
- **Backup/DR (P2.8).** Nothing in this file backs anything up.

---

## Observability (P5.1)

Structured logging + `/healthz`/`/readyz` are always on (backend code, no
profile needed). Loki/Promtail/Prometheus/Grafana/Alertmanager/node-exporter/
mysqld-exporter are behind a NEW `observability` Compose profile -- deliberately
opt-in, same reasoning as `mariadb`/`backup`/`migrate`: this is ops
infrastructure, not something the base demo boot needs, so it can never be
the reason the core stack fails to come up.

```
docker compose --profile observability up -d                    # SQLite demo
docker compose --profile mariadb --profile observability up -d  # + mysqld-exporter
```

- **Structured logging.** `LOG_FORMAT=json` (docker-compose.yml's default for
  `backend`; unset/`text` for a readable local dev console) switches every
  log line to one JSON object with `request_id`/`user_id`/`role`/`facility`
  bound via `backend/app/log_context.py` -- a contextvar set once per
  request (the request-id middleware) and once auth resolves
  (`auth.py::_resolve_current_user`), so every existing `logger.info(...)`
  call site in the codebase gets this for free with zero changes elsewhere.
  Never carries PHI -- these are identifiers, not clinical content.
  `X-Request-Id` is also returned on every response, and is the SAME id an
  unhandled-exception 500 quotes back to the caller (previously a second,
  unrelated uuid) -- one id finds the whole request's log trail via a Loki
  query on `request_id`.
- **`/healthz`** (liveness, no auth, no dependency checks) and **`/readyz`**
  (readiness: real `SELECT 1` + object-store `exists()` checks, 503 if
  either fails) replace the previous placeholder container healthcheck that
  probed `GET /` -- see `app/main.py`. Deliberately NOT checked by
  `/readyz`: Redis (provisioned in compose but no app code uses it yet --
  gating readiness on it would be readiness theater) and Orthanc/PACS (a
  DICOM-viewer outage already degrades gracefully per-request without
  needing the whole app pulled from rotation over it). `/healthz` stays
  reachable through the public site (`/api/healthz`) -- a liveness probe is
  harmless; `/readyz` does not (see the `/metrics` bullet's correction just
  below -- the same edge-level block covers both).
- **`GET /metrics`** (Prometheus exposition format, `prometheus-fastapi-
  instrumentator`) and `/readyz` above are blocked at the edge:
  `proxy/Caddyfile` has an explicit `@backend_diag path /api/metrics
  /api/readyz` -> 404, checked BEFORE its `handle_path /api/*` catch-all.
  **Review finding, fixed 2026-09-15:** the original reasoning here ("not
  under `/api` internally, so unreachable") was wrong -- `handle_path
  /api/*` strips the `/api` prefix and forwards whatever remains verbatim,
  with no per-route allowlist, so `GET /api/metrics` would otherwise have
  reached this route exactly like any real API route. Not yet verified
  against a live Caddy instance in this session (no Docker daemon running
  here) -- the fix mirrors this same file's own already-working `@healthz`/
  `handle` pattern on the `:80` block, and Caddy's documented behavior is
  that sibling `handle`/`handle_path` blocks (unlike bare directives) try in
  the order written, but confirm with `docker compose --profile
  observability up proxy` + a manual `curl -k https://localhost/api/metrics`
  (expect 404) before relying on this in production.
- **Network note.** `backend` joins a new `observability` bridge network
  alongside its existing `edge`/`internal` ones. Docker bridge networking
  has no per-port ACL: any container sharing a network with `backend` can
  reach ALL of its exposed ports, not just `/metrics` -- so every
  observability-tier container (prometheus, grafana, loki, promtail,
  alertmanager, node-exporter, mysqld-exporter) can reach the full
  authenticated API surface at `backend:8000`, the same way every
  `internal`-tier container (mariadb, minio, redis, orthanc) already could
  before this change. Not a new auth bypass (every route still needs a
  valid bearer token except the three covered above) and not implemented
  differently here -- worth recording so a future reviewer doesn't have to
  re-derive it (voltagent review, 2026-09-15). `web` stays `edge`-only, so
  the pre-existing web/edge <-> data-tier isolation is untouched.
- **Go-live gate:** `grafana` is the one `observability`-profile service
  that publishes a host port directly (`${GRAFANA_PORT:-3000}:3000`,
  deliberate -- see the service's own comment in `docker-compose.yml`),
  which is a deviation from `healthcare/On-Prem Architecture.md`'s "only the
  proxy publishes" convention. Acceptable for a demo/single-host deploy
  (profile-gated, `GRAFANA_ADMIN_PASSWORD` fails closed if unset, real
  login required, no anonymous access) but re-check at a real multi-host
  go-live: either firewall port 3000 to the ops network only, or front it
  through the reverse proxy like everything else instead of a direct host
  publish (confirmed live, 2026-09-16 test run: `healthcare/Test Suite Run
  Report 2026-09-16.md` F-RUN-4).
- **Prometheus** (`observability/prometheus.yml` + `alert.rules.yml`)
  scrapes `backend:8000/metrics`, `node-exporter:9100`, and
  `mysqld-exporter:9104` (only up with both `mariadb` + `observability`
  profiles). 90-day retention. Three alert rules, deliberately a short,
  named list tied to a real identified risk rather than a speculative
  library: `BackendDown` (scrape failing 2m), `DiskSpaceWarning`/
  `DiskSpaceCritical` (the architecture plan's own "disk-full on the object
  volume is the #1 risk" at 75%/90% used), `HighHttp5xxRate` (>5% of
  requests failing for 5m).
- **Alertmanager** (`observability/alertmanager.yml`) routes alerts to a
  single `email` receiver (the tender's "contactable... via
  email"). Every value in that file -- smarthost, from/to addresses -- is a
  **demo placeholder an operator edits directly** before a real deployment:
  unlike `proxy/Caddyfile` (Caddy's own native `{$VAR}` templating) or the
  app's env-driven config, Alertmanager's official image has no shell/
  envsubst to render a templated config at startup, so this follows the
  same "operator provides a real file" pattern as `proxy/certs/`'s TLS pair.
  The SMTP password is separate again: `smtp_auth_password_file` points at
  `observability/secrets/smtp_password` (git-ignored, only `.gitkeep` is
  committed -- see `.gitignore`). Demo ships with neither customized;
  Alertmanager still starts and simply fails (logged, not fatal to the
  container, and Grafana/Prometheus/Loki are unaffected) to actually send
  until both are provisioned. **WhatsApp** (the tender's other
  channel) is a documented go-live gap, same class as P4.7's Modality
  Worklist / P4.8's SMP-SMS-e-klinik -- no real Meta WhatsApp Business Cloud
  API app or paid gateway (Twilio etc.) exists in this environment to wire
  up; `alertmanager.yml` has a commented-out `webhook_configs` stub for a
  real deployment to point at one.
- **Grafana** (`:3000`, published directly like the app itself rather than
  kept behind the edge proxy -- it still sits behind its own real login;
  `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD` in `.env.docker`, no
  "change-me" fallback -- an unset password fails the container outright
  rather than shipping a guessable default) auto-provisions two
  datasources (Prometheus, Loki) and two dashboards
  (`observability/grafana/dashboards/clarion-backend.json` -- request
  rate/error-rate/p50-p95-p99 latency/up-down; `clarion-infra.json` -- CPU/
  memory/disk-free-per-mountpoint/MariaDB connections+QPS). Deliberately
  skipped: hand-authoring further custom dashboards beyond those two --
  add one when a specific KPI is named; Grafana's Explore view already
  covers ad-hoc queries against both datasources in the meantime.
- **Loki + Promtail**: single-binary, filesystem-backed Loki (no S3/
  object-store chunk backend -- matches this compose file's own "single-VM
  fallback for the pilot" framing; revisit only if log volume/retention
  ever outgrows one VM's disk), 90-day retention (`observability/
  loki-config.yml`). Promtail discovers every container via the Docker
  socket (mounted read-only) and ships stdout/stderr to Loki, labelled by
  compose service name (`observability/promtail-config.yml`). The socket
  mount is broad (any container's logs, not just this stack's) -- the
  standard Promtail idiom, traded for not hand-maintaining a static log-path
  list that drifts every time a service is added/renamed. **Review finding
  (2026-09-15), left as-is, not implemented:** `:ro` on the bind mount only
  stops Promtail from replacing/unlinking the socket file -- it does not
  restrict what the Docker Engine API reachable *through* that socket
  permits (container create/start with an arbitrary volume mount is
  reachable the same as log-reading is); a compromised Promtail container
  is host-root, full stop, same as any container with ANY access to the
  Docker socket. A lower-privilege alternative that avoids the socket
  entirely: a static file-based scrape of `/var/lib/docker/containers/*/*-
  json.log` (already bind-mounted read-only) with a path-based relabel
  instead of `docker_sd_configs`' dynamic discovery -- worth doing if the
  compose-service-name label mapping doesn't need to be dynamic, not
  attempted in this pass.
- **`clarion_metrics`** (`backend/db/mariadb/10-accounts.sh`) is a 4th
  least-privilege MariaDB account for `mysqld-exporter` --
  `PROCESS`+`REPLICATION CLIENT` (inherently server-global privileges,
  there is no schema-scoped equivalent) + `SELECT` on
  `performance_schema` only. No access to the `clarion` schema itself.
  `MARIADB_METRICS_PASSWORD` in `.env.docker`.

---

## Two-campus rollout & offline emergency-export appliance (P5.3)

`healthcare/On-Prem Architecture.md`'s deployment topology: one central
stack at Main Campus, Branch reached over the University WAN. Two pieces, both
scoped to what's buildable without a real second campus/WAN link (same
class of gap as P4.7's Modality Worklist):

**Branch edge proxy** -- `docker compose --profile branch-edge up -d` brings
up `branch-proxy` (Caddy, `proxy/branch-edge/Caddyfile`) + `branch-web` (the
same `clarion/web:local` image the central `web` service builds). Static
SPA assets are served from Branch's own LAN; every `/api/*` call makes one
WAN hop to `CLARION_CENTRAL_BACKEND_ORIGIN`. Runs on its own `branch-edge`
network, isolated from `edge`/`internal`/`observability` -- its only route
to patient data is that one WAN hop, same trust boundary as any other
client. Full detail, what's deliberately not built (Redis -- turned out
unnecessary once the edge just runs the pre-built static image), and the
WAN-degradation validation procedure (`simulate-wan.sh` + re-running
P5.2's Locust suite against the edge under injected latency/loss):
`proxy/branch-edge/README.md`.

**Offline emergency-export appliance** -- `backend/app/emergency_export.py`
+ CLI `backend/db/emergency_export_appliance.py`. Reuses
`routers/emergency.py`'s own `_scoped_fields`/critical-for-emergency logic
(the same shape the public QR/NFC scan endpoint returns) and
`clinical_access.py`'s facility-scoping helper, batched over every patient
a facility has a relationship to -- independent of any individual
patient's opt-in `EmergencyToken` card, this is the facility's own offline
safety net for a WAN cut. Encrypted with `age` (same tool + recipient/
identity convention as the P2.8 backup pipeline, not a second crypto
dependency):

```bash
# central host, nightly cron
python -m db.emergency_export_appliance build --facility "University Branch" \
    --recipient age1... --out /appliance/emergency-campus-branch.json.age

# on the appliance itself, during an actual WAN cut
python -m db.emergency_export_appliance query \
    --in emergency-campus-branch.json.age --identity /secure/appliance-key.txt \
    --nric 900101-01-1234
```

The identity (private key) lives only on the appliance, never on the
central host that runs `build` -- same custody rule as
`backend/backup/README.md`'s restore identity.

`build` refuses an unregistered `--facility` (must match a
`HospitalSetting` row -- catches a typo before it silently produces an
empty or wrong export) and writes one `audit_logs` row per run
(`emergency_export_build`, facility + patient count). `query` can't reach
the central DB by design (that's the entire point of the appliance during
a WAN cut), so it instead appends one line — timestamp + `sha256(NRIC)`,
never the NRIC itself — to a local `<export>.access.log`; reconcile that
into central `audit_logs` once connectivity returns (a manual/scripted
step at commissioning, not built here — same "documented wiring, not an
end-to-end pipeline" precedent as the backup service's own
`status.jsonl`). Both gaps (no audit trail, `--facility` untied to any
authenticated identity) were the security review's top findings —
`healthcare/Implementation Roadmap.md`'s P5.3 changelog entry has the
full review.

Branch's own TLS certs go in `proxy/branch-edge/certs/`, **never**
`proxy/certs/` (the central site's — would ship its private key to the
less-trusted Branch container). `branch-proxy`'s entrypoint refuses to start
if `CLARION_CENTRAL_BACKEND_ORIGIN` doesn't begin with `https://`, so a
plaintext-WAN misconfiguration fails loudly instead of silently
downgrading every API call.

---

## Offline NFC emergency tag (true zero-network fallback)

Two independent things live on the same physical NFC card
(`EmergencyToken`, `routers/emergency.py`):

- **The pointer model** (existing): the tag's hardware UID is hashed
  (`auth.hash_nfc_uid`, Security Audit M7) and looked up server-side on
  every scan. Rich, revocable, fully audited -- but needs the backend
  reachable. This also covers the QR/`card_reference` flow.
- **The on-tag model** (new): a compact plaintext summary (blood type,
  critical allergies, critical active medications, critical conditions —
  in that truncation priority) written DIRECTLY onto the tag's own NDEF
  memory. Readable by **any** standard NFC reader with **zero** network,
  app, or server dependency -- the answer to "the entire backend is down,
  not just the WAN link, can a responder still get anything." Not
  revocable in real time (it's physically on the tag until rewritten) and
  deliberately minimal -- no name/age, no non-critical items. That's an
  accepted tradeoff for this specific fallback, not a bug.

**Registration flow** (staff, same roles as today's NFC registration --
admin/records_officer/clinician):
1. Web console → Patient → "Register NFC Card" (unchanged) — now the
   response includes `tag_text` (+ `tag_text_truncated` if it didn't all
   fit). The prompt shown after registering walks staff through the next
   step.
2. On a phone running the CLARION app (staff role), open the NFC icon in
   the Home app bar → **"Write Offline Tag"** → paste the text → tap the
   SAME physical card. This is the one thing a desktop browser can't do
   (generic NDEF write needs a phone's native NFC) -- see
   `mobile_flutter/lib/services/nfc_service.dart`.

**Reading it back**: the existing "Scan Emergency Card" → NFC mode
already does this automatically -- one tap reads both the UID (tries the
live server lookup first) and the on-tag text in the same session. If the
live call fails with **no response at all** (a real connection failure,
never a legitimate 404 "not registered") and on-tag text exists, the
scanner falls back to it and shows a loud "OFFLINE — read directly from
the card" banner. A live, reachable answer from the server always wins
over the tag's own (possibly stale) copy.

`tag_max_bytes` on the registration request lets the app pass the actual
tapped tag's real NDEF capacity (`NdefAndroid.maxSize` -- NTAG213=144B,
NTAG215=504B, NTAG216=888B); the backend default (128B) is conservative
enough to fit the smallest common tag without it.

### Encrypted tags (v2) -- what changed operationally

`register_nfc_card` now also returns `tag_blob`: the same critical data
sealed with AES-256-GCM to that tag's UID. Staff should write **`tag_blob`**
(the web prompt offers it first); `tag_text` plaintext is only for a tag too
small to hold a sealed record.

| Setting | Meaning |
|---|---|
| `CLARION_TAG_KEY_SECRET` | Master secret the data keys are derived from. **Set it in production**; if unset the key falls back to `SECRET_KEY`, and rotating `SECRET_KEY` would then make every tag in the field unreadable. |
| `CLARION_TAG_KEY_ID` | Current key id (default 1). Bump to rotate; re-write tags afterwards. |
| `CLARION_TAG_MIN_KEY_ID` | Oldest key id still handed to devices (default = current). Raising it is the only revocation lever for old keys; a device that already cached one is unaffected until its 72 h cache lapses. |

Behaviour you should expect:
- A sealed tag opens offline only on a CLARION device with a signed-in
  admin / clinician / records_officer / emergency_responder account that
  fetched the key within the last 72 h. A generic phone sees ciphertext.
- The scanner tries the server for 1.5 s, then falls back to the tag only
  when the server is genuinely unreachable (timeout / no connection / 429 /
  502 / 503 / 504). A real 404 for a revoked card is never overridden.
- Offline reads are logged on the device and uploaded on the next
  connection (`POST /emergency/offline-reads`); they appear in the audit log
  as `emergency_access_nfc_offline` with `source=device_asserted`. Treat them
  as honest-but-unverifiable until the NTAG 424 DNA read counter lands.
- Any key holder can open any sealed tag; a revoked-but-unexpired tag still
  opens offline.

---

## Public site: status page details and the app download

- **Status page (`/status`):** every card expands. The **API** card shows
  what it is made of -- Sign-in, Patient records, Emergency card lookup,
  Queue & appointments, Background jobs, and Hospital network sync (central
  reachable, when federation is configured) -- each a cheap read-only
  probe run on the server (`backend/app/main.py::_api_checks`), with latency.
  Each component also shows what "normal" looks like (typical and p95 latency
  over this server's last ~10 minutes of checks) and what stops working if it
  is down. Still status + milliseconds only; no counts, hostnames or errors.
  A failing sub-check turns the API "degraded" and the overall banner
  "Partial outage".
- **Get the app (`/get-app`):** static page for people who don't have CLARION:
  Android download, install steps, QR code for the page, SHA-256 of the file,
  and the web console as the fallback. The sign-in page and the landing page
  link to it.
- **Publishing the APK** (the file is never committed):
  1. `flutter build apk --release` in `mobile_flutter/` (the default API base
     is baked in as `https://clarion.larmkx.com/api`; override with
     `--dart-define=API_BASE_URL=...`).
  2. Copy `build/app/outputs/flutter-apk/app-release.apk` to
     `web/public/downloads/clarion.apk` and write its fingerprint:
     `sha256sum clarion.apk | cut -d' ' -f1 > clarion.apk.sha256`.
  3. Rebuild the `web` image. Until the file exists the page shows
     "Download is being prepared".
  Note: release builds are currently signed with the DEBUG key (fine for
  direct installs/demos; a real keystore is needed for the Play Store).

---

## Sign-in security (public access)

- **Login page:** `/login` has two paths (Patient / public, Staff); the
  backend resolves the identifier either way. Errors are uniform (no account
  enumeration, dummy hash for unknown identifiers), lockout feedback shows
  when to retry, and failed/locked sign-ins are written to the audit log
  (`login_failed`, `login_locked`, `mfa_failed`, ...).
- **MFA (TOTP):** `CLARION_MFA_REQUIRED_ROLES` (comma list; the central compose
  file defaults it to `admin,clinician,records_officer`, the app default is
  empty = opt-in). A required role is walked through enrolment (QR +
  recovery codes) at first sign-in; anyone who has enrolled is always
  challenged. Secrets are AES-GCM encrypted at rest (key derived from
  `SECRET_KEY`); a code can't be replayed; wrong codes feed the same account
  lockout as wrong passwords. The challenge token is not a JWT, so it can
  never act as an access token.
- **Lost phone + codes:** an admin clears it (`POST /auth/mfa/reset/{user_id}`),
  the user re-enrols at next sign-in. Rotating `SECRET_KEY` invalidates every
  enrolled secret -- re-enrol everyone.
- **Sessions:** `/security` in the web console lists signed-in devices
  (IP, browser, last active) and lets a user sign out one or all others. A
  sign-in from a never-seen browser sends a "new sign-in" email (Mailtrap,
  best effort).
- **Mobile:** the app prompts for the code after the password; enrolment
  itself is done once in the web console.

---

## Federation: central MPI + hospital nodes

Each hospital keeps its own database. The central node runs `mpi`
(`backend/mpi`, compose service in `docker-compose.pi.yml`, routed at
`/mpi/*`): it holds hospital public keys and, per patient, the newest 3 visit
pointers per hospital keyed by an opaque `HMAC(pepper, NRIC)`. No PHI, no
NRICs, and the pepper never reaches it.

**Central**
- `MPI_ADMIN_TOKEN` (>= 24 chars; shorter = registration disabled). Register
  a hospital from the central host, not over the internet (`/mpi/admin/*` is
  blocked at the edge):
  `docker compose -f docker-compose.pi.yml exec mpi python -c "..."` or a
  curl to `http://mpi:8100/admin/facilities` from inside the network.
- Run ONE `mpi` worker (its replay cache is process-local).
- Locked out (e.g. every seeded account was rotated)? From the central host:
  `docker compose -f docker-compose.pi.yml exec backend python /app/db/reset_admin_password.py <email>`
  prints a one-time temporary password to YOUR terminal -- don't run it where
  output is logged. The account must change it at next sign-in; sessions are revoked.

**Each hospital** (`.env.docker`)

| Variable | Meaning |
|---|---|
| `MPI_BASE_URL` | Central URL incl. `/mpi`, e.g. `https://central.example/mpi` |
| `CLARION_FACILITY_ID` | This hospital's id as registered at central |
| `CLARION_FACILITY_PRIVATE_KEY` | base64 Ed25519 seed; generate with `python -c "from mpi.sigs import generate_keypair; print(generate_keypair())"` and register the public half |
| `CLARION_MPI_PEPPER` | Shared among hospitals ONLY. Bump `CLARION_MPI_KEY_VERSION` to rotate (then re-publish). |
| `CLARION_FACILITY_NAME` | The `Encounter.facility_name` this hospital's records carry (default = id) |
| `CLARION_PEER_KEYS` | **Recommended.** Path/JSON `{"hosp-b": {"public_key": "...", "endpoint": "https://..."}}`. When set it is authoritative: a compromised central cannot swap a peer's key or redirect fetches. Unset = trust central's registry. |

Flow: sign-off -> queued pointer publish -> any hospital:
`GET /federation/patients/{id}/other-visits`, then
`GET /federation/patients/{id}/visits/{facility}/{visit_ref}` (fetched from
the origin, verified against the origin's signed content hash, returned for
display -- never written into the local tables).

**Known residual risks** (see the 2026-10-10 roadmap entry): any registered
hospital that knows an NRIC and the pepper can read that patient's recent
signed visits (audit trail only; a consent/presence proof is a product
decision); the 10-digit NRIC space makes the pepper a weak privacy boundary
if it leaks; without `CLARION_PEER_KEYS`, central is the key directory.

---

## University SMP/SMS/e-klinik-panel/Registrar eligibility check -- MOCK

SMP, SMS, and the e-klinik panel are campus-internal systems this environment
has zero real spec, schema, or credentials for (P4.8's documented gap, same
call P4.4 made to skip a real MIMS integration). Asked the user how to
proceed 2026-09-15; the answer was "build a working mock first" for the
exhibition demo, so what's here is a genuine, working integration
**boundary** — a real HTTP call, a real adapter, a real UI flow — over
entirely fictional demo data, never presented as real campus records.

- `backend/app/campus_registry.py` -- the adapter. `check_eligibility(nric)`
  calls `{CAMPUS_REGISTRY_BASE_URL}/eligibility/{nric}` and never raises: a
  down/slow/misbehaving registry returns `{"available": false, ...}`
  instead of blocking patient registration (same "advisory, never a hard
  gate" discipline as every AI feature in this codebase).
- `backend/app/routers/campus_registry_mock.py` -- the mock itself, mounted
  in-process at `/mock-campus-registry` (no separate service to stand up for
  something that exists only to be swapped out). A handful of entirely
  fictional student/staff records; every response carries `"mock": true`.
- `GET /patients/campus-eligibility/{nric}` -- the CLARION-facing endpoint
  (same roles as `create_patient`: admin/records_officer/clinician),
  wired into the web console's "New Patient (One-Click Intake)" form —
  a "Check University Eligibility" button next to the NRIC field, result shown
  inline, clearly labeled "(mock campus registry — demo)".

**Go-live**: set `CAMPUS_REGISTRY_BASE_URL` to the real SMP/SMS/e-klinik-panel
endpoint once the University provides one — no code change on CLARION's side. Until
then this stays a demo-only mock; don't remove the `"mock": true` /
"(demo)" labeling, it's load-bearing honesty, not decoration.

---

## Image pinning -- verify before an offline build

Images are pinned by **tag**, not digest. Before building the offline bundle,
confirm these tags resolve (they were chosen from memory) and replace them with
`name@sha256:...` digests:

- `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`
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
