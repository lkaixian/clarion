# AGENTS.md — read this first

**CLARION** is an emergency-first clinic system (FastAPI + React + Flutter, SQLite).
It is a **competition demo** deliberately aligned with a live Malaysian government
tender — **the tender reference**, "University HealthCare" for Pusat Kesihatan
Universiti, the University (two campuses, ~23k users). Plan: win the competition on this
stack, then **port to PHP CodeIgniter 4** (the tender mandates it).

## Where the knowledge lives

All research, assessment and the plan are in the **Obsidian vault at `healthcare/`**
(the `realclaudian` plugin opens it; vault = agent working directory). Start at:

- **`healthcare/CLARION HealthCare.md`** — map of content, links to everything
- **`healthcare/Implementation Roadmap.md`** — the plan (P0–P5) + **progress log** +
  risk register.
- **`healthcare/Compliance Matrix.md`** — every tender clause → Have/Partial/Gap
- **`healthcare/Security Audit.md`** — 1 critical + 4 high + 9 medium findings
- **`healthcare/On-Prem Architecture.md`** — MariaDB/MinIO/Orthanc/backup target
- Research notes: `Designing for the PHP Port`, `Malaysia Health Regulation`,
  `National Interoperability`, `On-Prem Clinical AI`, `PACS and DICOM`,
  `Integration Engine and LDAP`, `Nationwide Health Information Exchange`
- **`healthcare/Sources.md`** — every external reference, checked
- Raw agent transcripts: session scratchpad `agy-research-full.md`,
  `security-audit.md`, `architecture.md` (not committed)


## Implementation status (2026-08-30)

Working on branch `main`, uncommitted (the user commits). Session did:

| Task | State |
|---|---|
| **P0.4** cloud-AI egress guard | ✅ done — `backend/app/ai/_cloud_guard.py`; Anthropic path now needs `ANTHROPIC_API_KEY` **and** `CLARION_ALLOW_CLOUD_AI=1`, else local fallback |
| **P1.1** Alembic | ✅ done — `backend/alembic/`, baseline `5e6a60dfe274` (30 tables). Existing DB needs one-time `alembic stamp head`. Verified: autogenerate vs `create_all()` → 0 ops |
| **P1.2** `models.py` portability sweep | ✅ done — explicit `String(N)`, `DateTime(timezone=True)`, FK `ondelete`, `MetaData` naming in `database.py`. `RoomClaim` partial-unique dropped → Python guard only (demo keeps DB backstop via `_migrate_lightweight`) |
| **P1.11** containers | ✅ done — `backend/Dockerfile`, `web/Dockerfile`+`nginx.conf`, `docker-compose.yml` (backend/web/mariadb/minio/redis/orthanc), `.env.docker.example`, `docs/deployment.md`. `docker compose config` passes; full `docker compose build` not yet run |
| **P1.3** MariaDB cutover | ✅ done — `database.py` env-driven `DATABASE_URL` + dialect-branched pool (`max_overflow=30`, `pool_timeout=10`, LIFO, `READ COMMITTED`, `charset=utf8mb4`) + `DB_BACKEND`; `PyMySQL==1.1.1`; `RoomClaim` active-unique restored via VIRTUAL generated columns + `UniqueConstraint` (Alembic `9f2c8a1b7e4d`); `create_all()` + `_migrate_lightweight()` both guarded to SQLite only (`_IS_SQLITE`); `backend/db/mariadb/10-accounts.sh` = 3 least-priv accounts + `MAX_USER_CONNECTIONS`. Verified on fresh SQLite + real MariaDB 11.4. voltagent DBA review actioned; audit_logs append-only → P2.9 (trigger) |
| **P1.2b** MariaDB DATETIME(6) | ✅ done — `models.TZDateTime` variant on all 52 timestamp cols; audit read `id`-tiebreak; mysql-only Alembic `a1b2c3d4e5f6` (`MODIFY … DATETIME(6)`, no-op on SQLite). Verified both engines, autogen zero-ops. Found (unrelated): `5e6a60dfe274.downgrade()` is FK-unsafe on MariaDB → P1.5 |
| **P1.4** data migration | ✅ done — `backend/db/migrate_sqlite_to_mariadb.py` + README. Pre-flight scan (FK orphans / over-length / ci-collisions / active-claim dup / bad JSON), FK-ordered copy, coercion, `--prune-orphans`, reconciliation report. Verified real MariaDB 11.4: demo `clarion.db` → 30 tables, all counts+checksums MATCH, app runs on migrated data. Demo DB has 2 real FK orphans (deleted user) → pruned |
| **P1.5** retire schema hacks | ✅ done — `_migrate_lightweight()` + `_backup_sqlite_*` + `create_all()` deleted from `main.py` (**Security Audit M9 closed**); `_ensure_schema()` = SQLite auto-`upgrade head`, MariaDB verify-or-refuse, pre-Alembic DB refused not stamped; `seed.py` uses `upgrade head`; `5e6a60dfe274.downgrade()` FK-safe on MySQL; new `db/check_schema.py` CI gate (PASS both engines). Local `clarion.db` rebuilt fresh |
| **P1.6** ObjectStore + MinIO | ✅ done 2026-08-30 (Claude, staged) — `backend/app/storage.py` (`ObjectStore` ABC + `LocalObjectStore` default + `MinioObjectStore`, env factory `CLARION_STORAGE_BACKEND`, 7 buckets, `sanitize_filename`/`validate_key`/`apply_object_meta`). 5 `*_path` cols → `*_object_key`+`_sha256`+`_bytes`+`_mime`. Alembic `84f653e6c999` (add) + `b7f1c0d94a2e` (drop) split so `db/migrate_uploads_to_objectstore.py` runs between. Every read/write site rewritten; API shape unchanged (no FE change). **voltagent security-audit actioned** — WORM buckets now created with `object_lock=True`+versioning + COMPLIANCE per-object retention on `put` (provisioning steps a go-live gate in `docs/deployment.md`); `enforce_upload_size` pre-`.read()` cap (`app/routers/_uploads.py`); `open_stream` conn-leak fix; server-side doc mime sniff; `ObjectStore.get_checked` sha256 verify on serves; `S3Error`→`ObjectStoreError` wrapping. Verified: `tests/test_storage.py` 32/32, `check_schema` PASS SQLite+MariaDB 11.4, real-MinIO smoke + full HTTP E2E on SQLite/MariaDB/MinIO, migrator against pre-P1.6 DB. `minio`/`argon2-cffi`/`pytest` pinned |
| **P1.9** edge proxy + TLS | ✅ done 2026-08-30 (Claude; agy CSP sweep + voltagent infra-security review) — NEW `proxy/Caddyfile` (Caddy 2.8): the single TLS-terminating entry point + the one place the stack's security headers live. TLS via `CLARION_TLS_DIRECTIVE` (demo `tls internal` / prod CAMPUS-CA cert in `proxy/certs/`). HTTP→HTTPS 308, HSTS+preload, strict CSP (`script-src 'self'`, `style-src` keeps `'unsafe-inline'`, NFC bridge via `CLARION_CSP_CONNECT_EXTRA`, no `upgrade-insecure-requests`), X-Frame DENY, COOP/CORP/Permissions-Policy, `-Server`. Routes `/api/*`→backend (strip prefix), rest→web. **compose:** NEW `proxy` is the only host-port publisher (80/443); `web`+`backend`→`expose:` only; network `172.28.0.0/16` + `ip_range .10.0/24`, proxy pinned `172.28.0.2` = the `FORWARDED_ALLOW_IPS` anchor. Fixed a pre-existing crash: `uvicorn-worker` 0.3.0→0.4.0 (0.3.0 dies on uvicorn ≥0.36 — stack had never booted). Verified live: HTTP→HTTPS, all headers, `/api` routing, `/config.js`, SPA load, **XFF-spoof rejected** both through-proxy and direct-to-backend. **voltagent infra-security review actioned (verdict: sound):** M1 HSTS `preload` dropped + `{$CLARION_HSTS:max-age=300}` env-driven; M2 edge `servers{}` timeouts + `max_header_size` + `protocols h1 h2` + `trusted_proxies static` + `strict_sni_host`; M3 TLS floor `tls1.2 tls1.3` pinned; M4 healthcheck → plain-HTTP `/healthz`; **M5 network split** `edge`/`internal` (web walled off from data tier — residual: data tier↔backend, → P1.11-rem); L2 `style-src-elem/attr` split; L5 body cap 16MB; L6 `encode` off `/api`. **Bug fixed:** `_ensure_schema()` raced across gunicorn's 4 workers on the SQLite file → added `_schema_lock` (POSIX flock). Re-verified full stack + 66 tests. Prod TODO: real cert + full `style-src` tighten. |
| **P1.8** env-driven config | ✅ done 2026-08-30 (Claude; agy sweep + voltagent review) — backend CORS was already env-driven (`main.py` `CORS_ALLOWED_ORIGINS` allowlist, fail-safe closed off-`demo`, `allow_credentials=False`); Flutter already `--dart-define` + Settings override. **Wired the web SPA to the runtime config:** `web/index.html` loads `/config.js` (classic, `<head>`, before the deferred module); `web/src/api/client.js` `API_BASE = resolveApiBase()` = `window.__CLARION_API_BASE__` → `import.meta.env.VITE_API_BASE` → `http://localhost:8000` (trailing slash trimmed); NEW `web/public/config.js` dev stub; `web/vite.config.js` dev-proxies `/api`→`VITE_DEV_API_PROXY`; NEW `web/.env.example`. **`web/entrypoint.sh` hardened** — `$API_BASE` validated before it's interpolated into the JS literal. **voltagent security review actioned (6):** F1 entrypoint injection (done); F2 removed `--forwarded-allow-ips "*"` from `backend/Dockerfile` → env `FORWARDED_ALLOW_IPS` (default `127.0.0.1`), else a spoofed `X-Forwarded-For` bypassed every per-IP rate limit; **F3 → Security Audit M3 RESOLVED**: `main.py` CORS now fails **closed**, wildcard needs explicit `APP_ENV=demo`; F4 TLS→P1.9; F5 `VITE_`-bleed doc; F6 prod `console.error` on localhost fallback. agy confirmed no other must-fix hardcoded hosts (DB/MinIO/ports env-driven; bridge + healthchecks legit-local). Legacy `mobile/` RN client still hardcodes `localhost:8000` → dies with P0.2. Verified: `npm run build` clean, config load order, injection guard (7 inputs), CORS matrix + preflight E2E, `pytest` 66 pass |
| **P1.10** LDAP/AD provider | ✅ done 2026-09-07 (Claude direct — agy delegation blocked on a missing write-grant, `--yolo` deliberately withheld for an auth-critical module) — NEW `backend/app/ldap_auth.py`: service bind → search (filter-injection-escaped) → user re-bind, empty-password pre-bind rejection (anonymous-bind bypass guard), `resolve_role_for_groups` (highest-priority `LdapRoleMapping` match, denies rather than defaulting a role). NEW `models.LdapRoleMapping` + `User.auth_source`/`ldap_dn`/`ldap_username`. `auth_router.login()`: Case A JIT-provision, Case B re-bind + role/facility resync every login, Case C (local) unchanged; LDAP failures feed the same per-account lockout. Admin CRUD `GET/POST/PUT/DELETE /admin/ldap-role-mappings`. **Bug found + fixed (repo-wide):** `alembic/env.py`'s `fileConfig()` was silently disabling every already-created `app.*` logger — fixed with `disable_existing_loggers=False`. **voltagent security review actioned (1 Critical + 4 High + 4 Medium + 3 Low):** C1 identity was keyed on `email` (the directory's `mail` attribute) instead of the raw login string — broke re-login + group-revocation-resync under any non-mail `LDAP_USER_SEARCH_FILTER` (i.e. realistic `sAMAccountName` AD logins) — fixed with a new `User.ldap_username` column as the real identity key (Alembic `90f10b24a6db`); H1 unthrottled LDAP DoS on `/auth/login` → `threading.Semaphore` concurrency gate; H3 `/admin/ldap-role-mappings` let any admin set an arbitrary `facility` (cross-tenant escalation) → restricted to the acting admin's own; H4 ldap3's default `Tls()` is `validate=CERT_NONE` (verified against the installed `ldap3==2.9.1` directly) → explicit `CERT_REQUIRED` + `LDAP_CA_CERT_FILE`; M1 `role="patient"` was assignable → restricted role set; M2/M4 uniqueness races could 500 → `IntegrityError` → 409/fallback; M3 plaintext LDAP was a silent default → fail-closed unless `LDAP_ALLOW_INSECURE_BIND`; L1–L3 search size limit, fail-loud config validation, broadened exception safety. Test coverage: **test_ldap_auth.py → 23 tests**, NEW **test_admin_ldap_role_mappings.py → 10 tests**. Verified: **106/106 pytest pass**, `check_schema` PASS through the new revision, `pyflakes` clean, `_make_tls` behavior confirmed live against the installed ldap3. No web UI yet for the role-mapping table (API only) |
| **P1.12** pytest suite scaffold | ✅ done 2026-09-07 (Claude direct) — NEW `backend/tests/conftest.py` (`test_client`/`db_session`/`make_user`/`auth_headers` fixtures, consolidating what P1.10's test file had rolled ad hoc) + NEW `test_auth_rbac_immutability.py` (7 tests: RBAC, page-access gating, cross-facility clinical-record immutability — cross-facility denied+audit-logged, same-facility-but-absent still denied, same-facility-and-present allowed). Verified: all pass alongside the full suite |
| **P1.7** image normalisation | ✅ done 2026-08-30 (Claude) — `backend/app/imaging.py` (pure Pillow: EXIF/GPS/ICC/XMP strip via `info.clear()`, auto-orient, ≤2500px, progressive JPEG q82, 300px thumb; **24MP** bomb ceiling + `Semaphore(4)` decode gate + `Image.open(formats=[...])` allowlist — no TIFF; all Pillow errors → `ImageProcessingError`) + `backend/app/derived.py` (`clarion-derived` bucket, **sha256-scoped** keys `{variant}/{bucket}/{key}.{sha8}.jpg`, regenerate-on-miss, negative-cache marker, propagates `ObjectStoreError`). Medicine photos normalised **in place** (fail → 422, never store un-stripped); clinical-doc originals **never modified** (WORM), preview only; doc-thumbnail prime runs in the threadpool. Endpoints `GET /pharmacy/inventory/{id}/image/thumbnail` + `GET /patients/{id}/documents/{docId}/thumbnail` (503 on outage). `thumbnail_url`/`thumbnail_available` in API. **No schema change.** Sync-at-upload (async worker = P1.7b). **voltagent security + arch review actioned** (1 bug + ~15 fixes). 66 tests, `check_schema` PASS, E2E on SQLite+MariaDB+MinIO |

Files touched: `backend/app/ai/{_cloud_guard.py,summarize.py,nric_ocr.py}`,
`backend/app/{models.py,database.py,main.py}`, `backend/app/routers/patients.py`,
`backend/{requirements.txt,.env.example}`, `backend/alembic/` (incl. `env.py` +
`versions/9f2c8a1b7e4d_*`, `versions/a1b2c3d4e5f6_*`), `backend/alembic.ini`,
`backend/app/seed.py`,
`backend/db/{mariadb/10-accounts.sh,migrate_sqlite_to_mariadb.py,check_schema.py,README.md}`,
`backend/.gitignore`, `backend/Dockerfile`, `backend/.dockerignore`,
`web/{Dockerfile,nginx.conf,entrypoint.sh,.dockerignore}`, `docker-compose.yml`,
`.env.docker.example`, `.gitignore`, `.gitattributes`, `docs/deployment.md`,
`backend/alembic/versions/5e6a60dfe274_*` (downgrade FK-safety).

P1.6 also touched: `backend/app/storage.py` (NEW), `backend/app/routers/_uploads.py` (NEW),
`backend/tests/test_storage.py`, `backend/db/migrate_uploads_to_objectstore.py` (NEW),
`backend/alembic/versions/{84f653e6c999,b7f1c0d94a2e}_*` (NEW),
`backend/app/routers/{profile,ai_router,patients,admin,pharmacy,consultation,auth_router,self_registration}.py`,
`backend/app/{models.py,schemas.py,seed.py}`, `backend/{requirements.txt,.env.example,.gitignore}`,
`docs/deployment.md`.

P1.7 also touched: `backend/app/{imaging.py,derived.py}` (NEW),
`backend/tests/{test_imaging.py,test_derived.py}` (NEW),
`backend/app/routers/{admin,pharmacy,ai_router,patients,_uploads}.py`,
`backend/app/schemas.py`, `docs/deployment.md`.

P1.8 touched: `web/index.html`, `web/src/api/client.js`, `web/vite.config.js`,
`web/entrypoint.sh`, `web/public/config.js` (NEW), `web/.env.example` (NEW),
`backend/app/main.py` (CORS fail-closed), `backend/Dockerfile` (drop
`--forwarded-allow-ips "*"`), `docker-compose.yml` + `.env.docker.example`
(`FORWARDED_ALLOW_IPS`), `backend/.env.example`, `docs/deployment.md`,
`healthcare/Security Audit.md` (M3 resolved).

P1.9 touched: `proxy/Caddyfile` (NEW), `proxy/README.md` (NEW),
`proxy/certs/.gitkeep` (NEW), `docker-compose.yml` (proxy service, 2-network
split `edge`/`internal`, expose-only web/backend), `.env.docker.example`,
`.gitignore` (`proxy/certs/*`), `backend/requirements.txt` (`uvicorn-worker`
0.4.0), `backend/app/main.py` (`_schema_lock` — gunicorn multi-worker migrate
race), `web/nginx.conf` (X-Frame DENY + `/api` no-edge-fallback comment),
`docs/deployment.md`.

P1.10 touched: `backend/app/ldap_auth.py` (NEW), `backend/app/models.py`
(`LdapRoleMapping`, `User.auth_source`/`ldap_dn`/`ldap_username`),
`backend/alembic/versions/{1b4bf5c769e9,90f10b24a6db}_*` (NEW),
`backend/app/routers/auth_router.py` (login() LDAP wiring),
`backend/app/routers/admin.py` (ldap-role-mappings CRUD + facility guard),
`backend/app/schemas.py` (`LdapRoleMapping*`, `LDAP_ASSIGNABLE_ROLES`),
`backend/requirements.txt` (`ldap3`), `backend/.env.example`,
`docs/deployment.md`, `backend/tests/{test_ldap_auth.py,
test_admin_ldap_role_mappings.py}` (NEW), `backend/alembic/env.py`
(`disable_existing_loggers=False` fix).

P1.12 touched: `backend/tests/conftest.py` (NEW),
`backend/tests/test_auth_rbac_immutability.py` (NEW).

P2.1 touched: `backend/app/routers/emergency.py` (require_page_access +
`_require_patient_present_for_staff`, imports `_patient_present_at` from
`patients.py`), `backend/tests/test_emergency_access_control.py` (NEW),
`healthcare/Security Audit.md` (H1 resolved).

P2.2 touched: `backend/app/routers/patients.py` (`_facility_known_patient_ids`,
`_patient_known_to_facility`, `list_patients` scoping+pagination+break-glass,
`get_patient_full_record`'s cross-facility audit flag),
`backend/tests/test_patients_facility_scoping.py` (NEW),
`web/src/api/client.js` + `web/src/pages/PatientList.jsx` (pagination +
break-glass search UI), `healthcare/Security Audit.md` (H2 resolved).

P2.3 touched: `backend/seed.py` (demo-gated password generation),
`backend/app/schemas.py` (`MIN_PASSWORD_LENGTH` 8→12,
`_WEAK_PASSWORD_DENYLIST`), `backend/tests/test_seed_password_policy.py`
(NEW), `README.md` + `docs/deployment.md` (production seeding behavior
documented), `healthcare/Security Audit.md` (H3 resolved).

P2.4 touched: `backend/app/routers/{auth_router,self_registration,patients,
reception}.py` (per-IP rate limits, lockout-reset fix, indexed NRIC lookup
reused across all 4 call sites), `backend/app/models.py`
(`Patient.normalized_national_id` + `@validates` sync hook),
`backend/alembic/versions/649f25aeb36f_*` (NEW), `backend/tests/conftest.py`
(`_reset_rate_limiter` autouse fixture),
`backend/tests/test_login_rate_limiting.py` (NEW),
`healthcare/Security Audit.md` (M1/M2 resolved).

P2.5 touched: `backend/app/models.py` (`RefreshToken`), `backend/app/auth.py`
(`ACCESS_TOKEN_EXPIRE_MINUTES` 8h→15min, `REFRESH_TOKEN_EXPIRE_DAYS`,
issue/rotate/revoke_refresh_token), `backend/app/schemas.py`
(`Token.refresh_token`, `RefreshTokenRequest`),
`backend/app/routers/auth_router.py` (`/auth/refresh`, `/auth/logout`,
cookie helpers, password-change now revokes-everywhere),
`backend/app/main.py` (CORS `allow_credentials`),
`backend/alembic/versions/c4f34fe29451_*` (NEW),
`backend/tests/test_refresh_tokens.py` (NEW), `web/src/api/client.js`
(withCredentials, refresh-and-retry interceptor, real `/auth/logout` call),
`mobile_flutter/lib/services/{api_client,token_storage}.dart` +
`lib/providers/auth_provider.dart` (refresh token storage + interceptor +
logout call), `healthcare/Security Audit.md` (M4 resolved).

P2.6 (in progress) touched so far: `backend/app/imaging.py`
(`validate_image_safe_to_decode`), `backend/app/routers/ai_router.py`
(digitise_document safety gate), `backend/tests/test_digitise_document_safety.py`
(NEW), `healthcare/Security Audit.md` (M5 partially resolved -- the
AV-hook half was re-scoped as PTM/host-level per the tender's own clause
text + Compliance Matrix, not built as app code).

## Next up

**P2 (security/compliance) and P3.1–P3.8 (every tender module in the P3
table) are all done**, landed 2026-09-07 through 2026-09-13. **P4.3's core
landed 2026-09-13**: `backend/app/ai/local_llm.py` (local Ollama client)
replaced every Claude-API call in `ai/summarize.py`/`ai/nric_ocr.py` —
**Security Audit C1 is now actually resolved**, not just interim-guarded;
`ai/_cloud_guard.py` and the `anthropic` dependency are gone. See
`healthcare/Implementation Roadmap.md`'s changelog for detail — that file
is the source of truth, this file is not kept blow-by-blow.

**P4.3b (CDS hint) and P4.3c's voice→SOAP half both landed 2026-09-13**:
`backend/app/ai/cds_hint.py` + `ai/voice_soap.py` (`faster-whisper` +
local-LLM segmentation), both wired into the sign-off modal
(`web/src/pages/PatientList.jsx`) — a clinician-facing reference note, a
deterministic allergy-vs-active-medication conflict flag, and a "🎙
Dictate SOAP" button.

**P3.9 + P3.10 landed 2026-09-14** (calling-system ESC/POS ticket +
sample-label printing + TV audio/branding; mobile self-service booking by
dept/doctor, vitals view, visit-summary PDF, announcements), then
voltagent security-auditor + flutter-expert reviewed it and 4 real findings
(1 Critical timezone bug that broke self-booking on real devices, a
missing DB-level double-book guard, ESC/POS command injection, a stale-
response UI race) were all fixed and pushed — see
`healthcare/Implementation Roadmap.md`'s changelog for full detail.

**P4.3c finished 2026-09-14** (NL report narrative — local-LLM prose over
the Reporting engine's structured output, `POST /reports/narrative`):
**all of P4.3 is now done**. voltagent security-auditor reviewed it clean;
incidentally fixed a pre-existing `await`-in-non-async-callback bug in
`HospitalSettingsTab.jsx` that broke `npm run build` outright (from the
P3.9 commit). 409/409 backend tests pass.

**P4.7 core landed 2026-09-14** (DICOM viewer, the last unstarted top-5 demo
priority): `backend/app/pacs.py` + `backend/app/routers/pacs.py` (Orthanc
REST client + the auth/facility-scoping boundary in front of it, reusing
ancillary.py's own `_request_or_404`/`_hidden_author_facilities`),
`models.DicomStudy`, `web/src/components/DicomViewer.jsx` (embeds `dwv`,
its API verified against the library's real source before writing).
Deliberately a **scoped core slice, not the full clause**: manual upload
against an X-ray `ServiceRequest` stands in for real Modality Worklist
hardware this environment doesn't have (documented go-live TODO, same class
as P1.9/P3.9's deploy-time gaps) — see the roadmap changelog for why P4.7
is 🟡 not ✅. voltagent security review caught and fixed one real bug (a
zip-bomb bypass via a trusted, attacker-controllable declared size — see
that changelog entry). agy's docs-delegation failed outright on auth in
this headless session (see `agy-delegation-flakiness` memory) — Claude
wrote `docs/deployment.md`'s new section directly instead. 423/423 backend
tests pass, web build/lint clean.

**P4.1 + P4.2 landed 2026-09-14** (FHIR coding-triple columns on
Condition/MedicationStatement/AllergyIntolerance/ServiceCatalogItem + NEW
`resource_identifiers` table + a read-only FHIR façade router,
`backend/app/routers/fhir.py`, over 8 resource types reusing the
already-audited `patients.py` cross-facility read policy). Deliberately no
fabricated ICD-10/MyDrug/LOINC seed list and no new tables for resources
CLARION's existing tables already cover — see the roadmap changelog. agy
wrote the test file from a tight spec (verified line-by-line, then re-run
independently, not trusted on its own report); Claude wrote every
resource-mapper/route directly. 432/432 backend tests pass, `check_schema`
PASS. Same session, a **fresh, independent voltagent security-auditor pass
over P4.7** (re-derived from the code, not from the prior review's
changelog claim) confirmed the zip-bomb fix and facility-scoping are both
still sound — no new findings.

Next: every top-5 demo priority is now done, and P4.1/P4.2 close one more
gap in the Compliance Matrix. Remaining backlog is P4.7's own go-live TODOs
(Orthanc auth + PG/S3 plugins + real Modality Worklist), P4.4
(medication-safety rule engine), or the P4.x items with no status yet
(P4.5/4.6) — surface the choice rather than assuming order, same discipline
as every prior phase boundary.

**P2.9 leftover:** the migration (`b2d7e4a9c1f6`) has only been run on
SQLite this session — a real `alembic upgrade head` on MariaDB is still
owed (no local DB creds). It uses the same dialect-branched patterns as the
other MariaDB-verified migrations.

**Ongoing housekeeping:** existing test files predating `tests/conftest.py`
(`test_storage.py`/`test_imaging.py`/`test_derived.py`/`test_ldap_auth.py`)
still carry their own setup where applicable — dedup opportunistically, not
urgent.

**P1.9 leftovers (deploy-time, not code):** drop the CAMPUS-CA cert pair in
`proxy/certs/` and set `CLARION_TLS_DIRECTIVE` to the file form; wire MariaDB
`REQUIRE SSL` + MinIO TLS into the same story (P2.7); tighten CSP `style-src`
off `'unsafe-inline'` (hash/nonce); any voltagent-review follow-ups.

**P1.8 leftover:** the legacy React-Native `mobile/` app (`mobile/api/client.js`
hardcodes `http://localhost:8000`) is untouched — slated for deletion in **P0.2**.

**P1.7 loose ends (see the roadmap progress-log note + voltagent review):**
normalisation is synchronous-at-upload — moving the heavy path to a background
worker (Redis is provisioned) is a later call keyed on payload size/volume. PDF
documents get no thumbnail yet (first-page render needs pypdfium2/pdf2image).
`clarion-derived` needs its MinIO ILM rule (`mc ilm rule add --expire-days 30`)
wired at deploy — see `docs/deployment.md`.

**P1.6 loose ends:** `docker-compose.yml` needs the `minio` service env wired to
the backend. `backend/uploads/` (old tree) can be deleted once a real deployment
has run `db/migrate_uploads_to_objectstore.py`.

Small follow-ups: sweep remaining naive `datetime.utcnow()` in `auth.py`/routers/
`seed.py` to aware (no live bug — pymysql coerces aware→naive-UTC on write, so
it's consistent, but any code that assumes an *aware* value back from MariaDB
will `TypeError`); NIH RxNav/DailyMed calls in `ai/interactions.py` still need an
offline path (P4.4); audit_logs append-only enforcement owed at P2.9 (trigger);
FK `ondelete` uniformity (DBA review S3) → do it when a Patient delete/merge path
is built; SSL `connect_args` / account `REQUIRE SSL` → with the TLS work
(P1.9/P2.7); wire `db/check_schema.py` into real CI at P2.11.

## The one thing to never regress

the tender forbids third-party AI cloud APIs. Keep all inference local.
See `healthcare/Security Audit.md` finding **C1** and `healthcare/On-Prem Clinical AI.md`.

## Working style for this project

- The user drives; they handle all git commits. Don't commit or branch unless asked.
- Delegate bulk/mechanical work to **agy** and to **voltagent** specialists;
  **Claude verifies every output in a clean state** before marking anything done.
  Update the progress log in `healthcare/Implementation Roadmap.md` as you go.
- **agy delegation caveats (learned the hard way, P1.3–P1.6):** agy's self-reported
  "GREEN" is unreliable — it dropped `SessionLocal`, silenced FK checks, botched
  `--force` semantics, wrote BOM+CRLF. Worse, a `--yolo` job can run **detached**
  and keep editing files after the subagent reports done (P1.6: it raced Claude's
  cleanup edits). So: **never `--yolo` a cross-cutting refactor**; prefer tight
  single-file specs; after any delegation, `Get-Process agy` to confirm it's dead
  before editing, then diff every file and re-run the real gate.
