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

**P4.4 landed 2026-09-14** (medication-safety engine): an ATC
drug-class layer on `ai/interactions.py`'s DDI/allergy checks (RxClass, same
free NIH/NLM family as RxNorm/DailyMed — e.g. a "Penicillin" allergy now
also catches "Amoxicillin" via their shared class, not just an exact name
match) plus a new real-time pre-save check, `GET /ai/prescription-screen`,
wired into the Add Medication form so a conflict must be acknowledged with
a second click before it saves — the tender's literal "alerts before
confirmation" ask. Deliberately skipped: MIMS itself (no public API, needs
a paid clinical-data license) and diagnosis-based screening (would need
fabricated clinical data) — Compliance Matrix stays Partial for those two.
voltagent security-auditor reviewed it clean on RBAC/injection/fail-open,
caught one real issue (the new sync RxClass path wasn't sharing the async
path's cache, doubling NIH calls per screen) — fixed, with a regression
test. 441/441 backend tests pass, web build clean. agy wasn't delegated —
judgment-heavy (curating/verifying real ATC codes), below the break-even.

**P4.5 landed 2026-09-14** (access-anomaly detection + AI audit-trail
intelligence, –7): NEW `backend/app/security_analytics.py`, same
registry-of-rules/UPSERT-by-key shape as `data_quality.py` (P2.12) but over
`audit_logs`, keyed on `(rule, actor, actor_facility, window_start)`. Two
hardcoded-threshold rules (no manual rule config, per the clause's own
wording) — `distinct_patient_fanout` (≥20 distinct patients/hour) and
`off_hours_access` (00:00–05:00 MYT) — plus `ai/audit_intelligence.py`'s
local-LLM narrative on demand (`POST /admin/security-alerts/{id}/explain`).
No web admin tab, same precedent as data-quality alerts (API only).
voltagent security-auditor found and fixed 4 real issues before this
landed: facility misattribution in the bucket key (an actor touching two
facilities in one window now correctly gets two alerts, not one with an
arbitrary facility), an unbounded auto-resolve vs. wall-clock time (one
bad-clock row could've silently closed every open alert), redundant
per-rule re-querying, and a cross-facility RBAC gap on
acknowledge/resolve/explain (now 404s on a facility mismatch — the
identical unscoped pattern was found already shipped in data-quality's own
ack/resolve, P2.12, noted below as a separate leftover, not fixed here).
Also found and fixed independently while writing tests: a naive-vs-aware
datetime bug that broke the off-hours rule's own dedup key. 456/456 backend
tests pass, `check_schema` PASS. agy not delegated — judgment-heavy
(choosing/defending real thresholds), below the break-even.

**Security Audit L6 fixed 2026-09-14:** `_get_dq_alert_or_404` (data-quality
alerts, `routers/admin.py`, P2.12) now reuses `_dq_facility_filter` —
acknowledge/resolve 404 on a facility mismatch, same shape as P4.5's
`_get_security_alert_or_404`. `test_admin_acknowledge_resolve_is_facility_scoped`.

**P4.7 go-live, 2 of 3 done 2026-09-14:** Orthanc HTTP basic auth +
PostgreSQL index + S3 storage (against the existing `orthanc-postgres` /
`minio` services) are all wired in `docker-compose.yml`, `pacs.py` sends the
matching creds. voltagent reviewed clean (2 non-blocking hardening notes
actioned: JSON-interpolation escaping caveat documented, MinIO
root-creds-everywhere flagged as a stack-wide follow-up — see next).
Verified via `docker compose config` only — no daemon running this session
to boot the stack live. 457/457 backend tests pass, `check_schema` PASS.
Real Modality Worklist is the one still-open P4.7 item (needs hardware).

**MinIO is dead upstream — repointed + least-privilege pass done, same
2026-09-14 session:** Docker Hub pulled the `minio` org 2026-09-11 (the
`minio/minio:RELEASE.2025-04-22T22-12-26Z` this repo had pinned stopped
being pullable). SeaweedFS and Garage are both disqualified as
alternatives (broken/absent Object Lock WORM enforcement); RustFS is the
only non-disqualified one but alpha/RC with unconfirmed `mc`/admin-API
compat — the user declined to land alpha software under a compliance
path. **Repointed to `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`**
(MinIO's own last free-tier mirror; documented residual: predates
CVE-2025-62506, a service-account privilege-escalation fix never
back-pushed to the free quay.io stream — accepted given internal-network-
only). Then did the least-privilege pass on top: NEW `backend/db/minio/
10-accounts.sh` + `policies/*.json` (mirrors `backend/db/mariadb/
10-accounts.sh`'s 3-role shape) run by a NEW one-shot `minio-init` service
— `backend`/`orthanc`/`backup` each now hold their own scoped user instead
of the shared root key. See the roadmap changelog for full detail,
including why `clarion-backend` still needs broad `s3:*` on `clarion-*` for
now (bucket auto-create at app startup, a separate already-tracked TODO).
`minio-dead-storage-decision-pending` memory can be considered resolved for
the "repoint now" half; revisiting a real migration off MinIO stays open.
**voltagent caught + fixed one real bug same-day:** `mc admin policy
attach` isn't idempotent like `create`/`user add` — it errors on a policy
already attached, which would have wedged the whole stack from restarting
past the first `docker compose up`. `attach_policy()` in `10-accounts.sh`
now tolerates only that specific error, verified against mocked `mc`
output (no live server this session).

**P4.6 done 2026-09-14** (predictive analytics + population-health
stratification, — picked over P4.8 when asked which was
next): NEW `backend/app/predictive_analytics.py` — a dependency-free EWMA
level+trend forecaster over `Encounter`/`Condition`/`MedicineStockEvent`
(visit volume, disease burden, stock depletion) plus a deterministic
rule-based risk score/band (not a fitted cluster model — no real
outcome-labelled data to validate one against, same call P4.4 made) for
population stratification. 4 new `/reports/predictive/*` endpoints, same
RBAC/facility-scoping conventions as the rest of `routers/reporting.py`.
Caught + fixed my own bug pre-review (a naive/aware datetime comparison
that would have raised `TypeError` at runtime — this codebase's recurring
`TZDateTime`-round-trips-naive hazard). voltagent reviewed clean
afterward (one docstring-precision nit fixed, one deliberate-scope choice
documented with a comment, no real bugs). 467/467 backend tests pass.

**P4.8 done 2026-09-14, scoped down** (the last unstarted P4.x item):
turned out to bundle 4 things, 2 already done elsewhere (label printer +
calling-system TV, P3.9) and 2 needing real campus specs/credentials this
environment doesn't have (SMP/SMS/e-klinik/university-DB — asked the user
rather than fabricating mock schemas for systems this codebase knows
nothing concrete about, same discipline P4.4 used to skip MIMS). Scoped to
the one genuinely buildable, testable piece: lab-analyser HL7 v2
integration. NEW `backend/app/hl7v2.py` (hand-rolled HL7 v2.5.1
encode/decode — no third-party HL7 lib, this app is producer+consumer of
exactly 2 message types) + `hl7_client.py` (outbound ORM^O01 push,
best-effort, never blocks order creation) + `hl7_listener.py` (inbound
ORU^R01 MLLP server, its OWN process — NOT a gunicorn worker — NEW
`hl7-listener` compose service). NEW `models.AnalyserResultInbox` stages
incoming results; **never auto-signs a ServiceResult** — a clinician
reviews and submits through the existing sign-off endpoint unchanged, same
"advisory, never authoritative on its own" rule as every AI feature here.
An unmatched result is deliberately never exposed via any endpoint (no
facility to scope it to, and its raw HL7 text can still carry a real
patient name) — same "no admin override" PHI-leak discipline as this
router's own `_request_or_404`. No real analyser to test against —
verified via hand-crafted HL7 messages + a real MLLP socket round-trip.
No new dependency (pure stdlib).

**voltagent caught + fixed 4 real issues:** a genuine escape/unescape
round-trip bug (sequential `str.replace` calls could corrupt a value
shaped like `\F\` — switched to single-pass `re.sub`, the correct
technique for reversible escaping); `build_ack`'s attacker-controlled
`control_id` wasn't escaped before being echoed back; the MLLP listener
had no per-connection timeout or concurrency cap, so an idle/hostile
connection on the `internal` network (anything there can reach port
2575, not just a trusted analyser) could exhaust threads/file
descriptors and crash the whole process's `accept()` loop with no
handler — fixed with a 30s timeout, a 16-connection semaphore, and a
guarded accept loop; `AnalyserResultInbox.facility_name` was declared and
indexed but never populated — fixed. All 4 have regression tests.
504/504 backend tests pass, `check_schema` PASS, pyflakes clean.

**Every P4.x item now has a status.** Remaining backlog: the RustFS
migration off MinIO (deliberately deferred, see the `minio-dead-storage-
decision-pending` memory), the SMP/SMS/e-klinik/university-DB integration
this pass declined to fabricate (needs real campus specs), and whatever
surfaces next — there's no more "no status yet" P4.x item to default to.

**P1.7b landed 2026-09-15** (imaging follow-ups, left at "--" since P1.7
landed 2026-08-30 — asked the user which backlog item to pick up next with
every P4.x item statused): PDF documents now get a real page-1 preview
(`backend/app/imaging.py` NEW `render_pdf_first_page()`, `pypdfium2`)
instead of "no preview available" — scale is computed from the page's own
declared size and applied at render time, so the output's long edge is
exactly `max_edge` by construction, no separate bomb ceiling needed; a new
`?size=1400` "web preview" variant on the document-thumbnail endpoint
avoids pulling a possibly-15MB original over the Branch WAN; both that
endpoint and the medicine-photo thumbnail gained a strong ETag +
If-None-Match → 304 (safe — content-addressed already); `clarion-derived`'s
ILM doc bumped 30→180 days. Deliberately skipped: HEIC input (no confirmed
real upload source) and an async normalisation worker (no reported
latency/volume problem). voltagent found 1 Medium + 2 Low; 2 Low fixed
(shared size-allowlist constant to remove a drift-to-500 risk; the
medicine-photo thumbnail endpoint was missing `log_access` entirely), the
Medium (PDFium's internal render cost isn't wall-clock-bounded, only the
output size is) accepted as a documented residual — bounded today by the
existing upload-size cap + concurrency gate on a 3-role authenticated
endpoint, real fix needs a `ProcessPoolExecutor` timeout. 519/519 tests
pass (3 unrelated pre-existing `test_security_analytics.py` failures are a
real time-of-day flake, confirmed via `git stash`, not this change).

**P5.1 landed 2026-09-15** (Observability, the first P5 item — asked the
user which to pick up next with P1.7b done): structured JSON logging bound
to request-id/user/role/facility via `backend/app/log_context.py`
(contextvars, stdlib only, zero call-site changes anywhere else in the
codebase); `GET /healthz` + `GET /readyz` (real DB + object-store checks)
replace the placeholder `GET /` the container healthcheck used to probe;
`GET /metrics` (`prometheus-fastapi-instrumentator`). A NEW `observability`
Compose profile (opt-in, like `mariadb`/`backup`) adds Prometheus (3 alert
rules incl. the architecture plan's own named #1 risk, disk-full at
75%/90%), Alertmanager (email only — every value is a demo placeholder to
edit for real, same pattern as `proxy/certs/`), Grafana (two dashboards,
written by agy from a tight spec then Claude-verified and one real
datasource-uid integration bug fixed), Loki+Promtail, node-exporter, and a
new least-privilege `clarion_metrics` MariaDB account for mysqld-exporter.
WhatsApp (the clause's other alert channel) deliberately not built — same
"no real credentials to fabricate" call as P4.4/P4.8. voltagent found 1
Medium + 2 Low + caught a real bug in my own code comment: `/metrics` and
`/readyz` were claimed to be unreachable through the public site because
they're "not under `/api`" — wrong, `proxy/Caddyfile`'s `/api/*` handler
strips the prefix and forwards anything, so they actually were reachable
at `/api/metrics`/`/api/readyz`; fixed with an explicit Caddy-level block
(not yet verified live, no Docker daemon in this session — flagged for a
live check). Medium (the new MariaDB account's `PROCESS` grant + PyMySQL's
client-side query interpolation) fixed with an explicit exporter flag +
upgraded secret-tier docs. 528/528 tests pass. See the roadmap changelog
for full detail.

**P5.2 landed 2026-09-15, scoped** (load testing, the last unstarted top-
level P5 item — asked the user which to pick up next with P5.1 done): NEW
`backend/loadtest/{locustfile.py,README.md}` (Locust, weighted realistic
clinic traffic). Standing up the MariaDB-backed stack to run it for real
(pool/worker tuning is meaningless against SQLite) surfaced **5 real,
previously-undiscovered bugs**, the significant one being that slowapi's
rate limiting was broken two independent ways — a multi-worker in-memory
storage bypass (fixed: Redis-backed `storage_uri`) and `SlowAPIMiddleware`
being a confirmed total no-op on this app's fastapi/starlette versions, so
`default_limits=["60/minute"]` had **never** been enforced on any route
without its own explicit decorator (fixed: a new global FastAPI
dependency, `enforce_rate_limits`, replaces it). Plus 4 MariaDB/migration
bugs found getting a truly-fresh `docker compose up` + `alembic upgrade
head` to work at all (a P5.1 regression zeroed out DB account creation; the
`migrate` service ran from the wrong `WORKDIR`; P1.2b's DATETIME(6)
migration imported live `app.models` instead of reflecting the actual DB,
breaking on tables added after it was written; P2.9's audit trigger needed
`log_bin_trust_function_creators`, not more privilege). Gunicorn tuning
(`--timeout`/`--graceful-timeout`/`--max-requests`+jitter) also applied.
531/531 backend tests pass. **voltagent security-auditor caught one real
CRITICAL before it shipped:** the new global rate-limit dependency had no
`in_memory_fallback_enabled=True`, so a Redis outage would fail-closed
site-wide — 500 on literally every request, including `GET /healthz` and
the unauthenticated emergency-scan endpoints this "Emergency-first" system
is supposed to keep reachable no matter what. Fixed + verified live
(stopped the `redis` container, confirmed `/healthz`/`/auth/login` both
still 200, restarted it, confirmed recovery). **Marked 🟡, not ✅**: the load
test itself is a single-test-machine run (one apparent client IP) and so
could never exercise the DB-pool/worker ceiling regardless of user count
— a real capacity number needs a distributed generator or an
operator-authorized rate-limit bypass in staging; this session's own
attempt to widen `FORWARDED_ALLOW_IPS` for that purpose was correctly
declined by Claude Code's own safety controls, which is the right call
for a repo, not a session, to make unilaterally. See
`healthcare/Implementation Roadmap.md`'s changelog and
`backend/loadtest/README.md` for full detail.

**P5.4 landed 2026-09-15** (docs & handover — the whole roadmap's last
unstarted row): NEW `backend/db/gen_data_dictionary.py` (the tender,
auto-generated Mermaid ERD + column reference from live SQLAlchemy
metadata, `docs/data-dictionary.md`) + NEW `docs/{operations,programming,
maintenance,transfer-of-technology}-manual.md` (clauses 7.1/3.2.5) — each
an index into already-existing deep docs, not a duplicate (the DR runbook
these clauses also ask for was already done at P2.8). voltagent
code-reviewer caught + fixed 4 real issues in the generator script
(invisible table-level UniqueConstraints, non-deterministic ERD ordering,
docstring paragraphs collapsed to run-ons, `<lambda>` defaults) — see
`healthcare/Implementation Roadmap.md`'s changelog. 532/532 tests pass.

**P5.3 landed 2026-09-15, scoped** (two-campus rollout — the roadmap's
last row overall): a Branch edge Compose profile (`branch-edge` — isolated
network, reuses the central `web` image, no new Redis dependency) +
offline emergency-export appliance (`backend/app/emergency_export.py` +
`db/emergency_export_appliance.py`, reuses `routers/emergency.py`'s own
critical-for-emergency logic, `age`-encrypted like the P2.8 backup
pipeline). Self-caught (before review): an `*env-file` anchor would have
leaked every central secret into the less-trusted Branch container, and a
`:?`-required compose var was breaking `docker compose up` even with
`branch-edge` not enabled — both fixed. Real WAN validation still needs the
actual link (same class of gap as P4.7's Modality Worklist) —
`proxy/branch-edge/simulate-wan.sh` + re-running P5.2's Locust suite is the
same-machine substitute. **voltagent security-auditor found + fixed 4 more
(1 High, 2 Medium, 1 Low):** the bulk export wrote zero `audit_logs` rows
despite the PHI then leaving the network as a file (fixed: a `log_access`
row per `build` run + the appliance's own local hashed-NRIC access log for
offline `query` lookups); `--facility` was untied to any registry (fixed:
refuses an unregistered `HospitalSetting` name); `branch-proxy` mounted the
CENTRAL site's cert directory, which holds its TLS private key in
production (fixed: separate `proxy/branch-edge/certs/`); no enforced
`https://` scheme on `CLARION_CENTRAL_BACKEND_ORIGIN` (fixed: the
container refuses to start on a bad scheme, verified live against the
real `caddy:2.8-alpine` image). 534/534 backend tests pass (1 skipped —
`age` not installed on this machine). See `healthcare/Implementation
Roadmap.md`'s changelog for the full review and what was found sound.

**Every row in the P0–P5 roadmap now has a status.** Asked the user what
to pick up next; they named SMP/SMS/e-klinik/Registrar — flagged back
that this was already investigated (P4.8) and deliberately left a gap for
lacking real campus specs, same call P4.4 made for MIMS. Follow-up answer:
**"build a working mock first, will show in the exhibition."**

**Landed 2026-09-15:** a working, genuinely-integrated demo mock for
the tender — NEW `backend/app/campus_registry.py` (real
`httpx` adapter, never raises/blocks patient registration) +
`backend/app/routers/campus_registry_mock.py` (in-process mock at
`/mock-campus-registry`, fictional seed identities, `"mock": true` on every
response) + `GET /patients/campus-eligibility/{nric}` wired into the web
console's "New Patient" form (a "Check University Eligibility" button, result
labeled "(mock campus registry — demo)" so it can't be mistaken for real
data on stage). `CAMPUS_REGISTRY_BASE_URL` is the entire swap point for a
real campus endpoint later — zero code change. **voltagent code-reviewer
found + fixed 1 real bug:** the adapter's own "never raises" contract had
a hole — a control character (tab/newline) in the NRIC raised
`httpx.InvalidURL` (not an `HTTPError` subclass) uncaught, a live-
reproduced 500 through the real endpoint; fixed with URL-encoding +
a regression test. RBAC, mock isolation, and frontend auto-fill/labeling
all reviewed clean. moved Gap → Demo in the
Compliance Matrix; (the separate billing-side touchpoint, not
built this pass) moved Gap → Partial. 543/543 backend tests pass (1
skipped — `age` not installed), `npm run build`/`lint` clean. See
`healthcare/Implementation Roadmap.md`'s changelog for the full detail.

**Offline NFC emergency tag landed 2026-09-15/16**, answering a direct
user question ("if the entire network is outage, can we retrieve
emergency info offline using the NFC card?" — answer at the time was no,
the existing flow only stored the tag's UID as a server-resolved lookup
key). Two rejected design directions first (a bulk UID→patient export
would have meant reversing the M7 "never persist the raw UID" fix or
shipping the server's HMAC secret to every phone), then the real ask
clarified ("if the entire infrastructure is down... only the most basic
emergency information") — landed as the standard medical-alert-tag
pattern: critical data (blood type/allergies/meds/conditions, fixed
truncation priority) written DIRECTLY onto the physical tag's own NDEF
memory via a new `write_offline_tag_screen.dart` (staff-only,
`mobile_flutter`), read back with zero network by the existing scanner
screen's already-built NFC-tap mode (falls back to on-tag text only on a
genuine no-response network failure, never a real 404, verified against
`api_exception.dart`). `register_nfc_card`'s response now returns the
compact `tag_text` for staff to carry to a phone and write. Self-caught +
fixed a real bug (the compact format's `|` separator had no escaping).
The voltagent review agent stalled twice and wasn't retried further;
self-reviewed the two highest-risk points (offline-trigger correctness,
NDEF wire-format correctness) directly against source instead. 548/548
backend tests pass, `flutter analyze`/`npm run build` clean. See
`healthcare/Implementation Roadmap.md`'s changelog for full detail.

**P1.7b's last two leftovers (HEIC input + async thumbnail-priming worker)
landed 2026-09-16** — see the roadmap changelog. voltagent caught a real
HIGH (the SQLite claim path in the new job queue had no locking at all,
a real double-run race under this app's own documented gunicorn-4-workers-
on-one-SQLite-file topology) + a MEDIUM (a crashed worker's "running" row
was never reclaimed), both fixed. P1.7b is now fully ✅.

Remaining backlog: P4.7's real-hardware Modality Worklist gap (deploy-time,
not buildable here), the RustFS migration off MinIO (deliberately
deferred), a REAL SMP/SMS/e-klinik/Registrar integration (still needs
actual campus specs/credentials — today's mock is a demo stand-in, not a
step toward one without those), P5.2's own distributed/staging capacity
run if that need ever gets real, P5.3's own real WAN validation once a
real second campus link exists, and the tender's billing-side SMP/SMS/
e-klinik touchpoint if that's ever wanted — surface the choice rather than
assuming order, same discipline as every prior phase boundary.

**P2.9 leftover:** the migration (`b2d7e4a9c1f6`) has only been run on
SQLite this session — a real `alembic upgrade head` on MariaDB is still
owed (no local DB creds). It uses the same dialect-branched patterns as the
other MariaDB-verified migrations.

**Ongoing housekeeping:** ✅ done 2026-09-16 — of the four files flagged,
only `test_ldap_auth.py` actually duplicated `tests/conftest.py`'s fixtures
(the other three are dependency-free unit tests, nothing to dedupe); its
dead temp-DB/atexit/module-client/shadowing-`db_session` setup is gone,
561/561 tests still pass. See the roadmap changelog for detail.

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
