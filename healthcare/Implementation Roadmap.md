---
title: Implementation Roadmap
type: plan
updated: 2026-09-07
tags: [plan, roadmap, clarion, campus]
---

# Implementation Roadmap — CLARION → University HealthCare

Phased plan from the current competition demo to a tender-grade system. Effort:
**S** = 1–3 person-days, **M** = 4–7, **L** = 8–15. Ordered by dependency — no phase
has a forward dependency on a later one. Backbone:
[[Compliance Matrix]], [[Security Audit]], [[On-Prem Architecture]].

> [!tip] Apply the [[Designing for the PHP Port]] checklist to **every** P1–P4 task as
> you write it — retrofitting portability later doubles the CI4 estimate.

## Progress log
- **2026-09-07** — **Code-review follow-up, third pass (closing the "still
  open" list).** LDAP facility-admin→admin-role mapping: made the secure
  call -- only a platform admin (no facility) may create an admin-granting
  LDAP mapping (`_check_mapping_authz`), reversible if the University disagrees.
  `PatientDetail.jsx` `exhaustive-deps` fixed properly (`useCallback`), no
  render loop -- **oxlint now 0 warnings**. Grace-window residual: every
  graced refresh race now logs a WARNING so it's detectable post-hoc (full
  device binding stays a tender-grade follow-up). Lower-sev N+1 +
  pagination: `_serialize_inventory_item` / `_serialize_admission` /
  `list_staff_roster` batch their per-row lookups; `GET
  /patients/{id}/audit-log` + `/annotations` gained `skip`/`limit` (default
  500). **Verified 159/159, build + oxlint clean.** Genuinely still open:
  the god-file splits + cross-router coupling (`admin.py`↔`pharmacy.py`
  inventory helpers, `consultation.py` calling `reception.py` route handlers
  directly) -- a dedicated reviewed refactor, plan in
  [[Security Audit#Third pass (2026-09-07) — closing the "still open" items]].
- **2026-09-07** — **Code-review follow-up, second pass (the deferred
  items).** CR9: refresh cookie `Path` was `/auth`, never sent on the
  documented `/api/auth/refresh` proxy path -> silent refresh dead ->
  re-login every 15 min; now `REFRESH_COOKIE_PATH` env, default `/`. CR10:
  concurrent browser tabs racing `/auth/refresh` no longer nuke every
  session -- `_is_concurrent_refresh_race` + `REFRESH_REUSE_GRACE_SECONDS`
  grace the just-rotated token, reuse outside the window still full-revokes.
  CR11: duplication extracted -- `backend/app/directory.py`,
  `web/src/lib/{format,upload,image}.js` (agy delegation was blocked on a
  missing write permission, so done directly from agy's recon). CR12: new
  `test_password_change_lifecycle.py` (2) + `test_otp_reset_step2.py` (4)
  close the access-token-watermark / `must_change_password` /
  OTP-reset-step-2 coverage gaps. Lint: `Login.jsx` catch binding,
  `display.get_display_feed` documented. **Verified: 158/158, npm build +
  oxlint clean.** Still open (need a decision, not code): the LDAP
  facility-admin→admin-role mapping policy; the `AdminConsole.jsx` /
  `admin.py` / `reception.py` god-file splits + cross-router private
  imports; lower-sev list-serializer N+1 + pagination. See
  [[Security Audit#Second pass (2026-09-07) — the deferred items]].
- **2026-09-07** — **Code-review follow-up (post P2.1–P2.6).** A full
  parallel-agent `/code-review` over the uncommitted `backend/` + `web/`
  tree surfaced one missed instance of the H1/H2 authz pattern plus perf /
  deploy-safety findings. Backend fixes landed together (Claude, direct):
  **CR1** deleted `backend/_debug_photos/` (real MyKad images + OCR'd
  NRIC/name/address, `.gitignore`-covered now) before it could be
  committed; **CR2** `GET /patients/{id}/appointments` now behind
  `require_page_access("patients")` + restricted to admin/clinician/
  records_officer for staff, with a distinct `view_appointments_cross_facility`
  audit action; **CR3** the public NRIC-OCR + document-OCR endpoints moved
  off the event loop (`run_in_threadpool` / `asyncio.gather`); **CR4**
  RxNorm/DailyMed lookups get a 1h TTL cache + one pooled `httpx` client;
  **CR5** the P1.6 `b7f1c0d94a2e` legacy-column drop now aborts unless the
  blob-move script has run (+ a `--profile migrate` compose service +
  runbook); **CR6** new migration `d5e8a1c4b6f2` adds the missing
  `patient_id` / facility / `(facility_name, queue_date)` indexes,
  `_serialize_patient` de-N+1'd, `list_patients` scope pushed into one SQL
  `UNION` subquery; **CR7** app-wide 500 handler with correlation id +
  logging on the swallowed ObjectStore-failure paths; **CR8** dropped
  unused `argon2-cffi*`, moved `pytest` to `requirements-dev.txt`. New
  `backend/tests/test_appointments_access_control.py` (7 tests).
  **Verified:** full suite **151/151 pass**, `alembic` up/down +
  `db/check_schema.py` round-trip clean, `pyflakes` clean. Web-side items
  (multi-tab refresh race, `Path=/auth` cookie vs `/api` proxy, LDAP
  facility-admin→global-admin, god-file splits) deferred — see
  [[Security Audit#Code-review follow-up (2026-09-07)]].
- **2026-09-07** — **P2.6 in progress (M5 partial).** Fixed the real,
  in-scope half of [[Security Audit#M5]]: `POST /ai/digitise/{id}` now
  validates an image-shaped upload through `imaging.validate_image_safe_to_decode`
  (new, reuses P1.7's format allowlist/pixel-bomb ceiling/concurrency gate)
  before attempting OCR -- it previously bypassed `imaging.py` entirely. A
  non-image upload (a genuine PDF) is still tolerantly archived with OCR
  skipped, unchanged. **The AV-hook half of M5 was re-scoped, not built:**
  the tender's own text assigns antivirus to PTM (the University's IT dept) at
  the host/VM level, already correctly marked N/A/Contractual in
  [[Compliance Matrix]] -- an application-level scanner would solve a
  problem that isn't the vendor's per the tender itself. New
  `backend/tests/test_digitise_document_safety.py` (3 tests). **Verified:**
  full suite **144/144 pass** (141 prior + 3 new), `pyflakes` clean.
  **M6 (emergency-scan audit trail unverified), M7 (NFC card entropy/1yr
  default), M8 (clinical data in audit_logs.detail) still open** -- next up.
- **2026-09-07** — **P2.5 done** (Claude, direct — design confirmed with the
  user first, a bigger architectural change than P2.1-4). Fixed
  [[Security Audit#M4]]: `ACCESS_TOKEN_EXPIRE_MINUTES` 8h → 15min; new
  `models.RefreshToken` (30-day) backs a `POST /auth/refresh` that mints a
  fresh access token and ROTATES the refresh token, treating reuse of an
  already-rotated token as a compromise signal (revokes every refresh
  token for that user). Web console gets the refresh token as an
  `HttpOnly`/`SameSite=Strict` cookie (`path=/auth`, never JS-reachable);
  the Flutter app (no cookie jar) gets the same value as a plain JSON
  field, stored via `flutter_secure_storage`. New `POST /auth/logout` is
  real server-side revocation (there was none before). A password change
  now revokes every refresh token for the account too, not just the old
  access-token watermark. `main.py`'s CORS `allow_credentials` is `True`
  only with an explicit `CORS_ALLOWED_ORIGINS` allowlist (spec-required —
  forbidden with the demo wildcard), so the cookie degrades to "re-login
  every 15 min" rather than misbehaving in the cross-origin demo/tunnel
  mode. Both clients' interceptors transparently refresh-and-retry once on
  a 401, single-flighted (concurrent 401s share one refresh call rather
  than each racing the backend's single-use rotation). New
  `backend/tests/test_refresh_tokens.py` (9 tests: cookie shape, rotation,
  reuse-detection nukes the whole chain, logout, password-change-revokes-
  everywhere). **Verified:** full suite **141/141 pass**, `check_schema.py`
  PASS through new revision `c4f34fe29451`, `npm run build` + `oxlint`
  clean, `flutter analyze` clean project-wide, AND a live end-to-end smoke
  test against a real running backend (not just TestClient) via a Node
  script exercising the actual HTTP/cookie contract (login → cookie
  shape/flags → /auth/me → refresh → rotated cookie → new token works →
  logout → refresh-after-logout correctly rejected).
- **2026-09-07** — **P2.4 done** (Claude, direct). Fixed
  [[Security Audit#M1]]/[[Security Audit#M2]]. **M1:** per-IP
  `20/minute` limit on `POST /auth/login` (on top of, not instead of, the
  per-account lockout -- catches a spray across many different accounts
  from one IP, which the per-account counter can't); fixed the real DoS
  M1 names -- a lapsed lock previously left `login_failed_count` at its
  old value, so one further wrong guess re-locked the account for another
  full cooldown indefinitely, off one request per window, without ever
  needing the real password. Now resets to 0 the moment a lapsed lock is
  observed. **M2:** per-IP limits on both OTP-reset endpoints
  (`10/minute`) and self-registration's `/start`/`/verify-otp`
  (`10/minute`) + `/complete` (`20/minute`). New indexed
  `models.Patient.normalized_national_id` (unique), auto-synced by a
  `@validates("national_id")` model hook rather than per-call-site
  discipline; `_resolve_patient_by_nric` (used by login + both OTP
  endpoints) rewritten from an O(n) fetch-every-patient loop to a single
  indexed query -- and found + consolidated THREE more copies of that
  same loop (`patients.py::create_patient`'s duplicate check,
  `reception.py`'s check-in-by-IC and admission-by-IC lookups) onto the
  same resolver. Alembic `649f25aeb36f` adds the column + backfills every
  existing row. **Test-infra fix along the way:** the new per-IP limits
  immediately broke the shared-`TestClient` test suite (127 tests'
  cumulative login calls tripped the new limit before any individual
  test's own logic was at fault) -- added an autouse
  `_reset_rate_limiter` fixture to `conftest.py`. New
  `backend/tests/test_login_rate_limiting.py` (5 tests). **Verified:**
  full suite **132/132 pass** (127 prior + 5 new), `check_schema.py`
  PASS, backfill verified against the real seeded demo patients,
  `pyflakes` clean, no import cycle from the new cross-router
  `_resolve_patient_by_nric` reuse.
- **2026-09-07** — **P2.3 done** (Claude, direct). Fixed
  [[Security Audit#H3]]: `seed.py`'s memorable demo passwords
  (`admin123`/etc.) now only apply when `APP_ENV`/`DEMO_MODE=demo` (same
  signal `main.py`'s CORS wildcard opt-in already uses) — any real
  deployment instead gets a fresh `auth.generate_temp_password()` per
  account, `must_change_password=True`, printed to the console exactly
  once. `schemas.MIN_PASSWORD_LENGTH` 8→12 + a new weak-password denylist
  (common passwords + this app's own demo credentials) — deliberately kept
  length+denylist over mandatory character-class complexity, per NIST SP
  800-63B (the existing length-only design already reasoned this; this
  strengthens rather than reverses it). New
  `backend/tests/test_seed_password_policy.py` (4 tests — runs `seed.py`
  as a real subprocess in both modes, inspects stdout + stored hashes).
  README + `docs/deployment.md` updated. **Verified:** full suite
  **127/127 pass** (123 prior + 4 new), both modes manually run
  end-to-end, `pyflakes` clean.
- **2026-09-07** — **P2.2 done** (Claude, direct — design confirmed with
  the user first, since this genuinely reshapes CLARION's cross-hospital
  access model, unlike P2.1's unambiguous bug fix). Fixed
  [[Security Audit#H2]] with an allow-and-log vs. default-deny split:
  `list_patients` (browse-everyone, no emergency urgency) now
  default-scopes to the caller's own facility's known patients
  (`_facility_known_patient_ids` — encounter / authored condition-medication-
  allergy / admission / queue ticket / appointment, any one counts),
  paginated (`skip`/`limit`, max 200), with an explicit audited
  `break_glass_reason` override and **no admin exemption from the
  scoping**. `get_patient_full_record` (single lookup, genuine
  continuity-of-care/emergency value) stays fully open but now logs a
  distinct `view_full_record_cross_facility` action
  (`_patient_known_to_facility`, a cheap per-patient check — NOT the bulk
  form, to avoid materialising a whole facility's patient set on every
  detail view) whenever the caller has no local relationship to the
  patient. Web console (`PatientList.jsx`/`client.js`) updated to match:
  requests up to 200 (keeps the existing client-side-filter UI pattern
  working at this app's actual scale) + a "search all facilities" override
  UI (reason input, audited, shows an "All facilities — audited" badge).
  New `backend/tests/test_patients_facility_scoping.py` (8 tests).
  **Verified:** full backend suite **123/123 pass** (115 prior + 8 new),
  `npm run build` clean, `pyflakes` clean, only caller of `listPatients()`
  in the web app updated.
- **2026-09-07** — **P2.1 done** (Claude, direct). Fixed [[Security Audit#H1]] --
  `routers/emergency.py`'s `issue`/`revoke`/`current-status`/`list_nfc`
  endpoints had no page-access gate at all (any authenticated staff role,
  including pharmacist/receptionist, could act on any patient's emergency
  card) and no facility scoping. All 4 now depend on
  `auth.require_page_access("patients")` (same mechanism the rest of the
  app already uses; a `patient` role's own self-service path is
  unaffected). New `_require_patient_present_for_staff` adds facility
  scoping for staff callers: blocks unless the patient has an active
  `Admission` or an open today's `QueueTicket` at the acting staff's own
  facility -- reused `_patient_present_at` from `patients.py` (imported
  cross-router, an established pattern in this codebase -- see
  `patients.py`'s own imports from `reception.py`/`profile.py`), **no
  admin override**, matching `_guard_cross_facility_amend`'s own documented
  precedent exactly. `POST /emergency/scan` + `POST /emergency/nfc/scan`
  deliberately untouched -- intentionally public/unauthenticated, the
  life-safety break-glass design this app is built around, out of scope
  for H1. New `backend/tests/test_emergency_access_control.py` (9 tests --
  pharmacist/receptionist blocked, facility-presence blocks/allows,
  no-admin-override, patient self-service unaffected, revoke+status also
  scoped). **Verified:** full suite **115/115 pass** (106 prior + 9 new),
  `pyflakes` clean, no import cycle from the cross-router helper import.
- **2026-09-07** — **P0.2 done** (Claude, direct — user approved the delete
  after the permission classifier correctly flagged it as destructive).
  `git rm -r mobile/` (the legacy React Native app — superseded by
  `mobile_flutter/`, its `api/client.js` hardcoded `localhost:8000` per the
  P1.8 note); deleted the stray untracked `backend/comiin.db` (360K, a
  pre-rename leftover, never the live app DB); deleted the stale
  `mobile_flutter/build/` cache (gitignored, held `com.comiin.*` compiled
  classes from before the `MainActivity.kt` package rename). **Naming
  reconciliation:** found the Flutter app's own root widget was still
  literally named `MediBridgeApp`/`_MediBridgeAppState`
  (`mobile_flutter/lib/{app,main}.dart`) — renamed to `ClarionApp`/
  `_ClarionAppState` (only 2 files referenced it). `flutter analyze` on
  both files: clean. Left `bridge/README.md`'s "CLARION / MediBridge"
  dual-naming header and `mobile_flutter/README.md`'s historical
  dated log entries mentioning `medibridge.db` alone — those are
  point-in-time narrative, not current instructions or live code.
- **2026-09-07** — **P1.10 done** (Claude-owned, direct — agy delegation was
  attempted first per the routing policy but blocked: the headless wrapper
  refused to write without either `--yolo` or a pre-existing
  `permissions.allow` grant in `~/.gemini/antigravity-cli/settings.json`,
  neither of which was set, and `--yolo` was withheld deliberately per
  [[agy-delegation-flakiness]] for a security-critical auth module — see
  `healthcare/Integration Engine and LDAP.md`). LDAP/AD as a second, opt-in
  (`LDAP_ENABLED`) auth provider next to local accounts.
  - **`backend/app/ldap_auth.py`** (new): `ldap3`-based service-bind ->
    search -> user-rebind flow. Empty password rejected pre-bind (blocks
    the classic anonymous-bind-as-success LDAP bypass); username passed
    through `escape_filter_chars` before templating into the search filter
    (filter-injection guard); every `ldap3`/network exception caught and
    turned into a plain `None` (a directory outage reads as "wrong
    password" from the outside, same account-enumeration discipline as the
    rest of `auth_router.py`); `resolve_role_for_groups` picks the
    highest-`priority` matching `LdapRoleMapping` row, case-insensitive
    group-DN match, **denies (returns None) rather than defaulting a role**
    when nothing matches.
  - **`models.py`**: new `LdapRoleMapping` table (admin-editable,
    group_dn/role/facility/priority) + `User.auth_source`
    (`server_default='local'`, additive) + `User.ldap_dn` (audit cache,
    never trusted to skip a re-search). Alembic `1b4bf5c769e9` (down_revision
    `b7f1c0d94a2e`).
  - **`auth_router.py`** wiring: `_resolve_login_user` now also returns
    `ldap_eligible` (False only when the identifier resolved to a real
    Patient's NRIC — patients never reach LDAP, JIT-provision or otherwise).
    Case A (no local user, ldap_eligible) -> `_jit_provision_ldap_user`
    (random-placeholder local hash, `auth_source="ldap"`). Case B
    (`auth_source=="ldap"` already) -> `_verify_ldap_existing_user`
    (re-binds fresh every login, re-syncs role/facility/full_name/ldap_dn
    from *current* group membership — a revoked AD group takes effect next
    login). Case C (local account) byte-for-byte unchanged. Failed LDAP
    binds feed the SAME per-account lockout counters as a wrong local
    password.
  - **`admin.py`** CRUD: `GET/POST/PUT/DELETE /admin/ldap-role-mappings`,
    admin-only. Deliberately **not facility-scoped** unlike every other
    endpoint in that router — this is a platform-level identity-provider
    setting, not a per-hospital one (documented inline as the one
    intentional exception to the file's own scoping rule).
  - `.env.example` (every `LDAP_*` var, default off), `requirements.txt`
    (`ldap3==2.9.1`), `docs/deployment.md` (new "LDAP / Active Directory"
    section).
  - **Bug found + fixed (repo-wide, not P1.10-specific):** `alembic/env.py`'s
    `fileConfig(...)` call defaulted to `disable_existing_loggers=True` --
    silently `.disabled = True`'d every `app.*` logger that already existed
    at that point in the process (basically all of them, since
    `_ensure_schema()`'s auto-`upgrade head` on SQLite runs at every app
    import, after most router modules — hence most loggers — are already
    created), permanently, for the rest of the process, with no error.
    Found via `ldap_auth.py`'s own warning logs (unmapped-group denials,
    directory errors) silently never appearing anywhere, including under
    pytest's `caplog`. Fixed with one flag:
    `fileConfig(config.config_file_name, disable_existing_loggers=False)`.
  - **Tests** — new `backend/tests/test_ldap_auth.py` (18 tests, ldap3
    `MOCK_SYNC` in-process directory, no real AD): empty-password
    pre-bind rejection, successful bind+search+rebind, wrong password,
    zero/multiple search results, filter-injection escaping (asserts the
    exact filter string sent), service-bind failure, role-priority
    resolution + case-insensitivity + no-match, and full HTTP E2E through
    `POST /auth/login` for Cases A/B/C, LDAP-disabled-unaffected, a real
    patient's NRIC never reaching LDAP even with no linked account, and
    LDAP-backed lockout. Self-contained TestClient + throwaway SQLite DB
    (no shared fixture exists yet -- that's P1.12). Plus a manual E2E smoke
    of the admin CRUD (create/duplicate-409/invalid-role-422/update/
    non-admin-403/delete). **Verified:** full suite **84/84 pass** (66
    pre-existing + 18 new), `check_schema.py` PASS (upgrade head, autogen
    zero-ops, downgrade/upgrade round-trip), `pyflakes` clean on every
    touched file.
  **Not yet done:** no web/Flutter UI for managing `ldap-role-mappings`
  (API only — an admin can drive it via `/admin/docs` or curl for now).
- **2026-09-07** — **P1.10 voltagent security review actioned** (1 Critical +
  4 High + 4 Medium + 3 Low + test-coverage gaps; findings ranked using this
  file's own severity scheme):
  - **C1 (Critical) — identity keyed on the wrong field.** `email` (from the
    directory's `mail` attribute) and the login string only coincide under
    the default `LDAP_USER_SEARCH_FILTER=(mail={username})`. A realistic AD
    login (`sAMAccountName`/`uid`-based — the actual tender scenario) has a
    DIFFERENT `mail` value, so a second login couldn't find the row the
    first created (re-attempted JIT-provision → crash on the `email`
    unique constraint) and Case B's resync could never re-find the entry
    at all. **Fixed:** new `User.ldap_username` column (Alembic `90f10b24a6db`)
    = the exact raw login string, captured once at JIT time; every
    subsequent lookup/search keys on it, never on `email`.
  - **H1 — unthrottled LDAP DoS.** `/auth/login`'s `@limiter.exempt` is
    justified by its per-account lockout, which doesn't exist for an
    identifier with no `User` row yet — every such guess now did a real,
    slow, unauthenticated directory round trip. **Fixed:** process-wide
    `threading.Semaphore` (`LDAP_MAX_CONCURRENT_BINDS`, default 8) gates
    `authenticate_ldap`; over-limit callers are rejected immediately, no
    queueing.
  - **H2 (timing side-channel, documented not fixed)** — a local-account
    401 is sub-ms; an LDAP-eligible one does ≥1 real network round trip.
    Content-identical, timing-observable. Logged as a residual risk in
    `docs/deployment.md` rather than an engineered constant-time fix.
  - **H3 — facility privilege escalation in the new admin CRUD.** Every
    OTHER endpoint in `admin.py` forces `facility` from `current_user.facility`;
    the new `/admin/ldap-role-mappings` took it verbatim from the client,
    letting any single-facility admin plant a mapping that JIT-provisions
    or resyncs a user at a DIFFERENT facility (incl. as `admin`). **Fixed:**
    `_check_mapping_facility` — `payload.facility` must be `None` or equal
    the acting admin's own facility, on both create and update.
  - **H4 — no TLS certificate validation.** Verified directly against the
    installed `ldap3==2.9.1`: its default `Tls()` is `validate=CERT_NONE` —
    `LDAP_USE_SSL`/`LDAP_START_TLS` alone bought no certificate-chain
    validation at all (any self-signed cert, any host, would MITM every
    password). **Fixed:** explicit `Tls(validate=ssl.CERT_REQUIRED, ...)`
    whenever either flag is on; new `LDAP_CA_CERT_FILE` pins a private CA
    (unset = OS default trust store). Noted residual: ldap3 doesn't verify
    hostname/SAN even so — pin a dedicated CA, don't rely on hostname match.
  - **M1 — `role="patient"` was a valid LdapRoleMapping value**, contradicting
    "patients never authenticate via LDAP" (a JIT-provisioned "patient"
    would have `patient_id=None`). **Fixed:** new `schemas.LDAP_ASSIGNABLE_ROLES`
    (staff roles + admin, excludes patient/emergency_responder) replaces
    the general `VALID_ROLES` check on this one schema.
  - **M2 — `group_dn` uniqueness TOCTOU/collation race** could 500 instead
    of 409 (SQLite case-sensitive vs. MariaDB `ci` collation disagreeing
    with the app-level pre-check). **Fixed:** `try/except IntegrityError`
    around both create/update commits, falling back to the same 409.
  - **M3 — plaintext LDAP was a silent default.** Following only the
    documented minimal steps shipped a fully working feature that sent
    every password in cleartext. **Fixed:** `authenticate_ldap` now refuses
    to bind at all when neither TLS flag is set, unless
    `LDAP_ALLOW_INSECURE_BIND=true` explicitly overrides (same
    opt-in-to-danger pattern as `CLARION_ALLOW_CLOUD_AI`).
  - **M4 — JIT-provision race** (two concurrent first-logins for one new
    identity) could 500 on the second commit. **Fixed:** `try/except
    IntegrityError` re-queries by `ldap_username` and returns the winner's
    row instead of failing the login.
  - **L1** `search()` now passes `size_limit=5` (defense-in-depth — the
    `>1 = deny` check already existed). **L2** `authenticate_ldap` fails
    loud (CRITICAL log) at first use if `LDAP_ENABLED=true` but
    `LDAP_SERVER_URI`/`LDAP_BASE_DN`/`LDAP_BIND_DN` aren't all set, instead
    of a confusing per-request failure further down. **L3** `_make_server`
    construction moved inside the try block and both except clauses
    broadened `LDAPException` → `Exception`, so a non-LDAPException failure
    (e.g. a malformed `LDAP_SERVER_URI`) can no longer escape as a raw 500.
  - **Test-coverage gaps closed:** +5 tests in `test_ldap_auth.py` (the two
    C1 regressions under a `sAMAccountName` filter, a malformed-placeholder
    filter, `unbind()` called on a mid-flow exception, the M4 JIT race) and
    a new `test_admin_ldap_role_mappings.py` (10 tests — RBAC, the H3
    facility restriction on create *and* update, M1's two rejected roles,
    an allowed `admin`-role mapping, M2's plain and case-variant 409, full
    CRUD round-trip). Reviewer-flagged as previously **zero** coverage on
    the admin endpoints.
  **Verified (Claude):** full suite **106/106 pass** (91 prior + 15 new),
  `check_schema.py` PASS (upgrade head, autogen zero-ops, downgrade/upgrade
  round-trip through the new `90f10b24a6db` revision), `pyflakes` clean on
  every touched file, `_make_tls` confirmed `validate=CERT_REQUIRED` against
  the installed `ldap3==2.9.1` directly (not just read from source).
- **2026-09-07** — **P1.12 done** (Claude, direct). New `backend/tests/conftest.py`:
  the shared TestClient+throwaway-SQLite-DB scaffold P1.10's `test_ldap_auth.py`
  had rolled ad hoc, consolidated so future router-level test files don't
  repeat it. Fixtures: `test_client` (session-scoped), `db_session`,
  `make_user` (factory, auto-cleanup, stashes a `plaintext_password` for
  login tests), `auth_headers` (logs in for real through `POST /auth/login`
  rather than hand-minting a JWT). New `test_auth_rbac_immutability.py` (7
  tests) — the roadmap's stated priority order: RBAC (`require_roles`),
  router-level page-access gating (`require_page_access`), and the
  cross-hospital clinical-record immutability guard
  (`_guard_cross_facility_amend` in `patients.py`) — cross-facility PATCH
  denied + audit-logged, same-facility-but-patient-absent still denied
  (both rules independently necessary), same-facility-and-present allowed.
  **Verified:** all 7 pass alongside the full 106-test suite.
  **Not yet done:** existing test files (`test_storage.py`/`test_imaging.py`/
  `test_derived.py`/`test_ldap_auth.py`) still carry their own
  pre-conftest setup where applicable — a mechanical dedup pass, not
  correctness-bearing, left for whenever one of those files is next touched.
- **2026-09-07** — **P1.13 done** (Claude, direct — small + judgement-light,
  no delegation per the routing policy). `mobile_flutter/android/app/build.gradle.kts`
  now reads `android/key.properties` (git-ignored, template at
  `android/key.properties.example`) and defines a real `signingConfigs.create("release")`
  from it; falls back to the debug key with a loud Gradle `logger.warn` when the
  file is absent (so local/demo release builds keep working, but can't be
  mistaken for a distributable one). Root `.gitignore` excludes
  `key.properties`/`*.jks`/`*.keystore` under `mobile_flutter/android/`.
  `mobile_flutter/README.md` gets a "Release signing" section with the
  `keytool -genkeypair` command and the credential-custody note (keep the
  `.jks` outside the repo). Deliberately did **not** generate a real
  production keystore — that's the team's own long-lived credential to
  create and hold, not something to fabricate here. **Verified** (Claude,
  this environment): `./gradlew.bat :app:signingReport` — no `key.properties`
  → `Variant: release / Config: debug` (fallback, as designed); a throwaway
  test keystore + `key.properties` → `Variant: release / Config: release`
  pointing at the test `.jks`; test artifacts deleted after.
- **2026-08-30** — **P1.9 DONE** (Claude; agy CSP sweep + voltagent infra
  security review). Edge reverse proxy: **`proxy/Caddyfile`** (Caddy 2.8-alpine)
  is now the single TLS-terminating entry point and the one place the whole
  stack's security headers are defined.
  - **TLS:** `{$CLARION_TLS_DIRECTIVE:tls internal}` — demo uses Caddy's local
    CA (`caddy trust` to silence the warning); production sets
    `CLARION_TLS_DIRECTIVE=tls /etc/caddy/certs/clarion.crt …key` with the
    CAMPUS-CA pair mounted from `proxy/certs/` (git-ignored). Global
    `admin off`, `persist_config off`; explicit `tls` stops any ACME reachout.
  - **Headers:** HSTS (`max-age=31536000; includeSubDomains; preload`), a
    strict **CSP** (`default-src 'self'`; `script-src 'self'` — the Vite build
    has no inline/eval; `style-src 'self' 'unsafe-inline'` kept as a margin;
    `img-src 'self' data: blob:`; `connect-src 'self' {$CLARION_CSP_CONNECT_EXTRA}`
    for the NFC bridge; **no** `upgrade-insecure-requests` — it would break the
    plain-HTTP bridge), `X-Frame-Options: DENY`, nosniff, Referrer-Policy,
    COOP, CORP, a locked-down Permissions-Policy (`camera=(self)` for the
    barcode scanner), `-Server`. Caddy's `header` op *replaces* the app's own
    header values on proxied responses — no duplication.
  - **Routing:** `handle_path /api/* → backend:8000` (strips `/api`, sets
    `X-Forwarded-Proto https`), everything else → `web:8080`. `request_body
    max_size 20MB`. `web/nginx.conf` keeps its own `/api` proxy as a no-op
    behind Caddy / for standalone use.
  - **compose:** NEW `proxy` service is the **only** one publishing host ports
    (80/443, `HTTP_PORT`/`HTTPS_PORT`). `web` + `backend` `ports:` → `expose:`
    only. Network gets `subnet 172.28.0.0/16` + `ip_range 172.28.10.0/24`;
    proxy pinned to **`172.28.0.2`** so `FORWARDED_ALLOW_IPS` (P1.8) can trust
    exactly that hop. `caddy_data`/`caddy_config` volumes. `.env.docker.example`
    gains `CLARION_SITE_ADDRESS` / `CLARION_TLS_DIRECTIVE` /
    `CLARION_CSP_CONNECT_EXTRA` / `HTTP_PORT` / `HTTPS_PORT`; drops
    `BACKEND_HOST_PORT`/`WEB_HOST_PORT`.
  - **Pre-existing bug fixed to get a bootable stack:** `uvicorn-worker`
    `0.3.0 → 0.4.0` — 0.3.0 calls uvicorn's removed `Config.setup_event_loop`
    and crash-loops every gunicorn worker on uvicorn ≥ 0.36 (the compose stack
    had never actually been booted — AGENTS.md P1.11 "not yet run").
  - **Verified (Claude, live stack, Caddy internal CA):** `caddy validate` +
    `caddy fmt`; `docker compose config` OK; full stack up (proxy/web/backend/
    redis/minio healthy); **HTTP→HTTPS 308**; every security header present on
    `/` and `/api/` (single `X-Frame-Options`); `/config.js` `no-store` with
    `window.__CLARION_API_BASE__="/api"`; `/api/` → backend JSON; SPA loads.
    **XFF spoof test:** `X-Forwarded-For: 9.9.9.9` through the proxy → backend
    logs the real hop (injected value dropped); spoofed XFF on a direct hit to
    `backend:8000` from a non-`.0.2` peer → ignored, real peer used. So the
    per-IP rate-limit key can't be forged.
  **voltagent infra-security review actioned (verdict: design sound; edge
  hardening owed):**
  - **M1 — HSTS `preload` + long fixed max-age:** dropped `preload` (an
    irreversible the University domain-owner call, not an app default). Header is now
    `{$CLARION_HSTS:max-age=300}` — demo ships a 5-min pin, prod ramps
    deliberately (`.env.docker.example` documents `max-age=31536000;
    includeSubDomains`, `preload` only with FQDN sign-off).
  - **M2 — no edge timeouts / header cap:** added a `servers { }` global —
    `timeouts` (read_body 30s / read_header 5s / write 120s / idle 2m),
    `max_header_size 16KB`, `protocols h1 h2` (kills the unreachable HTTP/3
    Alt-Svc — also L4), `trusted_proxies static` (explicit "trust no inbound
    XFF"), `strict_sni_host on`.
  - **M3 — TLS floor unpinnable with the one-liner:** the site's
    `{$CLARION_TLS_DIRECTIVE:tls internal}` now takes a `{ protocols tls1.2
    tls1.3 }` block that attaches whichever `tls` form the env produced.
    (Typo'd directive → Caddyfile parse fails → container won't start = fail
    closed; unset on a real domain → `tls internal`, no ACME reachout.
    Reviewer confirmed both.)
  - **M4 — healthcheck broke in the FQDN config:** replaced the
    `https://127.0.0.1/config.js` probe with a plain-HTTP `/healthz` route
    (a dedicated `:80` block, no TLS/cert/DNS dependency); compose healthcheck
    hits `http://127.0.0.1/healthz`. Verified `ok 200` and everything else on
    `:80` still 301s to HTTPS.
  - **M5 — flat network:** split into **two** compose networks — `edge`
    (proxy↔web/backend) and `internal` (backend↔mariadb/minio/redis/orthanc);
    `backend` bridges both. Verified: `web` can't resolve/reach `minio`;
    `backend`↔`redis` fine; the `web`→`backend` fallback still works.
    **Residual (documented):** `backend` must sit on `internal` to reach the
    data tier, so `internal` members can still hit `backend:8000` — full
    per-service isolation / the 3rd `observability` net is P1.11-remainder /
    P5.3. Also aligned `web/nginx.conf` `X-Frame-Options` → `DENY` and
    commented its `/api` block as the no-edge fallback.
  - **L1** README's `auto_https disable_redirects` prose was fiction — rewritten.
    **L2** CSP: kept `style-src 'unsafe-inline'` (React `style={{}}` genuinely
    needs it — reviewer confirmed; my earlier comment was wrong) but added
    `style-src-elem 'self'` + `style-src-attr 'unsafe-inline'` so injected
    `<style>`/`<link>` is still blocked; confirmed **no** `wasm-unsafe-eval`
    needed (`@zxing` is pure JS). **L5** edge body cap 20MB→16MB (just above
    the app's 15MB). **L6** `encode` scoped to non-`/api` only. **L7** removed
    a stray `proxy/Caddyfile;C/` dir, added an edge JSON access log.
  - **Bug found + fixed to get a stable boot:** `_ensure_schema()` runs at
    module import, so gunicorn's 4 workers raced `alembic upgrade` on one
    SQLite file and corrupted it ("tables but no alembic_version" → refuse to
    serve, crash-loop). Added a POSIX file lock (`_schema_lock`, SQLite-only;
    Windows/ MariaDB no-op) so one worker migrates and the rest wait then
    see head. Verified: repeated fresh `up` → 0 races, all workers healthy.
  Re-verified after all fixes: `caddy validate`/`fmt`, `docker compose config`,
  full stack healthy, `/healthz` 200, HTTP→HTTPS, HSTS `max-age=300`, single
  `X-Frame-Options`, `/api/` + `/api/docs` 200, SPA loads, network isolation
  as above, `pytest tests/` 66 pass, `pyflakes` clean.
- **2026-08-30** — **P1.8 DONE** (Claude; agy repo-wide sweep + voltagent
  security review). Most of P1.8 was already standing from P1.3/P1.6/P1.11:
  backend CORS is env-driven (`main.py` — `CORS_ALLOWED_ORIGINS` csv allowlist;
  else `["*"]` only when `APP_ENV`/`DEMO_MODE` is unset or `demo`; else fail-safe
  `[]`; `allow_credentials=False`), `web/nginx.conf` has the `/api`→`backend:8000`
  same-origin proxy, `web/entrypoint.sh` writes `/config.js` from `$API_BASE`,
  and Flutter reads its base from `--dart-define` + an in-app Settings override.
  **The gap was the web SPA never consuming `/config.js`.** Now:
  - `web/index.html` loads `<script src="/config.js">` (classic, in `<head>`
    ahead of the deferred module bundle).
  - `web/src/api/client.js` — `API_BASE = resolveApiBase()`:
    `window.__CLARION_API_BASE__` → `import.meta.env.VITE_API_BASE` →
    `http://localhost:8000`, trailing slash trimmed (so `/api` and `/api/`
    are equal). Feeds the axios `baseURL` and the handful of bare
    `axios.get(\`${API_BASE}/...\`)` calls (login, OTP reset, public display).
  - `web/public/config.js` — NEW committed stub (`window.__CLARION_API_BASE__ = ""`)
    so local dev / a static `dist/` preview fall through to the fallback chain;
    the container overwrites this copy.
  - `web/vite.config.js` — dev server now proxies `/api` →
    `VITE_DEV_API_PROXY` (default `http://localhost:8000`), so
    `VITE_API_BASE=/api` exercises the prod same-origin path in `npm run dev`.
  - `web/.env.example` — NEW (`VITE_API_BASE`, `VITE_DEV_API_PROXY`,
    `VITE_NFC_BRIDGE_URL`). `backend/.env.example` — `DEMO_MODE` note.
  - **`web/entrypoint.sh` hardening:** `$API_BASE` is interpolated raw into a
    JS string literal, so it's now validated — empty, `/`-rooted, or
    `http(s)://…` built only from `[A-Za-z0-9._~:/-]`; anything else is dropped
    with a warning (quote/newline/`<` breakout → the SPA falls back to its safe
    localhost default instead of running injected script). Verified with 7
    inputs incl. `"; fetch(...localStorage.mb_token)` and an embedded newline.
  - `docs/deployment.md` — "How the web console finds the API" rewritten (the
    "not yet consumed by the SPA" caveat is gone), roadmap + troubleshooting
    rows updated.
  **agy sweep (pro tier, read-only)** confirmed no other must-fix hardcoded
  hosts: `database.py`/`email_service.py`/`docker-compose.yml` MinIO+ports all
  env-driven w/ fallbacks; bridge localhost binds + Docker healthchecks +
  RxNav/DailyMed (P4.4) are legitimately fixed. One real find — **`mobile/api/client.js`
  hardcodes `http://localhost:8000`** with no env read — but that's the legacy
  RN app already slated for deletion in **P0.2**; left as-is.
  **Not done (deliberate):** agy pushed to delete `/config.js` + the CORS
  allowlist entirely and force pure same-origin — rejected; the direct /
  cross-origin mode is a supported deployment (the rotating trycloudflare
  tunnel demo) and the roadmap explicitly asks for runtime `config.js`.
  **voltagent security review actioned (6 findings):**
  - **F1 (Med) — `entrypoint.sh` `$API_BASE` → JS-literal injection:** value
    now validated (empty / `/`-rooted / `http(s)://` from `[A-Za-z0-9._~:/-]`)
    before interpolation, else dropped with a warning. (Already done pre-review;
    reviewer confirmed client-side-only, operator-controlled.)
  - **F2 (Med) — `X-Forwarded-For` spoof defeats every per-IP rate limit:**
    `backend/Dockerfile` had `--forwarded-allow-ips "*"` (trust `XFF` from any
    peer → slowapi keys on a forged IP → the `10/minute` public
    emergency-scan / OTP back-stops bypassable, worse with the backend port
    published). Removed the flag; gunicorn now reads `FORWARDED_ALLOW_IPS`
    (default `127.0.0.1`), wired through `docker-compose.yml` +
    `.env.docker.example` + `backend/.env.example`, with a P1.9 note to set it
    to the edge-proxy subnet and unpublish the backend port.
  - **F3 (Low, Security Audit M3) — CORS fail-OPEN when nothing is set:**
    `main.py` now fails CLOSED. Wildcard is an **explicit** `APP_ENV=demo` /
    `DEMO_MODE∈{demo,1,true}` opt-in; unset or any non-demo `APP_ENV` with no
    `CORS_ALLOWED_ORIGINS` → `allow_origins=[]` + a startup WARNING.
    `.env.example` files ship `APP_ENV=demo` so local dev still works on copy.
    Verified: unset→`[]`, demo→`['*']` (ACAO `*` on preflight), production→`[]`
    (ACAO absent), explicit list→parsed; 66 tests still green.
  - **F4 (Low) — no TLS at this layer** → P1.9 (edge proxy must also cover the
    published backend port). Noted, not actioned here.
  - **F5 (info) — `VITE_`-prefix bleed:** documented in `web/.env.example`
    (every `VITE_`-var referenced in `src/**` is inlined verbatim into the
    public bundle). Reviewer confirmed `vite.config.js` `server.proxy` /
    `VITE_DEV_API_PROXY` never reach a prod build.
  - **F6 (Low) — silent `localhost:8000` fallback in a prod build:**
    `client.js` now `console.error`s when it falls through in an
    `import.meta.env.PROD` build.
  Reviewer confirmed **no service worker** anywhere in `web/` and that
  `window.__CLARION_API_BASE__` is not browser-attacker-influenceable
  (same-origin static JS, loads before the app, `typeof === "string"` guard).
  **Verified (Claude):** `npm run build` clean; `dist/index.html` loads
  `/config.js` before the module; bundle contains the `__CLARION_API_BASE__`
  read; `vite preview` serves `/config.js` 200; `entrypoint.sh` generates the
  exact literal `client.js` parses for `/api` / a full tunnel URL / empty;
  7 injection inputs neutralised; CORS matrix + preflight E2E on demo &
  production; `pytest tests/` 66 pass.
- **2026-08-30** — **P1.7 DONE** (Claude; agy write-delegation was blocked by a
  missing grant so it was done directly — the module is small + judgement-light).
  `backend/app/imaging.py` — pure Pillow, bytes→bytes: `normalise_image`
  (EXIF/GPS/ICC/XMP strip, `exif_transpose` auto-orient, transparency→white,
  ≤2500px long edge, progressive JPEG q82), `make_thumbnail` (300px box),
  `is_supported_image` (magic sniff). Hardening: `MAX_INPUT_PIXELS` 40MP +
  explicit `w*h` check, `Image.MAX_IMAGE_PIXELS` pin, Pillow-format allowlist
  (`_ALLOWED_PIL_FORMATS` — rejects ICO/EPS/etc even though Pillow could decode
  them), `n_frames > 2000` guard, every Pillow exception re-raised as
  `ImageProcessingError`. `backend/app/derived.py` — `clarion-derived` bucket,
  deterministic keys `{variant}/{source_bucket}/{source_key}.jpg`,
  `get_or_make_thumbnail` (regenerate-on-miss so the bucket can carry a 30-day
  ILM expiry), `prime_thumbnail`, `purge_derived`. **Wiring:** medicine photos
  normalised **in place** on upload (`admin.save_medicine_image` — key now ends
  `.jpg`, old derived purged, thumb primed); clinical-document originals
  **never touched** (WORM) — only a derived preview, primed for image mimes
  only (`ai_router.digitise_document`). New endpoints
  `GET /pharmacy/inventory/{id}/image/thumbnail` +
  `GET /patients/{id}/documents/{docId}/thumbnail` (same auth/scope as the
  full-file endpoints, `nosniff`, `Cache-Control: private, max-age=300`). API:
  `thumbnail_url` on medicine items, `thumbnail_available` on document detail.
  **No schema change.** `docs/deployment.md` documents the `clarion-derived`
  ILM + backup-exclude as a deploy step. **Verified (Claude, clean state):**
  `tests/test_imaging.py` (28) + `tests/test_derived.py` (8) + P1.6 suite = **61
  pass**; `check_schema` PASS (unchanged); full HTTP E2E on SQLite **and**
  MariaDB+MinIO — medicine photo 3000×100 EXIF-tagged → stored 2500×83, EXIF
  stripped, 5967B→1940B; medicine + document thumbnails 200; non-image doc
  thumbnail → 404; P1.6 paths unregressed.
  **voltagent security + architecture reviews actioned (1 bug + ~15 fixes):**
  - **BUG (arch #1):** medicine thumbnail went stale on a same-name re-upload
    (`old_key == key` → no purge, cache hit served the old preview). **Fixed:**
    derived key now folds the source sha256 — `{variant}/{bucket}/{key}.{sha8}.jpg`
    — so new bytes ⇒ new key; `purge_derived` deleted (ILM expires the orphan).
  - **H1:** `MAX_INPUT_PIXELS` 40MP→**24MP** + a `threading.Semaphore(4)`
    (`_decode_gate`) around every decode so a burst can't OOM the box / starve
    the threadpool. `Image.MAX_IMAGE_PIXELS` pinned to `//2` (Pillow's own bomb
    check only fires at 2×). **H2:** `prime_thumbnail` in `digitise_document`
    (an `async def`) now `await run_in_threadpool(...)` — a Pillow decode no
    longer blocks the event loop.
  - **M2:** `Image.open(formats=["JPEG","PNG","GIF","WEBP","BMP"])` — **TIFF
    dropped** (Pillow's CVE-prone decoder never runs on attacker bytes); ICO/etc
    rejected at parse. `is_supported_image` / `SUPPORTED_INPUT_MIMES` / the doc
    sniffer updated to match. **M1/#9:** `_finalise` + `get_or_make_thumbnail`
    catch the full `_DECODE_ERRORS` tuple — no Pillow exception escapes as a 500.
    **M3:** definitive-negative results (PDF/undecodable) cached as a zero-byte
    `.none` marker so a loop on `/thumbnail` can't force repeated full-original
    reads.
  - **L2:** metadata strip is now `img.info.clear()` (total, not a
    hand-maintained pop-list). **L3:** thumbnail endpoints 503 (not 404) on a
    storage outage — `ObjectStoreError` propagates from `get_or_make_thumbnail`.
    **L5:** the 3 copies of magic-byte sniffing collapsed to
    `imaging.sniff_image_mime` (the others delegate). **L6:** a medicine photo
    that fails to normalise is **422-rejected**, never stored with EXIF intact.
    **L8:** thumbnail build uses `get_checked` (sha256). **L9:**
    `Image.Resampling.LANCZOS`. **L10:** logs on a derived-write failure.
    **L12:** `size` restricted to a named-variant set.
  Re-verified: **66 tests** (imaging 22 + derived 11 + P1.6), `check_schema`
  PASS, full E2E on SQLite + MariaDB + MinIO. Bigger items (PDF preview, HEIC,
  web-preview variant, async job queue) logged as **P1.7b**.
- **2026-08-30** — **P1.6 DONE** (Claude-owned staged passes, as the previous
  entry's lesson demanded — no `--yolo`, no cross-cutting delegation). New
  `backend/app/storage.py`: an `ObjectStore` ABC + `LocalObjectStore` (default,
  `{root}/{bucket}/{key}` tree, atomic writes, traversal-proof key validation) +
  `MinioObjectStore` (S3 API, lazy `minio` import, bucket auto-create, presign,
  object-lock retention) + env-driven factory (`CLARION_STORAGE_BACKEND`
  local|minio). 7 buckets per [[On-Prem Architecture]]. `sanitize_filename` +
  `validate_key` + `apply_object_meta` helpers. **Stage 2:** the 5 `*_path`
  columns → `*_object_key` + `*_sha256` + `*_bytes` + `*_mime` on
  `User`/`Encounter`/`ClinicalRecordAnnotation`/`ClinicalDocument`/
  `MedicineInventoryItem`. Two Alembic revisions — `84f653e6c999` (ADD new
  cols) then `b7f1c0d94a2e` (DROP old) — split so the data migrator can run in
  between. **Stage 3:** rewrote every read/write site — `profile.py` (signature
  up/serve/delete + snapshot copy), `ai_router.py` (document original →
  `clarion-documents`), `patients.py` (`StreamingResponse` doc serve + nosniff +
  sanitized Content-Disposition; annotation snapshot + serve), `admin.py`
  (medicine photo → `clarion-medicine`, stored `image_mime` = sniffed type),
  `pharmacy.py` (serve from stored mime, not path-guess), `consultation.py`
  (encounter snapshot), `auth_router.py`/`schemas.py` (`has_signature`/
  `has_image` off the key col), `seed.py`. New
  `backend/db/migrate_uploads_to_objectstore.py` — reflection + Core (never the
  ORM, whose cols don't match the pre-migration schema), idempotent, 3-step
  flow (`upgrade 84f653e6c999` → migrate → `upgrade head`). API response shape
  unchanged → **no frontend changes needed** (agy sweep confirming). Stored-XSS
  guard preserved (html doc → `application/octet-stream`). `minio==7.2.15` +
  `argon2-cffi` + `pytest` pinned in requirements. `.gitignore` +`object_store/`,
  `.env.example` documents the storage vars. **Verified (Claude, clean state):**
  `tests/test_storage.py` 30/30 (Local end-to-end + traversal guards + factory +
  MinioObjectStore against a fake client); `db/check_schema.py` PASS on fresh
  SQLite **and** real MariaDB 11.4 (upgrade head, autogen zero-ops, full
  downgrade→base→upgrade); real-MinIO smoke (`minio/minio` container — bucket
  auto-create, put/get/stream/exists/delete/presign/ObjectNotFound); full
  HTTP end-to-end on SQLite **and** MariaDB (signature round-trip+nosniff,
  document upload→stream-back, html→octet-stream, annotation+staff signature,
  medicine photo round-trip, delete); the uploads→objectstore migrator against a
  hand-built pre-P1.6 DB (real files moved, cols backfilled, idempotent re-run,
  clean post-drop skip); 5-account login + full patient record + handover brief
  regression; **full app HTTP E2E against MariaDB + real MinIO simultaneously**
  (added after the review — closes the "local backend only" gap).
  **voltagent security-audit actioned (9 findings + migrator notes):**
  - **F1 (HIGH, WORM claimed-not-enforced):** corrected the misleading
    "WORM-locked" comments; `MinioObjectStore._ensure_buckets` now creates the
    4 WORM buckets (`documents`/`signatures`/`dicom`/`reports-archive`) with
    `object_lock=True` + enables versioning on all 7, and `put` stamps a
    per-object **COMPLIANCE** 7-yr retention when the bucket lock is on
    (verified on real MinIO: `get_object_retention` → COMPLIANCE 2033).
    `docs/deployment.md` now carries the `mc mb --with-lock` / `mc retention` /
    least-priv-credential / SSE provisioning steps as a **hard go-live gate**.
  - **F2 (MED, DoS — cap checked after full `.read()`):** new
    `app/routers/_uploads.py::enforce_upload_size` rejects on
    `UploadFile.size` before the read, wired into all 3 upload endpoints.
  - **F3 (MED, MinIO conn leak if `open_stream` created but not consumed):**
    `patients.get_document_file` now `stream.close()`s on any error before the
    `StreamingResponse` is returned + a 503 branch for `ObjectStoreError`.
  - **F4 (LOW, document mime from client header):** `digitise_document` now
    derives the stored mime from magic bytes (`sniff_document_mime`), never the
    Content-Type header.
  - **F5 (LOW, sha256 never verified on read):** new `ObjectStore.get_checked`
    (+ `ObjectIntegrityError`, logged) used by all signature + medicine-photo
    serves and `copy_signature_snapshot`.
  - **F6 (LOW, only `OSError` caught — S3Error isn't one):** `MinioObjectStore`
    wraps every `S3Error` in `ObjectStoreError` (not-found → `ObjectNotFound`);
    every caller catch updated; serve paths 503 on a backend error.
  - **F7/F8/F9 (INFO):** documented (least-priv MinIO cred / `ensure_buckets`
    out-of-band / SSE in `docs/deployment.md`; presign stays unused; the
    annotation-signature cross-facility scoping is unchanged from pre-refactor,
    flagged not fixed).
  - **Migrator:** per-table transactions (resumable mid-run) + `--uploads-root`
    so a relative legacy path resolves against the uploads dir not the CWD.
  Re-verified after the fixes: `tests/test_storage.py` **32/32**, `check_schema`
  PASS both engines, integrity-503 + oversize-413 guards, full E2E on
  SQLite/MariaDB/MinIO.
  **Follow-ups:** `docker-compose.yml` still needs the `minio` service env wired
  to the backend; delete `backend/uploads/` after any real deployment runs the
  migrator; P1.7 image-normalisation is the natural next step on this.
- **2026-08-30** — **P1.6 ATTEMPTED, reverted, still pending.** Delegated the full
  ObjectStore + MinIO build to agy (`--tier pro --yolo`). The `antigravity-delegate`
  subagent lost track of the job (reported "still running in background" but
  `agy-job list` showed nothing) and agy kept running **detached** — it got only
  as far as the `models.py` column definitions (5 models: `*_object_key` +
  `_sha256`/`_bytes`/`_mime`), no `storage.py`, no migration, no site rewrites, no
  compose/requirements. When Claude started reverting the half-state, agy (still
  alive, PID 12780) **raced the edits** — re-applied a buggier second pass
  (`signature_image_object_key` + mismatched `image_*` siblings), wrote a
  syntax-broken migration `4b633bfe25a2`, and converted `models.py` to UTF-8-BOM +
  CRLF. Claude killed the process and reverted. **The subagent was still alive**
  and auto-launched a *second* agy retry (`TaskStop` finally stopped it) — that
  one created `app/storage.py` + a migration with a non-hex revision id
  `b2c3d4e5f6g7` and **stamped the local `clarion.db` to that bogus revision**.
  Final cleanup: reverted all 5 `models.py` regions to the P1.5 columns
  (`signature_image_path` / `file_path` / `image_path`), deleted `storage.py` +
  both stray migrations, stripped BOM, restored LF, rebuilt `clarion.db` fresh.
  **Verified back to clean P1.5 state:** `check_schema` PASS (all 3), signature
  upload/download round-trips on SQLite **and** MariaDB, MariaDB 3-migration boot
  200, autogen zero-ops, zero agy processes, no leftover files.
  **Lesson: no more `--yolo` for cross-cutting refactors, and `TaskStop` the
  subagent (not just the OS process) before cleaning up.** Do P1.6 in Claude-owned
  stages: `storage.py` + tests first, then models + migration, then the
  site-by-site rewrite — each verified before the next.
- **2026-08-30** — **P1.5 done** (Claude). Retired the startup schema hacks —
  `_migrate_lightweight()` (~400 lines) + `_backup_sqlite_file_before_migration()`
  + `create_all()` all deleted from `main.py` (Security Audit **M9** closed: no
  more uncontrolled DDL as the app user at every boot). Replaced with
  `_ensure_schema()`: SQLite auto-runs `alembic upgrade head`; MariaDB only
  **verifies** it's at head and raises a clear RuntimeError otherwise (runtime
  account is DML-only). A *pre-Alembic* `clarion.db` (tables, no `alembic_version`)
  is **refused, not blind-stamped** — those `create_all` DBs carry real drift
  (missing FK `ondelete=CASCADE` on 6 patient-child tables, missing UNIQUEs on
  `patients.national_id` / `emergency_tokens.*` / `reception_stations.token` /
  `waiting_room_displays.token`); fix is `rm clarion.db && python seed.py`.
  `seed.py` now runs `alembic upgrade head` instead of `create_all`. **Fixed the
  P1.2b-discovered baseline bug:** `5e6a60dfe274.downgrade()` now takes a
  `SET FOREIGN_KEY_CHECKS=0` + blunt `DROP TABLE` path on MySQL (the autogenerated
  per-index drops hit error 1553); SQLite path unchanged. New
  `backend/db/check_schema.py` — CI gate asserting (1) `upgrade head` from empty,
  (2) autogenerate-against-head is empty, (3) `upgrade→downgrade base→upgrade`
  round-trips; **PASS on both SQLite and MariaDB 11.4**. **Verified** (Claude):
  fresh SQLite app boot auto-migrates; pre-Alembic DB correctly refused; MariaDB
  refuses before `upgrade head`, boots after; full `downgrade base` now clean on
  MariaDB; `seed.py` rebuild + login/`/patients` green; autogen zero-ops.
  Rebuilt the local dev `clarion.db` fresh from Alembic + seed.
- **2026-08-30** — **P1.4 done** (agy Gemini 3 Pro, Claude-fixed + verified). New
  `backend/db/migrate_sqlite_to_mariadb.py` + `backend/db/README.md`: one-shot
  SQLite→MariaDB copier. Reflects the source (not `models.py` — the demo DB carries
  `_migrate_lightweight` extras), asserts target is at Alembic head `a1b2c3d4e5f6`
  (won't run migrations itself), then a **pre-flight scan** (FK orphans ·
  over-length strings vs P1.2 `String(n)` · `utf8mb4_unicode_ci` case/accent
  unique-collisions · duplicate active `room_claims` · invalid JSON), FK-topological
  copy (`Base.metadata.sorted_tables`) excluding `Computed` columns, datetime/bool/
  JSON/empty-string coercion, per-table batched insert, and a reconciliation report
  (row counts + per-row SHA1 checksum sum + generated-key correctness). CLI:
  `--dry-run`, `--truncate-target`, `--prune-orphans`, `--force`, `--report`.
  **Claude fixed agy's output:** (1) agy's `--force` also did `SET
  FOREIGN_KEY_CHECKS=0` during copy → would import referential-integrity-violating
  rows; replaced with `--prune-orphans` (skip + log orphan rows, keep the target
  clean, reconcile counts) and `--force` no longer touches FK enforcement; (2)
  `UnicodeEncodeError` writing the report on Windows (`open(...)` → cp1252) →
  `encoding="utf-8"` + ASCII text; (3) `--report` default double-prefixed
  `backend/`; (4) non-empty-target guard now skipped under `--dry-run`;
  `.gitignore` the report files. **Verified** (Claude, real MariaDB 11.4): dry-run
  correctly BLOCKs on the demo DB's **2 real FK orphans** (`room_claims` +
  `staff_clock_events` rows for a hard-deleted user `3a4e7165-…`); `--prune-orphans`
  run copies all 30 tables, prunes exactly those 2, **every row-count + checksum
  MATCH**, `room_claims` generated keys PASS, OVERALL PASS; app boots on the
  migrated data as `clarion_app` — login + `/patients` + full-record + audit-log
  all 200. The 3 un-triggered scan classes checked in isolation (queries sound).
  *Note: the demo `clarion.db` can't hold a duplicate active `room_claims` — the
  `_migrate_lightweight` generated-key unique index already blocks it at source.*
- **2026-08-30** — **P1.2b done** (Claude). MariaDB timestamp-precision fix from
  the DBA review (B2). New `models.TZDateTime` =
  `DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")`, applied
  to all 52 timestamp columns (identical render on SQLite → baseline unaffected).
  `patients.py` audit-log read gets a `.order_by(..., AuditLog.id.desc())`
  tiebreak. New **mysql-only** Alembic revision `a1b2c3d4e5f6` (down_revision
  `9f2c8a1b7e4d`) — data-driven `ALTER TABLE … MODIFY … DATETIME(6)` walking
  `Base.metadata`, no-op on SQLite. **Verified:** `upgrade head` clean on fresh
  SQLite + fresh MariaDB 11.4; all MariaDB datetime cols now `datetime(6)` (0 bare
  `datetime` left); autogenerate = zero ops on both; `downgrade -1` of this rev +
  of P1.3 both reversible on MariaDB; app boot + `seed.py` + login + `/patients` +
  `/patients/{id}/audit-log` all 200 on MariaDB as `clarion_app`.
  **S3 (FK `ondelete` consistency) deferred** — no Patient-delete/merge path
  exists anywhere in the codebase (system is immutability-first), so the RESTRICT
  vs CASCADE gap is theoretical and fails *safe* (error 1451) if one is ever added.
  Do it with that feature.
  **Pre-existing baseline bug found (NOT P1.2b/P1.3):** `5e6a60dfe274.downgrade()`
  fails on MariaDB — `1553 Cannot drop index 'ix_admissions_ward_id': needed in a
  foreign key constraint` (drop order isn't FK-safe; SQLite never enforced it).
  Forward `upgrade` is clean both engines; only full `downgrade base` breaks.
  Fix belongs to **P1.5** (regenerate/repair baseline) and blocks the **P2.11**
  CI "upgrade head then downgrade base" rollback gate.
- **2026-08-30** — **P1.3 done** (agy Gemini 3 Pro, Claude-fixed + verified). MariaDB
  cutover: `database.py` reads `DATABASE_URL` (default `sqlite:///./clarion.db`),
  dialect-branched engine args — SQLite keeps `check_same_thread`; MySQL/MariaDB gets
  `pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800`. New
  `DB_BACKEND` export. `PyMySQL==1.1.1` added (pure-Python driver). `RoomClaim`
  active-claim exclusivity **restored** as two VIRTUAL generated columns
  (`active_room_key` / `active_user_key` = `CASE WHEN released_at IS NULL THEN
  room_id/user_id END`) + plain `UniqueConstraint` — NULL is non-colliding on both
  engines, so released claims never collide. Alembic revision **`9f2c8a1b7e4d`**
  (down_revision `5e6a60dfe274`), `batch_alter_table` for SQLite compatibility.
  `main.py` now guards `_migrate_lightweight()` behind `_IS_SQLITE` — on MariaDB
  Alembic owns the schema. New `backend/db/mariadb/10-accounts.sh` (initdb hook)
  creates the 3 least-privilege accounts: `clarion_app` (DML), `clarion_migrate`
  (DDL, deploy-time), `clarion_report` (read-only). `docker-compose.yml` mounts the
  init script + passes `MARIADB_{APP,MIGRATE,REPORT}_PASSWORD`; `MARIADB_USER`/
  `MARIADB_PASSWORD` removed. `.env.*.example` + `docs/deployment.md` updated.
  **Claude fixed 3 bugs agy's self-check missed:** (1) `database.py` had dropped
  `SessionLocal` → every DB endpoint would `NameError`; (2) `10-accounts.sh` did
  `REVOKE UPDATE,DELETE ON clarion.audit_logs` → MariaDB error 1147 (no
  `partial_revokes`), aborting container init — removed, audit append-only deferred
  to **P2.9** as a trigger; (3) `_migrate_lightweight()` ran unguarded on MariaDB
  and its length-less `VARCHAR` + `CREATE ... INDEX ... WHERE` partial-index DDL is
  invalid MySQL → app wouldn't start. **Verified** (Claude, clean state): fresh
  SQLite + fresh MariaDB 11.4 `alembic upgrade head` both clean; autogenerate =
  zero ops on both; batch upgrade preserves existing `room_claims` rows + computes
  the generated keys + enforces uniqueness; app boots on SQLite (fresh + existing
  `clarion.db`) and MariaDB; `seed.py` + login→`/patients` flow works as the
  DML-only `clarion_app`; `clarion_app` denied DDL; RoomClaim uniqueness (4
  scenarios) enforced via ORM on real MariaDB.
  **voltagent DBA review actioned** (2026-08-30): fixed B1 — `create_all()` also
  guarded to SQLite (`main.py`), was still running on MariaDB as `clarion_app` →
  would crash-loop with a misleading DDL-denied error on any schema drift or if
  started before `alembic upgrade head`. Applied S1 pool hardening
  (`max_overflow=30`, `pool_timeout=10`, `pool_use_lifo`, `isolation_level="READ
  COMMITTED"`, unconditional `connect_args={"charset":"utf8mb4"}`), S2
  (`WITH MAX_USER_CONNECTIONS 160/20` on app/report accounts; root pw in the guard
  check; dropped needless `FLUSH PRIVILEGES`), S4 (`render_as_batch` scoped to
  SQLite in `env.py`), S6 (stale compose/deploy-doc comments). Re-verified all of
  the above on fresh MariaDB 11.4 + SQLite. **Deferred to new task P1.2b** (before
  P1.4): B2 — `DateTime(timezone=True)` renders as bare `DATETIME` (no fractional
  seconds, tz ignored) on MariaDB → `.with_variant(mysql.DATETIME(fsp=6))` sweep +
  `id`-tiebreak on audit ordering; S3 — FK `ondelete` is CASCADE on 6 patient-child
  tables but absent (RESTRICT) on `queue_tickets` / `admissions` /
  `emergency_tokens` / `self_registration_attempts` /
  `appointment_reschedule_requests` — make uniform. B3 (the SQLite→MariaDB data
  scan/repair plan: generated cols, active-claim dupes, collation collisions, FK
  orphans, over-length strings, JSON validity, insert order) **is** the P1.4 spec.
- **2026-08-30** — P0.4 **done** (Claude). New `backend/app/ai/_cloud_guard.py`;
  `summarize.py` + `nric_ocr.py` now gate the Anthropic path on
  `cloud_ai_enabled()` — disabled unless BOTH `ANTHROPIC_API_KEY` and
  `CLARION_ALLOW_CLOUD_AI=1` are set. Verified: fallback triggers by default, app
  still imports. `.env.example` documents the opt-in. *(interactions.py's NIH
  RxNav/DailyMed calls are separate — handled in P4.4.)*
- **2026-08-30** — **P1.1 done** (agy Gemini 3.7 Flash, Claude-verified). Alembic
  added (`backend/alembic/`, `alembic.ini`, `alembic>=1.13` in requirements).
  `env.py` → `Base.metadata` + `DATABASE_URL` env, `compare_type` + batch mode.
  Baseline revision `5e6a60dfe274` creates all 30 tables. **Verified:**
  `alembic upgrade head` on fresh SQLite works; autogenerate against a
  `create_all()` DB emits **zero ops** (baseline is faithful to `models.py`);
  existing `clarion.db` still starts + serves; login/lockout/patient endpoints OK.
  Existing DBs need a one-time `alembic stamp head` (see `backend/alembic/README.md`).
- **2026-08-30** — **P1.2 done** (agy, Claude-verified). `models.py` portability
  sweep: explicit `String(N)` on ~70 columns, `DateTime(timezone=True)` +
  aware-UTC defaults on ~45, `ondelete="CASCADE"` on the 6 patient-child FKs,
  `MetaData` naming convention in `database.py`. `RoomClaim` SQLite partial unique
  indexes dropped → active-claim exclusivity now via the Python guard in
  `reception.py::claim_room` + `staff.py::clock_out` (the demo keeps the DB
  backstop via `_migrate_lightweight` until P1.5; **P1.3 restores it as a MariaDB
  generated-column unique**). No schema drift found between `models.py` and
  `_migrate_lightweight()`. Follow-up: sweep the remaining naive `datetime.utcnow()`
  in `auth.py` / `routers/*` to aware for consistency (no live bug — DB round-trip
  strips tzinfo on both SQLite and MySQL). One stray `docstring_parser` line landed
  in `requirements.txt` (nothing imports it — safe to drop on review).
- **2026-08-30** — **P1.11 done** (docker specialist, Claude-verified at config
  level). New: `backend/Dockerfile` + `.dockerignore`, `web/Dockerfile` +
  `nginx.conf` + `entrypoint.sh` + `.dockerignore`, `docker-compose.yml` (backend,
  web, mariadb 11.4, minio, redis, orthanc + postgres index — only web/backend
  publish ports, healthchecks + named volumes throughout), `.env.docker.example`,
  `docs/deployment.md`. **Verified:** `docker compose config` parses; all image
  tags resolve in the registry. Claude fixed: the gunicorn worker class
  (`uvicorn_worker.UvicornWorker` — uvicorn 0.52 dropped `uvicorn.workers`),
  `.gitignore` (un-ignore `.env.docker.example`), added `.gitattributes` (LF for
  `*.sh`). **Not yet run:** a full `docker compose build` (needs image pulls).
  MariaDB/MinIO/Redis env vars wired speculatively — the app reads them from P1.3/P1.6.

---

## P0 — Hygiene (do now, ~1 week)
| # | Task | Size | Why | Status |
|---|---|---|---|---|
| P0.1 | Commit the ~7 untracked backend routers + working tree in reviewable chunks | S | Half the codebase is uncommitted | user handles commits |
| P0.2 | Delete legacy `mobile/` (RN app) + stale `comiin.db`; reconcile MediBridge/comiin/CLARION naming | S | Cruft | ✅ 2026-09-07 |
| P0.3 | Add `AGENTS.md` at repo root pointing agents at this vault | S | So future sessions load context cheaply | ✅ 2026-08-30 |
| P0.4 | **Guard the Anthropic cloud path** — disabled unless an explicit dev override is set | S | [[Security Audit#C1]] | ✅ done 2026-08-30 |

## P1 — Foundations (language-independent; survives the CI4 port)
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P1.1 | `MetaData` naming convention + Alembic + reviewed baseline + `stamp head` | M | | ✅ 2026-08-30 |
| P1.2 | Portability sweep of `models.py` — the 12 SQLite-isms in [[On-Prem Architecture]] | M | | ✅ 2026-08-30 |
| P1.3 | MariaDB 11.4 container + env-driven DB URL + pool + 3 least-priv grants + restore RoomClaim active-unique | S | | ✅ 2026-08-30 |
| P1.2b | MariaDB precision (DBA review B2): `DateTime`→`DATETIME(6)` variant + audit `id`-tiebreak. *(S3 FK `ondelete` deferred — no delete path exists)* | S | | ✅ 2026-08-30 |
| P1.4 | SQLite→MariaDB data migration w/ type coercion + orphan check + reconciliation report | M | | ✅ 2026-08-30 |
| P1.5 | Delete `_migrate_lightweight` + `create_all`; fix `5e6a60dfe274` FK-unsafe downgrade; `db/check_schema.py` CI gate | S | / [[Security Audit#M9]] | ✅ 2026-08-30 |
| P1.6 | `ObjectStore` abstraction + MinIO + `*_object_key` columns + move `uploads/` | M | | ✅ 2026-08-30 (staged Claude-owned passes; `storage.py` + 2 Alembic revs + `migrate_uploads_to_objectstore.py`; verified SQLite + MariaDB + real MinIO) |
| P1.7 | Image-normalisation pipeline (Pillow: EXIF/GPS strip, resize, thumbnail) | S | | ✅ 2026-08-30 (`app/imaging.py` + `app/derived.py`; medicine photos normalised in place, doc previews in `clarion-derived`; 2 thumbnail endpoints; 36 new tests; no schema change; verified SQLite + MariaDB + MinIO). Sync-at-upload — async worker is a later call, see P1.7 progress-log note |
| P1.7b | Imaging follow-ups (voltagent arch review 2026-08-30): **PDF first-page preview** (`pypdfium2` — NOT PyMuPDF/AGPL); **web-preview ~1400px variant** (`/preview` endpoint, cuts the 15MB original off the Branch WAN + serves a metadata-stripped view of doc images by default — PDPA); **HEIC** input (`pillow-heif`, iOS default); **async job seam** = MariaDB `jobs` table + `FOR UPDATE SKIP LOCKED` worker (NOT rq/Celery — survives the CI4 port), `prime_thumbnail`→`enqueue` behind `CLARION_SYNC_DERIVE` (demo stays inline); **consolidate the 3 copies of magic-byte sniffing**; ETag/`If-None-Match` on derived responses; bump `clarion-derived` ILM 30→180d | M | | — |
| P1.8 | Env-driven config — kill hardcoded `localhost`, CORS allowlist, runtime `config.js` via proxy | S | / [[Security Audit#M3]] | ✅ 2026-08-30 (backend CORS + Flutter already env-driven; wired the web SPA to consume `/config.js` → `VITE_API_BASE` → localhost; `entrypoint.sh` `$API_BASE` injection-hardened; agy sweep + voltagent review). Legacy `mobile/` RN client still hardcoded — dies in P0.2 |
| P1.9 | Reverse proxy (Caddy/nginx) + CAMPUS-CA TLS + CSP + HSTS | S | | ✅ 2026-08-30 (`proxy/Caddyfile` Caddy 2.8 — TLS term, HTTP→HTTPS, HSTS+CSP+headers, `/api`→backend routing; only service with host ports; proxy pinned `172.28.0.2` = the `FORWARDED_ALLOW_IPS` trust anchor; verified live incl. XFF-spoof test). Prod TODO: drop the CAMPUS-CA cert in `proxy/certs/` + flip `CLARION_TLS_DIRECTIVE`; `style-src` tighten |
| P1.10 | **LDAP/AD** provider — service bind → search → user bind, JIT provision, `ldap_role_map` | M | **** | ✅ 2026-09-07 (backend + admin CRUD; no web UI yet) |
| P1.11 | Containerise full stack + offline image bundle/registry + Docker secrets | M | | ✅ 2026-08-30 (offline bundle + secrets still TODO) |
| P1.12 | Backend `pytest` suite scaffold (auth, RBAC, cross-facility immutability first) | M | 10.1.5 | ✅ 2026-09-07 (`tests/conftest.py` + `test_auth_rbac_immutability.py`) |
| P1.13 | Flutter release signing (real keystore + `key.properties`) | S | — | ✅ 2026-09-07 (gradle wiring + docs; real keystore generation is the team's own step) |

## P2 — Security & compliance
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P2.1 | Fix [[Security Audit]] H1 — gate emergency endpoints behind `require_page_access` + facility scoping | M | | ✅ 2026-09-07 |
| P2.2 | Fix H2 — default-deny cross-facility, reason-logged break-glass, scope + paginate `list_patients` | M | | ✅ 2026-09-07 |
| P2.3 | Fix H3 — random seed passwords + `must_change_password`; real staff password policy | S | | ✅ 2026-09-07 |
| P2.4 | Fix M1/M2 — per-IP login + OTP throttle; indexed normalized-NRIC column | S | | ✅ 2026-09-07 |
| P2.5 | Fix M4 — short access-token TTL + refresh in `HttpOnly` cookie + `jti` deny-list; strict CSP | M | | ✅ 2026-09-07 (CSP residual — see log) |
| P2.6 | Fix M5/M6/M7/M8 — upload magic-byte + AV hook; verified responder credential; HMAC card key + PIN; stop logging clinical values into `audit_logs.detail` | M | | — |
| P2.7 | Encryption at rest — MariaDB encrypted tablespaces + on-prem key management | M | | — |
| P2.8 | **Backup / DR regime** — daily incr + weekly full + binlog shipping, encrypted, 30-day, pre-update image, quarterly restore test, documented RPO/RTO | L | **** | — |
| P2.9 | Audit **hash-chain** + daily WORM seal + retention/partition policy | M | | — |
| P2.10 | PDPA — consent model + data-subject-request flow + DPO register + retention config | M | | — |
| P2.11 | Offline CI: Gitea + ruff/pytest/bandit/semgrep/pip-audit/trivy + alembic up/down check | M | | — |
| P2.12 | `data_quality_alerts` — batch validators (missing values, dup patients, bad coding) | S | | — |

## P3 — Tender modules
| # | Task | Size | Clause |
|---|---|---|---|
| P3.1 | **Ancillary engine** — `service_requests` + order → encounter → result → sign-off → document; then Procedure, Laboratory, X-ray, Physiotherapy faces | L | –10 |
| P3.2 | **Dental module** + tooth-chart UI (FDI notation) | M | |
| P3.3 | **Billing module** — charge master, `bills`, `bill_items`, `payments`, `claims`; wire consultation / pharmacy / ancillary fees | L | + per-module billing |
| P3.4 | Consultation: structured **SOAP** notes, treatment plan, follow-up scheduling, referral UI | M | –4 |
| P3.5 | Document generation — Digital Medical Certificate, Referral Letter, Timeslip (PDF) | M | |
| P3.6 | **Reporting engine** + **Custom Report Builder** (field picker across modules, filter/group, template store) | L | |
| P3.7 | **MOH / statutory reporting** — notifiable disease (e-Notifikasi format), HMIS returns, anonymization | M | |
| P3.8 | **Management Dashboard** — KPI view + patient-flow prediction (EWMA/GBM) + operational health score | M | |
| P3.9 | Calling-system hardware — ticket printer (ESC/POS), TV display **audio** + branding | S | –3 |
| P3.10 | Mobile: slot booking by dept/doctor, vitals view, PDF visit summary, server push, announcements | M | –5 |

## P4 — Interoperability, AI & imaging
| # | Task | Size | Clause |
|---|---|---|---|
| P4.1 | **FHIR-readiness migrations** — coding triples, `resource_identifiers`, resource tables, terminology seeds, backfill queue | L | **** → [[FHIR Schema Readiness]] |
| P4.2 | Thin **read-only FHIR façade** + CapabilityStatement | L | |
| P4.3 | **On-prem AI engine** — replace ALL Claude-API calls; local LLM (Ollama/vLLM) + `faster-whisper`; CDS hint, medication-safety alert, voice→SOAP, NL reports | L | **–17** → [[On-Prem Clinical AI]] |
| P4.4 | Medication-safety = rule engine + licensed drug DB (MIMS) integration | M | |
| P4.5 | AI audit-trail intelligence + access anomaly detection over the hash-chain | M | –7 |
| P4.6 | Predictive analytics + population-health stratification in Reporting | M | |
| P4.7 | **PACS** — Orthanc + PG index + S3 plugin + Modality Worklist + OHIF viewer + auto-link | L | **** → [[PACS and DICOM]] |
| P4.8 | Integration layer — SMP / SMS / e-klinik / Registrar (read-only) + lab-analyser HL7 v2 service + label printers | L | → [[Integration Engine and LDAP]] |

## P5 — Ops & handover
| # | Task | Size | Clause |
|---|---|---|---|
| P5.1 | Observability — structured logging, Loki, Prometheus, Grafana, Alertmanager (email + WhatsApp) | M | |
| P5.2 | Load testing to 23k users; tune pools + workers | M | |
| P5.3 | Two-campus rollout — WAN validation + Branch edge + offline emergency-export appliance | M | — |
| P5.4 | Docs & handover — auto-generated ERD / data dictionary, Operations / Programming / Maintenance manuals, DR runbook, Transfer-of-Technology package | M | 7.1 / 3.2.5 / |

---

## Risk register
| Risk | Severity | Mitigation |
|---|---|---|
| **PHP port underestimated** — 2–4 PM assumes disciplined layering from day one | High | Apply the [[Designing for the PHP Port]] checklist continuously, not retroactively |
| **On-prem AI on venue hardware** — no capable GPU on the demo laptop | High | Confirm hardware early; keep a small quantised model that runs on CPU as a floor |
| **SaMD regulation** — CDS + result-interpretation are regulated medical devices for a real deployment | Medium | Out of scope for the competition; named workstream for the tender; frame all AI as clinician reference aids |
| **Personnel (clause 10.3)** — need MBOT technologist + MMC clinical advisor + HIMSS/HL7 credential | Medium | **Open question — does the team have these lined up?** Bid blocker, not a demo blocker |
| **No MHNexus public API** — the tender can only be met as schema-readiness | Medium | [[FHIR Schema Readiness]]; direct enquiry to MHNexus / MOH Digital Health Division about partner onboarding |
| **PDPA 2024 exact dates** still settling | Low | Re-check before any formal compliance submission — [[Malaysia Health Regulation]] |

## Demo priorities (for the competition, not the full build)
Ranked by impact per unit of effort:
1. **Offline AI, cable unplugged** — 8B model doing a live CDS hint + medication-safety alert, network visibly disconnected. The the tender differentiator.
2. **Voice → SOAP** — dictate, watch it land in the right fields.
3. **DICOM viewer** — open a chest X-ray inside a record, zoom & measure.
4. **Patient-flow prediction + operational health score** on the dashboard.
5. **The emergency scan** — already built; lead the deck with it (most human moment).

Deprioritise for the demo: billing, custom report builder, ancillary modules beyond
one worked example, anything needing the University's internal systems (mock with a labelled adapter).
