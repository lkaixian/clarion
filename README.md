# CLARION
### *(Clinical Access, Records & Information Operations Network)*

Emergency-first, interoperable clinic information system — FastAPI backend,
React staff console, Flutter patient app, on an on-prem MariaDB / MinIO /
Caddy stack. Built as a competition demo aligned with the Malaysian
government tender **the tender reference** ("University HealthCare").

```
clarion/
├── backend/            FastAPI. FHIR-lite model, RBAC + page permissions,
│   ├── app/            auth (local + LDAP), emergency QR/NFC scan,
│   ├── alembic/        self-registration (NRIC OCR), AI endpoints,
│   ├── db/             append-only audit hash chain, data-quality scan,
│   ├── backup/         PDPA (consent / DSR / retention), backup/DR scripts.
│   └── requirements*.txt
├── web/                React + Tailwind staff / admin console.
├── mobile_flutter/     Flutter patient app (Android) — the maintained client.
├── mobile/             Legacy React Native prototype — reference only.
├── ci/                 The portable CI gate (ruff / bandit / semgrep / …).
├── proxy/              Caddy edge — TLS, HSTS, CSP, /api routing.
├── docs/               deployment.md (the ops guide) ·
├── healthcare/         Obsidian vault — all research, the roadmap, the
│                       compliance matrix, the security audit.
├── AGENTS.md           Read first — points at the vault + live status.
└── docker-compose.yml  The single-VM on-prem topology.
```

---

## 1. Local dev — SQLite, no containers

Fastest way to run the whole thing on one machine.

### Backend (start here — everything depends on it)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate       # Windows: venv\Scripts\activate  (needs Python 3.11+)
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env          # REQUIRED — edit it, see below
python seed.py                # creates demo logins + reference data
uvicorn app.main:app --reload --port 8000
```

**`backend/.env` is required.** Set `SECRET_KEY` and `OTP_HMAC_KEY` — there
is no hardcoded fallback for either. Generate each (use *two different*
values):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Rotating either later invalidates every issued JWT / in-flight OTP **and**
re-baselines the audit hash chain (`SECRET_KEY` keys it) — plan for it.

Swagger UI: <http://localhost:8000/docs>. SQLite migrates itself at boot
(`_ensure_schema()` runs `alembic upgrade head`).

**Demo logins** (only with `APP_ENV=demo`, the `.env.example` default):

| Role | Email | Password |
|---|---|---|
| Admin | admin@clarion.demo | admin123 |
| Clinician | clinician@clarion.demo | clinician123 |
| Pharmacist | pharmacist@clarion.demo | pharmacist123 |
| Receptionist | receptionist@clarion.demo | receptionist123 |
| Patient | patient@clarion.demo | patient123 (or NRIC `520314-01-1234`) |

Outside `APP_ENV=demo` (any real deployment) `seed.py` never uses these — it
generates a fresh random password per account, forces a change on first
login, and prints each once (Security Audit H3).

### Web console

```bash
cd web && npm install && npm run dev
```

<http://localhost:5173>, log in with the clinician demo account. Reads its
API base from `/config.js` → `VITE_API_BASE` → `http://localhost:8000`.

### Mobile app (Flutter)

```bash
cd mobile_flutter && flutter pub get && flutter run -d <device-id>
```

Full setup (SDK paths, API-base overrides, release signing) is in
`mobile_flutter/README.md` — read that first.

### Optional integrations (all degrade gracefully if unset)

| Set | Enables | Without it |
|---|---|---|
| local Ollama server (`ollama pull llama3.2 llava`) | on-prem LLM handover summaries / MyKad OCR | deterministic/Tesseract local fallback — nothing calls out, so this is safe to leave unset (`CLARION_DISABLE_LOCAL_AI=1` forces the fallback explicitly) |
| `tesseract-ocr` + `pytesseract` | offline NRIC OCR for self-registration | the photo step fails closed |
| `MAILTRAP_API_TOKEN` | real OTP emails (password reset, self-reg) | OTPs generated + logged server-side, not sent |
| `LDAP_ENABLED=true` (+ `LDAP_*`) | Active Directory as a second auth provider | local password accounts only |

---

## 2. On-prem stack — Docker Compose

The single-VM topology from `healthcare/On-Prem Architecture.md`. The full
ops guide is **`docs/deployment.md`** — this is the short version.

```bash
cp .env.docker.example .env.docker
# edit: SECRET_KEY, OTP_HMAC_KEY (required); change every *_PASSWORD
python -c "import secrets; print(secrets.token_hex(32))"    # twice

docker compose --env-file .env.docker config               # validate
docker compose --env-file .env.docker up -d --build        # start
docker compose exec backend python /app/seed.py            # first run only
docker compose exec proxy caddy trust                      # trust the demo CA
```

Default `up` brings: **proxy** (Caddy — TLS, HSTS, CSP, `/api` routing, the
only host-port publisher), **web**, **backend** (SQLite on a volume),
**minio**, **redis**, **orthanc** (+ postgres). `mariadb`, `migrate`, and
`backup` sit behind profiles.

- Web console: <https://localhost/>  · API: <https://localhost/api/>
  (docs at `/api/docs`)
- `docker compose down` keeps volumes; `down -v` wipes them.

### 2a. Adopt MariaDB (production DB — P1.3 / P2.7)

```bash
bash backend/db/mariadb/generate-encryption-key.sh                 # P2.7 — once
docker compose --env-file .env.docker --profile mariadb up -d mariadb
docker compose --env-file .env.docker --profile migrate run --rm migrate
#   set  DATABASE_URL=mysql+pymysql://clarion_app:PW@mariadb:3306/clarion?charset=utf8mb4  in .env.docker
docker compose --env-file .env.docker up -d --force-recreate backend
```

The `migrate` one-shot runs `alembic upgrade head` as the DDL-privileged
`clarion_migrate` account; `backend`'s runtime account is DML-only and
refuses to serve an un-migrated schema. To copy the demo SQLite data across:
`python -m db.migrate_sqlite_to_mariadb` (see `backend/db/README.md`).

### 2b. Enable backups (P2.8)

```bash
# in .env.docker: RESTIC_REPOSITORY, RESTIC_PASSWORD, BACKUP_AGE_RECIPIENTS
docker compose --env-file .env.docker --profile backup up -d backup
```

Installs the cron: binlog every 15 min, daily incremental, weekly full +
`restic check`, quarterly restore test. DR runbook: `backend/backup/README.md`.

---

## 3. Operational components

Everything the tender's security / ops clauses ask for. Each is off or
inert until you do the one step below; the deep doc has the detail.

| Component | Clause | Turn it on | Docs |
|---|---|---|---|
| **Edge TLS + security headers** (Caddy) | | drop the CAMPUS-CA cert in `proxy/certs/`, set `CLARION_TLS_DIRECTIVE` | `proxy/README.md` |
| **LDAP / Active Directory** auth | | `LDAP_ENABLED=true` + `LDAP_*`; map ≥1 group via `POST /admin/ldap-role-mappings` | `docs/deployment.md` → LDAP |
| **Object storage** (MinIO, WORM) | | `CLARION_STORAGE_BACKEND=minio`; **provision the WORM buckets before first start** | `docs/deployment.md` → ObjectStore |
| **Encryption at rest** (MariaDB TDE + LUKS) | | `generate-encryption-key.sh` (above); LUKS on the data LUN is a host step | `docs/deployment.md` → Encryption at rest |
| **Audit hash chain** (tamper-evident, append-only) | | on automatically with the `b2d7e4a9c1f6` migration; verify with `python -m db.verify_audit_chain --worm` or `GET /admin/audit/chain-status` | `docs/deployment.md` → Audit hash chain |
| **Daily WORM audit seal** | | cron: `python -m db.seal_audit_day` just after midnight UTC | same |
| **Data-quality monitoring** | | cron: `python -m db.data_quality_scan`; review at `GET /admin/data-quality` | `docs/deployment.md` → Data-quality |
| **PDPA** — consent / data-subject requests / DPO register / retention | | fill the DPO register (`PUT /admin/dpo-register`); cron `python -m db.retention_scan` | `docs/deployment.md` → PDPA |
| **Backup / DR** | | profile `backup` (above) | `backend/backup/README.md` |
| **CI gate** | | `make ci` locally; `.woodpecker.yml` on a forge | `ci/README.md` |
| **Refresh-token sessions** (15-min access + rotating refresh) | | on by default; the cookie is auto-`Secure` outside `APP_ENV=demo` — just set `CORS_ALLOWED_ORIGINS` for the web origin | `docs/deployment.md` → Session |

---

## 4. Checks

```bash
make ci            # ruff · bandit · semgrep · osv-scanner · shellcheck ·
                   # alembic up/down · pytest       (bash ci/run.sh --fast to skip pytest)
make test          # pytest only
make schema        # alembic upgrade→downgrade→upgrade + model-drift gate
```

Install the tooling with `make install` (`pip install -r backend/requirements.txt
-r backend/requirements-dev.txt`). `osv-scanner` / `trivy` are Go binaries —
install separately; air-gap setup is in `ci/README.md`.

---

## 5. Where the knowledge lives

- **`AGENTS.md`** — read first. Points at the vault and carries the live
  implementation status.
- **`healthcare/`** — the Obsidian vault: `Implementation Roadmap.md` (the
  phased plan + changelog), `Compliance Matrix.md` (every clause → status),
  `Security Audit.md`, `On-Prem Architecture.md`, and the research notes.
- **`docs/deployment.md`** — the operations guide (this README is the map).
- **`docs/{operations,programming,maintenance,transfer-of-technology}-manual.md`**
  — the handover manual set (tender 7.1/3.2.5); `docs/data-dictionary.md`
  is the auto-generated schema/ERD.
- **`docs/exhibition-demo-script.md`** — the live demo run sheet: setup,
  scene-by-scene script, fallbacks, anticipated Q&A.

---

## Troubleshooting

- **`RuntimeError: SECRET_KEY … is not set`** — `backend/.env` (or
  `.env.docker`) is missing/incomplete. See §1.
- **`mariadb` won't start** — you didn't run
  `bash backend/db/mariadb/generate-encryption-key.sh`; the encryption
  keyfile mount is empty (the "provision the key first" gate, P2.7).
- **`backend` refuses to serve on MariaDB** — the schema isn't at head; run
  the `migrate` profile (§2a) first.
- **`bcrypt` error on `pip install`** — `requirements.txt` pins
  `bcrypt==4.0.1`; add it explicitly if installing by hand.
- **`email-validator` import error** — `pip install "pydantic[email]"`.
- **CORS errors** — outside `APP_ENV=demo`, CORS fails **closed**; set
  `CORS_ALLOWED_ORIGINS` to your web origin.
- **Web console shows a stale API base** — it caches `/config.js`; hard-reload.
- **Mobile app can't reach the backend** — `localhost` / `10.0.2.2` don't
  work from a physical phone; use your LAN IP, set in the app's Settings
  screen (no rebuild) or `--dart-define=API_BASE_URL=...`.
- **Self-registration fails at the photo step** — no OCR backend; see §1
  optional integrations.
- **Audit-chain verify says BROKEN after a `SECRET_KEY` change** — expected;
  a rotation re-baselines the chain (`docs/deployment.md` → Audit hash chain).
