---
title: Security Audit
type: assessment
updated: 2026-09-07
tags: [security, owasp, pdpa, audit, clarion]
---

# Security Audit

Static audit of `backend/app/` against OWASP and security
clauses. **1 Critical · 4 High · 9 Medium · 5 Low.** Every finding
has a `file:line` and a blocked clause. C1 and H2 were re-verified against the code by
hand; the rest are internally consistent and reliable.

Fix order: **C1 → H1 → H3 (fast) → H2 → H4 → M1/M2 → M3/M4 → M5–M9 → L-items.**

---

## C1 — Full PHI + MyKad images sent to third-party US cloud
**Critical.** Blocks, (PDPA cross-border), (OWASP A10).
- `ai/summarize.py:52-72` — posts the entire serialised patient record (`f"{patient}"`
  at L65) to `anthropic.Anthropic().messages.create()` when `ANTHROPIC_API_KEY` is set.
  Caller `routers/ai_router.py:47`.
- `ai/nric_ocr.py:122-166` — base64-encodes the photographed **MyKad** and sends it to
  Claude vision. Caller `routers/self_registration.py:493` (`verify-photos`) has only
  `Depends(get_db)` — **unauthenticated**.
- `ai/interactions.py:194-209` — drug names to `rxnav.nlm.nih.gov` / `dailymed.nlm.nih.gov`.
- **Fix:** remove all outbound AI/lookup calls; local inference only ([[On-Prem Clinical AI]]).
  Interim: refuse to start if `ANTHROPIC_API_KEY` is set without an explicit dev override.

## H1 — Emergency endpoints bypass the role/page-permission model
**High.** `routers/emergency.py:189` (issue), `:339` (status), `:520` (list_nfc),
`:324` (revoke). Router mounted `main.py:615` with **no `require_page_access`**; the
only check is `role == "patient" and patient_id != payload.patient_id`. A `pharmacist`
or `receptionist` token can issue a card for any patient, then read PHI via the
unauthenticated scan endpoint. No facility scoping.
Blocks, PDPA Principle 1/3.
✅ **RESOLVED 2026-09-07 (P2.1).** All 4 endpoints now depend on
`auth.require_page_access("patients")` (a pharmacist/receptionist is blocked by
default, same mechanism `patients.py`/`reception.py`/`pharmacy.py` already use) —
a `patient` role is unaffected (excluded from `CONFIGURABLE_STAFF_ROLES`, so its
own self-service issue/revoke/view keeps working, gated only by the existing
per-endpoint "is this your own record" check). Facility scoping added via new
`_require_patient_present_for_staff` (staff callers only, not the patient
themself): blocks unless the patient has an active `Admission` or an open
today's `QueueTicket` at the ACTING staff's own facility — the exact same
`_patient_present_at` rule `patients.py`'s cross-facility clinical-record
immutability guard uses, **no admin override**, matching that guard's own
documented precedent. `POST /emergency/scan` and `POST /emergency/nfc/scan`
deliberately untouched (intentionally public, the life-safety break-glass
design — out of scope for this finding). New
`backend/tests/test_emergency_access_control.py` (9 tests). Verified: full
suite 115/115 pass.

✅ **RESOLVED 2026-09-07 (P2.2).** The tension this finding names ("coherent
with CLARION's cross-hospital premise; a gap against the tender's
single-facility need-to-know model") is resolved by treating list vs.
detail access differently, per user-confirmed design direction:
- `GET /patients` (browse-everyone) **default-denies cross-facility** now —
  scoped to patients this user's facility has an actual relationship to
  (an encounter, an authored condition/medication/allergy, an admission, a
  queue ticket, or a scheduled appointment there — `_facility_known_patient_ids`
  in `patients.py`), paginated (`skip`/`limit`, max 200). There is no
  emergency urgency to browsing every patient in the system, so this one
  can safely default-deny. An explicit, non-blank `break_glass_reason`
  query param unlocks the full list, audit-logged
  (`action=list_patients_break_glass`) — **no admin override on the
  scoping itself**, matching `_guard_cross_facility_amend`'s own
  precedent (need-to-know, not role seniority).
- `GET /patients/{id}` (single-patient detail) **stays fully open** — this
  is the actual continuity-of-care/emergency-first mechanism CLARION is
  built around, and blocking a walk-in/emergency lookup could cost real
  time. Instead it now logs a DISTINCT action
  (`view_full_record_cross_facility` vs. the existing plain
  `view_full_record`) whenever the caller's facility has no relationship
  to the patient (`_patient_known_to_facility`, a cheap short-circuiting
  per-patient check, not the bulk form) — the real-world hospital
  "break-the-glass" pattern: allow, but make it fully reviewable after the
  fact, never indistinguishable from a routine local lookup.
Web console updated to match: `PatientList.jsx` now requests up to 200
(this app's actual clinic-scale, keeping its existing "fetch + client-side
filter" pattern working) and adds an explicit "search all facilities"
override UI that collects a reason and surfaces an "All facilities —
audited" badge when active, rather than silently truncating or hiding the
scoping change from the user. New
`backend/tests/test_patients_facility_scoping.py` (8 tests). **Verified:**
full backend suite **123/123 pass**, `npm run build` clean, `pyflakes`
clean.

## H2 — No need-to-know / facility scoping on patient records
**High.** `routers/patients.py:370` `list_patients()` = `db.query(Patient).all()` —
every patient, no scope, no pagination — to any admin/records_officer/clinician. `:378`
`get_patient_full_record` — any staff token, any patient id, full history. The only
cross-facility control (`HospitalSetting.records_shared_publicly`) is opt-out per
authoring facility and only filters sub-records; the index is never scoped; no
break-glass. *(Coherent with CLARION's cross-hospital premise; a gap against the
tender's single-facility need-to-know model.)*
Blocks, PDPA Principle 1/3, OWASP A01.

## H3 — Weak seeded credentials, no forced rotation
**High.** `backend/seed.py:14-72,271-296` — `admin123` / `clinician123` /
`pharmacist123` / `receptionist123` / `patient123`, none set `must_change_password`,
printed to stdout, committed. `schemas.py:14` `MIN_PASSWORD_LENGTH = 8`, no complexity.
`password_changed_at` stays NULL → the JWT revocation watermark (`auth.py:197-204`)
never engages for these accounts.
Blocks, 10.1.5, OWASP A07.
✅ **RESOLVED 2026-09-07 (P2.3).** `seed.py` now gates the memorable demo
passwords behind the SAME `APP_ENV`/`DEMO_MODE=demo` signal `main.py`'s CORS
wildcard opt-in already uses: outside demo mode, every seeded account gets
a fresh password via `auth.generate_temp_password()` (cryptographically
random, already used for staff-issued temp passwords elsewhere),
`must_change_password=True`, printed to the console exactly once (never
logged to a file) for the operator to hand off securely — closing "no
forced rotation" for any real deployment while keeping the demo/judge
experience unchanged (demo accounts are contained to a non-production
signal by construction, so the "never rotated" residual there is
low-stakes). **Password policy** (`schemas.py`): `MIN_PASSWORD_LENGTH`
8→12, plus a new `_WEAK_PASSWORD_DENYLIST` (common passwords + this app's
own seeded demo credentials, so a real user can never coincidentally reuse
one). Deliberately still no mandatory character-class complexity — this
follows NIST SP 800-63B, which recommends length + a weak-password check
over composition rules (which mostly push people toward predictable
substitutions); the existing length-only design in this codebase already
reasoned this, this just strengthens it rather than reversing it. New
`backend/tests/test_seed_password_policy.py` (4 tests, runs `seed.py` as a
real subprocess in both modes against a throwaway DB and inspects both
stdout and the stored password hashes). README/deployment.md updated to
document the production behavior. **Verified:** full suite **127/127
pass** (123 prior + 4 new), both seeding modes manually run end-to-end,
`pyflakes` clean.

## H4 — No encryption at rest; fails the tender RDBMS requirement
**High.** `database.py:4` `sqlite:///./clarion.db`; `main.py:68-91` copies the
**unencrypted** DB to `backend/backups/` with no retention; `main.py:94-486`
`_migrate_lightweight()` runs hand-rolled `ALTER TABLE` at every startup, no Alembic,
no rollback; SQLite FK enforcement is off.
Blocks (encryption at rest),,.
Resolved by the MariaDB move — [[On-Prem Architecture]].

---

## Medium
- **M1 — no per-IP login throttle.** `auth_router.py:175-176` `@limiter.exempt`;
  lockout is per-account only → password-spraying unthrottled; conversely every staff
  account can be locked out on demand (`:228-232` never resets the counter after the
  lock lapses).
  ✅ **RESOLVED 2026-09-07 (P2.4).** `POST /auth/login` → `@limiter.limit("20/minute")`
  per-IP, ON TOP OF the existing per-account lockout (the per-account counter alone
  can't catch a spray across many DIFFERENT accounts from one IP). Separately fixed
  the actual DoS the finding names: when a lock had LAPSED, `login_failed_count`
  stayed at its old (>= `LOGIN_MAX_ATTEMPTS`) value, so one further wrong guess
  re-triggered the threshold check immediately and re-locked the account for
  another full `LOGIN_LOCKOUT_MINUTES` -- an attacker who merely knew the
  identifier could keep it locked out indefinitely with one request every
  lockout window, never guessing the password. Now the counter resets to 0 the
  moment a lapsed lock is observed, before the password check -- a lapsed
  timeout is a fresh start requiring a full new run of `LOGIN_MAX_ATTEMPTS`
  wrong guesses to re-lock. New `backend/tests/test_login_rate_limiting.py`
  covers both (5 tests).
- **M2 — unauthenticated OTP / self-registration endpoints are `@limiter.exempt` +
  O(n) table scan per call.** `_resolve_patient_by_nric` (`auth_router.py:92-109`)
  loops every patient — also on every login. Add a per-IP limit + an indexed
  normalized-NRIC column.
  ✅ **RESOLVED 2026-09-07 (P2.4).** Per-IP limits added to
  `/auth/request-password-reset-otp` + `/auth/reset-password-with-otp`
  (`10/minute` each) and self_registration's `/start` + `/verify-otp`
  (`10/minute`) + `/complete` (`20/minute`, lighter since it's gated behind
  the other two) -- all previously `@limiter.exempt` on the theory that their
  own persisted per-account/per-attempt counters were sufficient, which
  doesn't stop a caller spraying across many different NRICs from one IP.
  **Indexed lookup:** new `models.Patient.normalized_national_id` (unique,
  indexed), kept in sync automatically by a `@validates("national_id")` model
  hook (fires on ANY assignment -- ORM construction, a later write, a test
  fixture -- not just today's one real write path) rather than requiring
  every call site to remember to set it. `auth_router._resolve_patient_by_nric`
  is now a single indexed query instead of a fetch-every-patient loop, and
  THREE other copies of that same loop (`patients.py::create_patient`'s
  duplicate check, `reception.py::_resolve_patient` check-in-by-IC,
  `reception.py::_resolve_patient_for_admission`) were found and consolidated
  onto the same resolver. Alembic `649f25aeb36f` adds the column + backfills
  every existing row from its `national_id`. New
  `backend/tests/test_login_rate_limiting.py` (rate limits) +
  `test_normalized_national_id_kept_in_sync_by_model_validator` cover this.
- **M3 — CORS defaults to `*`.** ✅ **RESOLVED 2026-08-30 (P1.8).** `main.py`
  now fails **closed**: `allow_origins=["*"]` requires an explicit `APP_ENV=demo`
  (or `DEMO_MODE∈{demo,1,true}`) opt-in; unset or any non-demo value with no
  `CORS_ALLOWED_ORIGINS` → `allow_origins=[]` + a startup warning. `.env*.example`
  ship `APP_ENV=demo` so local dev is unaffected. Same pass hardened
  `entrypoint.sh` `$API_BASE` interpolation and removed
  `--forwarded-allow-ips "*"` (see roadmap P1.8 F1/F2). *(Update, P2.5:
  `allow_credentials` is no longer unconditionally `False` — it's `True`
  exactly when an explicit `CORS_ALLOWED_ORIGINS` allowlist is set, needed
  for the new refresh-token cookie to work cross-origin; still spec-safe,
  since that's never combined with the `*` wildcard. See M4.)
- **M4 — 8-hour JWT, no revocation list, `localStorage`, watermark gap.** `auth.py:43`;
  revocation only via the `password_changed_at` watermark (no `jti`, no deny-list, no
  server logout; ineffective when NULL). `web/src/api/client.js:9-10,73-80`. No app CSP.
  ✅ **RESOLVED 2026-09-07 (P2.5, design confirmed with the user first --
  a bigger architectural change than P2.1-4).** `ACCESS_TOKEN_EXPIRE_MINUTES`
  8h → 15min. Staying logged in past that is now a separate, longer-lived
  refresh token (new `models.RefreshToken`, 30 days) delivered as an
  `HttpOnly`/`SameSite=Strict` cookie (web console, scoped to `path=/auth`
  — never reachable from JS, closing the localStorage exposure) or a plain
  JSON field (native/Flutter client, no cookie jar concept — stored via
  `flutter_secure_storage`, the OS keychain). `POST /auth/refresh` mints a
  fresh access token and **rotates** the refresh token (revokes the old
  one, issues a new one); presenting an already-rotated-away token is
  treated as a compromise signal -- revokes EVERY refresh token for that
  user. New `POST /auth/logout` is REAL server-side revocation (there was
  none before). A password change now also revokes every refresh token for
  the account, not just the access-token watermark. `main.py`'s CORS
  `allow_credentials` is now `True` only when an explicit
  `CORS_ALLOWED_ORIGINS` allowlist is configured (spec-required — never
  with the demo wildcard), so the cookie degrades gracefully (no refresh,
  re-login every 15 min) rather than misbehaving in cross-origin demo
  mode. Web client's interceptor + Flutter's `ApiClient` both transparently
  refresh-and-retry once on a 401, single-flighted so concurrent 401s don't
  each race the backend's single-use rotation. Verified end-to-end against
  a live running backend (not just TestClient) via a Node script exercising
  the real HTTP/cookie contract. No app-level CSP still not done (a smaller,
  separate residual — see the web console's existing edge-proxy CSP from
  P1.9, which covers the transport layer but not an app-embedded meta-tag
  CSP).
- **M5 — `POST /ai/digitise/{id}` accepts any file type**, no magic-byte check, no AV.
  `ai_router.py:87-167`. Serve-side is mitigated (nosniff + attachment for
  non-allowlisted types); the PTM antivirus hook is never called.
  🟡 **PARTIALLY RESOLVED 2026-09-07 (P2.6, in progress).** **Magic-byte
  check fixed:** an image-shaped upload (`imaging.is_supported_image`) is
  now validated through `imaging.validate_image_safe_to_decode` (P1.7's
  same format allowlist / pixel-bomb ceiling / animation-frame guard /
  concurrency gate `normalise_image`/`make_thumbnail` already use) BEFORE
  any decode is attempted for OCR — previously this endpoint bypassed
  `imaging.py` entirely and handed raw bytes straight to a bare
  `PIL.Image.open()`, reachable even for the CVE-prone formats P1.7
  deliberately excludes (e.g. TIFF). A non-image upload (a genuine PDF
  scan, the common real case) is still tolerantly accepted — OCR is
  skipped with a clear note, the original is still archived — that
  behavior is unchanged, only the "is this superficially image-shaped"
  path is now gated. New `backend/tests/test_digitise_document_safety.py`
  (3 tests: valid image still OCRs, a non-image upload isn't rejected, a
  corrupt-but-PNG-signed upload fails safety validation gracefully, no
  500). **AV hook — re-scoped, not built:** re-reading the tender
  itself (`healthcare/Tender Clauses Section 10.md`) and this project's own
  `healthcare/Compliance Matrix.md` shows antivirus here is explicitly
  **provided by PTM (the University's own IT department) at the host/VM level** —
  "Vendor configures the Virtual Server prepared by PTM + Antivirus
  provided by PTM" — already correctly marked N/A/Contractual in the
  Compliance Matrix. Building an application-level ClamAV-style scanner
  would be solving a problem the tender explicitly assigns to the
  university's infrastructure team, not CLARION's code. No app-level AV
  integration was built; this sub-finding is considered addressed by
  correcting its scope, not by writing unused/speculative infrastructure.
  **Verified:** full suite **144/144 pass** (141 prior + 3 new),
  `pyflakes` clean. **M6/M7/M8 still open** — see the roadmap's P2.6 row.
- **M6 — emergency-scan audit trail is unauthenticated + self-asserted.**
  `emergency.py:262-321`. The audit "actor" is free text from the request body
  (`responder_name` / `responder_org`), never verified.
- **M7 — emergency NFC cards: cloneable low-entropy key, 1-year default.**
  `emergency.py:396-452`; `schemas.py:1382-1402` default `valid_minutes=525600`.
  Raw MIFARE UID used verbatim as the lookup key. QR `card_reference` is stronger.
  `_scoped_fields` (`emergency.py:96`) always returns name + DOB regardless of scope.
- **M8 — clinical data written into `audit_logs.detail`.** `patients.py:524` (diagnosis
  name), `:589` (drug name), `:642` (allergen). The audit store becomes a second,
  less-controlled copy of clinical data.
- **M9 — `_migrate_lightweight()` auto-runs DDL at every startup.** ✅ **RESOLVED
  2026-08-30 (P1.5).** `_migrate_lightweight()` + `create_all()` deleted from
  `main.py`; Alembic is now the only schema path. `_ensure_schema()` auto-migrates
  the SQLite demo and *verifies-or-refuses* on MariaDB (runtime account `clarion_app`
  has no DDL grant). `db/check_schema.py` gates migration integrity in CI (P2.11).

## Low
- **L1 — dependencies.** `python-jose==3.5.0` + `ecdsa==0.19.2` (Minerva
  CVE-2024-23342, no fix — *not exploitable*, HS256 only); `bcrypt==4.0.1` pinned for
  `passlib==1.7.4`, silently truncates >72-byte passwords; no SCA in the pipeline
Move off `python-jose` / `passlib`; add `pip-audit`.
- **L2 — size-check-after-full-read** in every upload path; no ASGI body cap.
- **L3 — `bridge/nfc_bridge.py`** is well-hardened (127.0.0.1 bind, Host allowlist,
  strict CORS, `/debug/scan` gated). Residual: any local process can `GET /last-scan`
  to read the UID, which is a bearer credential for `/emergency/nfc/scan` (M7).
- **L4 — `ai/ocr.py:30-31`** persists exception text into `ClinicalDocument.raw_text`.
- **L5 — `schemas.py:257-273`** `PatientProfileUpdate` uses `extra="allow"` (every
  other Update schema uses `extra="forbid"`); safe today only because the handler
  filters fields explicitly.

## Checked — clean
No SQL injection. JWT algorithm pinned (`auth.py:185`), no hardcoded secret fallback,
role re-resolved live from DB. OTP reset flow soundly built — 6-digit keyed
HMAC-SHA256 at rest, `hmac.compare_digest`, 5 attempts then invalidated, 3 req/15 min,
10-min expiry, generic responses. File store/serve paths always built server-side from
row id + `os.path.basename`. admin/pharmacy/reception/consultation routers tenant-
isolated with non-leaking scoped-404s. Cross-facility record immutability +
emergency annotation-suppression gate are coherent and fail-closed on NULL author.
`routers/display.py` — 128-bit token, per-token rate limit, masked names by default.

---

## Code-review follow-up (2026-09-07)

A full parallel-agent code review (`/code-review`, scope = uncommitted
`backend/` + `web/`) ran after P2.1–P2.6. It surfaced one new instance of the
H1/H2 pattern plus a set of perf / deploy-safety findings not in the original
static audit. Backend fixes below all landed together (Claude, direct);
`git`-tracked as *"Code-review follow-up 2026-09-07"* in code comments (NOT
"P2.7" — that slug is already the roadmap's encryption-at-rest phase). **Full
backend suite 151/151 pass** (144 prior + 7 new
`test_appointments_access_control.py`), `alembic upgrade/downgrade` +
`db/check_schema.py` round-trip clean, `pyflakes` clean.

### CR1 — MyKad photos + OCR text staged for git commit **(Critical, fixed)**
`backend/_debug_photos/` held real photographed MyKad images + `.txt` files
with the OCR'd name / NRIC / address (the repo owner's own card) — output of
`self_registration.py::_debug_save_photo` (`SELF_REGISTER_DEBUG_SAVE_DIR`).
`backend/.dockerignore` covered it but `backend/.gitignore` did **not**, so
`git add -A` would have committed a government ID into history permanently.
**Fix:** directory deleted; `_debug_photos/` added to `backend/.gitignore`
with a comment tying it to the env var.

### CR2 — `GET /patients/{id}/appointments` under-authorized **(High, fixed)**
Same shape as H1/H2, missed because `appointments.router` was the one
patient-scoped router NOT under `require_page_access`. `list_appointments`
gated only on `role == "patient"` ownership, so any authenticated
pharmacist / receptionist / cross-facility clinician could read any patient's
appointment `reason` / `precaution_notes` / fasting instructions at any
facility, and the audit action didn't distinguish a cross-facility read.
**Fix:** router mounted under `require_page_access("patients")` (same as the
record itself + ai_router); `list_appointments` restricted to
admin / clinician / records_officer for staff (patient keeps own-record read);
a staff read whose facility has no relationship to the patient now logs
`view_appointments_cross_facility` (mirrors `get_patient_full_record`'s
break-glass audit). New `backend/tests/test_appointments_access_control.py`
(7 tests).

### CR3 — event-loop-blocking OCR on public endpoints **(High, fixed)**
`self_registration.py::verify_self_registration_photos` (public,
unauthenticated) ran two sequential blocking `extract_nric_fields` calls
(Tesseract subprocess / sync Anthropic client) inline in the event loop;
`ai_router.py::digitise_document` threadpooled its validate + thumbnail calls
but not `extract_text_from_image` (the heaviest) or the ObjectStore `put`.
**Fix:** `run_in_threadpool` throughout; the two NRIC extractions now
`asyncio.gather` off-thread.

### CR4 — interaction-check external-API fan-out **(High, fixed)**
`ai_router.py::get_interaction_check` called three functions that each
re-normalized every drug via RxNorm (~6N + N external calls), each spinning
up a fresh `httpx.AsyncClient`, with no cache between calls or requests.
**Fix:** `app/ai/interactions.py` gained a 1-hour process-local TTL cache on
`resolve_rxcui` / `get_rxcui_name` / `search_dailymed` and a single pooled
`AsyncClient`; the endpoint shares one `MedicationProvider` across the three
calls so the 2nd/3rd are cache hits.

### CR5 — irreversible migration with unenforced prerequisite **(High, fixed)**
`alembic/…/b7f1c0d94a2e_p1_6_drop_legacy_path_columns.py` dropped five
`*_path` columns; the docstring said "run `migrate_uploads_to_objectstore.py`
first" but nothing enforced it, so `alembic upgrade head` on a populated
MariaDB would permanently drop the only pointer to every stored blob.
**Fix:** `upgrade()` now aborts with a clear message if any row still holds a
legacy `*_path` value without a matching `*_object_key`;
`CLARION_FORCE_DROP_LEGACY_PATH_COLUMNS=1` is the explicit accept-the-loss
override. Also added a profile-gated `migrate` service to `docker-compose.yml`
(`docker compose --profile migrate run --rm migrate`) and documented the
ordered runbook in `docs/deployment.md`.

### CR6 — missing indexes + N+1 + list_patients scan **(Medium, fixed)**
New migration `d5e8a1c4b6f2_cr_performance_indexes.py`: `patient_id` on
conditions / medication_statements / allergy_intolerances / encounters /
clinical_documents / appointments / audit_logs (created with only a bare FK
before); the authoring-facility columns scanned by `list_patients`; and
`(facility_name, queue_date)` on `queue_tickets` (the ≤120/min public board
poll). `_serialize_patient` now computes the "patient present at caller's
facility" check once per record instead of per clinical sub-record (was ~80
redundant queries on a 40-record patient). `_facility_known_patient_ids` →
`_facility_known_patient_ids_select`: one SQL `UNION` subquery composed into
`Patient.id.in_(...)` so `list_patients` filters + paginates in the database
instead of materialising the whole set + a giant `IN (...)` literal.

### CR7 — observability on failure paths **(Medium, partly addressed)**
Added an app-wide `@app.exception_handler(Exception)` in `main.py`: every
unhandled exception is logged at ERROR with traceback + method/path + a short
correlation id, and the caller gets a clean `{"detail", "request_id"}` 500
(no exception text leaked). `pharmacy.py` + `ai_router.py` now log the
ObjectStore-failure paths they previously swallowed into a bare 503 /
best-effort rollback. `emergency.py` / `reception.py` have no `except` blocks,
so the global handler covers them. Structured logging + metrics + per-route
alerting stay deferred to roadmap P5.1.

### CR8 — dependency hygiene **(Low, fixed)**
Dropped `argon2-cffi` + `argon2-cffi-bindings` (never imported — `auth.py`
hashes with bcrypt). Moved `pytest` out of `requirements.txt` into a new
`requirements-dev.txt` so it is not baked into the runtime image.

### Deferred (tracked, not done this pass)
Web-side items from the review were all "suggestions", not blockers: the
multi-tab refresh-token logout race, the `Path=/auth` refresh cookie vs the
`/api/...` proxy path, the LDAP facility-admin → global-admin mapping path,
and the god-file / duplication cleanups (`AdminConsole.jsx`, `admin.py`,
`reception.py`). Lower-severity backend N+1 in the admin/reception list
serializers + pagination on the remaining unbounded list endpoints also
deferred. See the review summary for the full list.

---

Full text: `scratchpad/security-audit.md`. Feeds [[Implementation Roadmap]] phase P2.
