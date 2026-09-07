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
  ✅ **RESOLVED 2026-09-07 (P2.6).** New `auth.get_optional_current_user`
  (`OAuth2PasswordBearer(auto_error=False)` → `User | None`; a missing OR
  broken/expired token both yield `None`, never a 401 — a bad token must not
  turn a life-safety scan into an error; delegates to the same
  `_resolve_current_user` — signature + revoke-on-password-change — that
  `get_current_user` uses, so it's not an auth-bypass path; identity is used
  for audit attribution ONLY, scope is still `grant.scope`).
  `emergency._responder_audit()`:
  - **valid staff token** → audited under the **real user id + real role**,
    `actor_facility` recorded, `detail` prefixed `verified` with the typed
    name kept as `self_asserted=<name>`. The audit UIs already resolve a
    real user id → name, so these render as an attributed staff access.
  - **no/invalid token** → audited EXACTLY as before: `actor=
    "emergency_responder:<name>"`, `actor_role="emergency_responder"`. That
    role value already *means* "self-asserted, unverified"; a reviewer
    filtering `actor_role == "emergency_responder"` gets precisely the
    unverified accesses, and every existing consumer
    (`PatientDetail.jsx:1069`, `audit_log_screen.dart:55`,
    `patients.py:989`'s skip-optimisation) keeps working unchanged. (An
    earlier draft that changed the actor/role strings was reverted after
    the parallel-agent review flagged the 3-consumer format drift.)
  **Audit *action* strings deliberately unchanged** (`emergency_access` /
  `_nfc` / `_failed` / `_sharing_bypass`) —
  `mobile_flutter/.../audit_log_screen.dart` switches on the exact action
  for severity/labelling. `_audit_sharing_bypass_if_any` re-signatured
  `(db, patient, payload)` → `(db, patient, ident)` so the bypass row gets
  the same attribution as the access row. Unauthenticated flow otherwise
  unchanged: no new field, no 401, identical data returned. New
  `backend/tests/test_emergency_scan_audit_identity.py` (6 — unverified
  shape byte-identical to pre-M6, verified binds real id/role/facility,
  failed-scan unverified, NFC verified, broken-token→no-401, sharing-bypass
  attribution). **Verified 176/176.**
- **M7 — emergency NFC cards: cloneable low-entropy key, 1-year default.**
  `emergency.py:396-452`; `schemas.py:1382-1402` default `valid_minutes=525600`.
  Raw MIFARE UID used verbatim as the lookup key. QR `card_reference` is stronger.
  `_scoped_fields` (`emergency.py:96`) always returns name + DOB regardless of scope.
  ✅ **RESOLVED 2026-09-07 (P2.6)** — user picked HMAC-at-rest +
  minimise-payload + per-card anomaly logging; kept the 1-yr default expiry
  (an explicit choice, not an oversight).
  - **M7a — HMAC at rest.** `EmergencyToken.nfc_uid` now stores
    `auth.hash_nfc_uid(raw)` = keyed HMAC-SHA256 (`_OTP_HMAC_KEY`, domain
    separator `nfc-uid:`), never the raw UID. `auth.canonical_nfc_uid`
    normalises case + separators first, so register / scan / reception
    check-in all agree regardless of reader format. New cleartext
    `nfc_uid_last4` column (display only); `GET /emergency/nfc/{id}` and the
    register response return `{id, nfc_uid_last4}`, never the UID;
    `POST /emergency/nfc/revoke/{token_id}` revokes by grant id. Scan
    `detail` logs `nfc_hash=<hmac16>`, never the raw UID (also closes an
    M8-adjacent leak). Alembic `f3a9d21c5e88` rewrites existing rows +
    backfills last4 + indexes `audit_logs.timestamp`; **hard-fails if
    `OTP_HMAC_KEY` is unset with rows to migrate** (a standalone
    `alembic upgrade` doesn't load `app.auth`'s fail-fast). Residual
    (documented in `auth.py` + the model + migration): a *physically
    cloned* card still works — MIFARE UIDs are readable; and the scheme's
    strength is conditional on `_OTP_HMAC_KEY` secrecy (a key+table leak
    leaves a 2³² UID space brute-forceable offline). HMAC-at-rest shrinks
    the DB-disclosure blast radius, nothing more.
  - **M7c — per-card scan-anomaly logging.** `_flag_nfc_scan_anomaly_if_needed`
    on every NFC scan (success + fail): ≥ 8 scans of one card within an
    hour → one `emergency_card_scan_anomaly` audit row (`actor="system"`),
    debounced to once/card/hour. Two `.count()` queries windowed on the new
    `audit_logs.timestamp` index — no row materialisation on the life-safety
    path. `patient_id=None` on the row when it's triggered off failed scans
    (don't correlate a probe to a patient).
  - **M7b — minimise the scan payload.** `_scoped_fields` now returns
    `age` (whole years, `_age_from_dob`, `None` for a missing/unparseable/
    future DOB) instead of the full `date_of_birth`. `full_name` is kept
    (on-scene identity confirmation). Both the QR scan and the NFC scan go
    through `_scoped_fields`, so both shapes changed. Flutter:
    `EmergencyScanResult.dateOfBirth` → `age: int?`, `emergency_scanner_screen`
    renders `scanResultAgeValue` (new l10n key, all 4 locales + regen). New
    `backend/tests/test_emergency_scan_payload.py` (3). Web has no
    emergency-scan renderer — unaffected.
  - **NOT done:** the default `valid_minutes` was deliberately left at 1yr
    per the user's selection; `register_nfc_card` / `revoke_nfc_card` still
    lack the `_require_patient_present_for_staff` facility scoping the other
    emergency endpoints have — **pre-existing**, not an M7 regression,
    flagged by the review for a follow-up (it has senior-citizen-registration
    workflow implications).
  New `backend/tests/test_emergency_nfc_hardening.py` (8). **Verified
  185/185, `check_schema` PASS, web build + oxlint + `flutter analyze` clean.**
- **M8 — clinical data written into `audit_logs.detail`.** `patients.py:524` (diagnosis
  name), `:589` (drug name), `:642` (allergen). The audit store becomes a second,
  less-controlled copy of clinical data.
  ✅ **RESOLVED 2026-09-07 (P2.6).** `add_condition` / `add_medication` /
  `add_allergy` now log the new row's `id` in `detail`, never `payload.name` /
  `payload.drug_name` / `payload.substance` — matching what the `update_*`
  endpoints already did (`detail=<record_id>`, `fields=[...]`). `add_encounter`
  likewise switched from `enc_data["facility_name"]` to `encounter.id` (the
  authoring facility is already captured as `actor_facility`). Swept
  `consultation.py` / `reception.py` / `emergency.py` / `ai_router.py` for the
  same pattern — clean (their `detail=` values are `room_id` / `queue_number` /
  `encounter_id` / `doc_type` / the NFC UID, none of which is clinical content;
  the NFC UID is a separate concern tracked under M7). New
  `backend/tests/test_audit_no_clinical_values.py` (5 tests — each add_* path
  logs the id not the value, plus a belt-and-braces "no clinical string in ANY
  `audit_logs.detail` row for the patient"). **Verified: 165/165 pass**,
  `pyflakes` clean. **M6/M7 still open.**
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

---

## Second pass (2026-09-07) — the deferred items

Full backend suite **158/158**, `npm run build` + `oxlint` clean.

### CR9 — refresh cookie `Path` broke silent refresh behind `/api` **(Medium, fixed)**
`_set_refresh_cookie` set `Path=/auth`. The browser matches `Path` against
the REQUEST URL, and the documented same-origin topology calls
`/api/auth/refresh` (nginx / the Caddy edge strip `/api` before the
backend), so the cookie was **never sent** on that path -- silent refresh
was dead and the session dropped to a full re-login every 15 minutes.
**Fix:** new `REFRESH_COOKIE_PATH` env var, **default `/`** (works in every
topology; HttpOnly + SameSite=Strict remain the CSRF defense). Narrow to
`/auth` only for a no-`/api` direct-origin deployment.

### CR10 — concurrent-tab refresh nuked every session **(Medium, fixed)**
Two tabs sharing one refresh cookie both hit 401 near access-token expiry,
both POST `/auth/refresh`; the second presents the just-rotated token and
`rotate_refresh_token` treated it as theft → `revoke_all_refresh_tokens` →
"logged out everywhere". **Fix:** `_is_concurrent_refresh_race` +
`REFRESH_REUSE_GRACE_SECONDS` (default **8**, fail-soft parse, clamped
[0,120]) -- an already-revoked token that was *rotated* (not
logged-out/compromised), whose replacement is still the live chain head AND
still un-rotated (`replaced_by_id is None`), revoked within the window,
fails only that one request; the chain is not revoked. Reuse after the
chain has moved on, or outside the window, still trips the full-revoke
compromise response.

**Residual (accepted):** if an attacker who already holds a currently-valid
refresh token wins a sub-second rotation race against the legit client, the
legit client's reuse of the old token is graced rather than alarming, and
the attacker's freshly-minted token is left unflagged. Mitigated by the
short window; a full fix needs device/fingerprint binding of the token.
Documented in `_is_concurrent_refresh_race`.

**Also fixed a pre-existing bug this exposed:** `POST /auth/refresh` called
`rotate_refresh_token` (mints row A, the rotation) *and then*
`_issue_login_response` minted a SECOND fresh row B, handed the client B,
and left A as a live, un-revoked orphan the client never saw -- one leaked
30-day token per refresh, forever, and a `replaced_by_id` chain that didn't
match the client's actual token sequence. `_issue_login_response` now takes
an optional `refresh_plaintext` so the refresh path reuses the token
rotation already minted; the login paths are unchanged.

`test_refresh_tokens.py`: graced-race test, chain-moved-on-still-revokes
test, outside-window-still-revokes test.

### CR11 — duplication extraction **(low, done — mechanical)**
Antigravity delegation was **blocked on a missing `write_file` permission**
(no `--yolo` was passed -- correct for a cross-cutting refactor), so this
was done directly using agy's recon digest.
- Backend: `app/directory.py::resolve_user_names(db, ids)` replaces four
  byte-identical "resolve user ids → names" loops in `admin.py` (×3) +
  `pharmacy.py`.
- Web: `src/lib/format.js` (`formatDateTime` / `formatTime`, was in 5
  files), `src/lib/upload.js` (`validateImageFile` + `MAX_IMAGE_BYTES`, was
  in 2), `src/lib/image.js` (`dataUrlToPngBlob`, moved out of
  `SignaturePad.jsx` so that file exports only a component -- clears the
  oxlint `only-export-components` warning).

### CR12 — auth test coverage gaps **(done)**
- `test_password_change_lifecycle.py` (2): an access token issued before a
  password change is 401 afterwards (the `pwd_changed_at` watermark);
  `must_change_password` actually 403s protected endpoints while
  `/auth/me` + `/auth/change-password` stay reachable.
- `test_otp_reset_step2.py` (4): `POST /auth/reset-password-with-otp`
  (bug history: commit 873595c) -- successful reset changes the password +
  burns the OTP, 5 wrong guesses invalidate the live OTP, an expired OTP
  is rejected + cleared, unknown-NRIC vs wrong-code responses are
  byte-identical.

### Lint cleanups
`Login.jsx` unused catch binding → bare `catch {`; `display.get_display_feed`
now carries a one-line comment explaining the deliberate no-`response_model`
(public flat screen feed). `models.py` unused `text` import + `main.py:59`
unused `models` import were removed in the first pass.

### Post-review verification pass (independent second-model review of `f457d78..1c41cab`)
An independent security review of the CR9–CR12 diff confirmed the global 500
handler and the `list_appointments` gate are sound (no leak / no bypass) and
raised follow-ups, now applied:
- grace window default 15→8s, fail-soft env parse + clamp, `_is_concurrent_
  refresh_race` tightened with the "replacement is still un-rotated" clause;
- `row.user is None` guard in the reuse-of-revoked branch (orphaned token →
  was a possible 500);
- stale "never read at auth time" comment on `RefreshToken.replaced_by_id`
  corrected;
- the double-issue orphaned-token bug above.
`REFRESH_COOKIE_PATH` default `/` kept (reviewer confirmed it is not a CSRF
regression given HttpOnly + SameSite=Strict + Secure; `/api/auth` is not a
valid universal default because the direct-origin topology needs `/auth`).

---

## Third pass (2026-09-07) — closing the "still open" items

Full backend suite **159/159**, `npm run build` + `oxlint` clean (oxlint now
**0 warnings**).

### LDAP facility-admin → admin-role mapping — **decided + fixed**
Made the secure call: `_check_mapping_authz` now blocks a facility-scoped
admin from pointing ANY LDAP role mapping at `role="admin"`. Only a
platform/bootstrap admin (no `facility` of their own) may create an
admin-granting mapping -- closing the facility-admin → platform-admin
escalation path. The normal "IT/Helpdesk AD group → admin" use is still
available, it just has to be configured by a platform admin. Reversible by
deleting the `role == "admin"` check if the University wants facility admins to
self-provision admins. `test_admin_role_mapping_requires_a_platform_admin`
replaces the old `test_admin_role_is_assignable`.

### `PatientDetail.jsx` `exhaustive-deps` — **fixed**
`refresh` and `refreshCardStatus` wrapped in `useCallback([id])`; the two
effects now list honest deps and the `eslint-disable` is gone. No render
loop -- every dep is stable (module-import getters, `useState` setters, a
`useRef`). oxlint is fully clean.

### Grace-window residual — **device binding now built**
`refresh_tokens.client_fingerprint` (migration `e7c1a9b3f2d4`, nullable) --
a sha256 of the User-Agent, captured at issue on login + every rotation.
`_is_concurrent_refresh_race` now also requires: if BOTH the token's stored
fingerprint and the reusing request's fingerprint are present, they must
match. A reuse from a different device is NOT graced → full-revoke
compromise response. Skipped (not failed-closed) when either side is NULL
(native client with no UA, pre-migration token). Every graced race still
logs a WARNING (`clarion.auth`). New
`test_reuse_from_a_different_device_is_not_graced`. Residual now: a
same-device attacker (exfiltrated the token AND runs the identical UA
string) winning a sub-second rotation race -- narrow.

### Lower-severity N+1 + pagination — **fixed**
- `_serialize_inventory_item` gained an optional `pending_delete_ids` set;
  `list_inventory` (admin) + both pharmacy inventory lists now batch that
  lookup once (`_pending_delete_item_ids`) instead of per row.
- `_serialize_admission` takes prebuilt `{id: row}` maps; `list_admissions`
  batch-loads patients/wards/floors (3 queries total, was 3 per row).
- `staff.batch_clock_status` -- `list_staff_roster` derives clock status in
  2 queries total instead of 2 per roster row.
- `GET /patients/{id}/audit-log` and `/annotations` gained `skip`/`limit`
  (default 500, max 2000) -- generous enough that the current "fetch all"
  web client is unaffected, but the unbounded growth is capped.

### Cross-router route-handler calls — **the fragile part fixed**
`consultation.py` was calling `reception.py`'s `claim_room` / `call_ticket` /
`cancel_ticket` **route handlers** directly as functions -- which silently
breaks the day one of those endpoints gains a new `Depends(...)`. Extracted
each body into a `_*_impl(id, db, current_user)` in `reception.py` (marked
with a note); the routes are now one-line wrappers and `consultation.py`
imports the `_impl`s, never the routes. The `_impl` logic stays covered by
the existing reception route tests. No consultation-specific test infra
exists yet -- adding it is its own small task.

### `app/inventory.py` — **extracted** (delegated to a voltagent python-pro, verified here)
The 13 medicine-inventory helpers (`save_medicine_image` + its image
consts/sniffer, `_serialize_inventory_item`, `_apply_restock`,
`_serialize_purchase_proposal`, the delete-request + count helpers, ...) moved
verbatim from `admin.py` to `app/inventory.py`; `admin.py` (2257→1937 lines)
and `pharmacy.py` both import from it now. `_require_facility` stays in
`admin.py` (generic — 30 call sites, mostly wards/rooms/staff/etc.).
`pharmacy.py` no longer imports service logic from another router. Verified:
`import app.main` OK, 4 spot-checked bodies (incl. `save_medicine_image`)
byte-identical, `pyflakes` clean, **160/160**.

### `AdminConsole.jsx` split — **done** (delegated to a voltagent react-specialist, verified here)
2447 → 42 lines; 11 files under `web/src/pages/admin/` (one per tab +
`_shared.jsx` for Section/TabBar + `occupancy.js` for the two colour helpers
genuinely shared by InventoryTab and WardsTab). `npm run build` + `oxlint`
clean, scope clean, ~39 component defs all accounted for.

### Still open — a dedicated pass
- **`reception.py`** (1.4k) into queue / stations / rooms / wards
  sub-modules — the four domains are already comment-delimited, but it holds
  the single combined `router`, the shared `_*_impl` helpers, and is imported
  by `admin.py` / `display.py` / `patients.py` / `consultation.py`, so the
  package `__init__` has to re-export carefully. Lower priority than the two
  above (it's half the size and has no cross-router *service* coupling left
  after the `_impl` extraction).

---

Full text: `scratchpad/security-audit.md`. Feeds [[Implementation Roadmap]] phase P2.
