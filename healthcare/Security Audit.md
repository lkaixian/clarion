---
title: Security Audit
type: assessment
updated: 2026-09-08
tags: [security, owasp, pdpa, audit, clarion]
---

# Security Audit

Static audit of `backend/app/` against OWASP and security
clauses. Original findings: **1 Critical · 4 High · 9 Medium · 5 Low**,
each with a `file:line` and a blocked clause.

**Status (2026-09-07): every Critical / High / Medium finding is resolved or has an
interim mitigation with the full fix scheduled.** Only the 5 Low items and documented
residuals remain. Per-finding detail below is a summary — the full implementation is in
git (search the commit log for the finding id or the `P2.x` slug) and the [[Implementation Roadmap]] changelog.

---

## Critical

### C1 — Full PHI + MyKad images sent to third-party US cloud
`ai/summarize.py:52-72` posts the whole serialised patient record to Anthropic when
`ANTHROPIC_API_KEY` is set; `ai/nric_ocr.py:122-166` sends the photographed MyKad to
Claude vision from an **unauthenticated** caller (`self_registration.py:493`);
`ai/interactions.py:194-209` sends drug names to NIH. Blocks,
(PDPA cross-border), (OWASP A10).
✅ **RESOLVED 2026-09-13 (P4.3).** Every Anthropic call site removed — `anthropic`
dropped from `requirements.txt`, `ai/_cloud_guard.py` deleted (nothing left to guard).
`ai/summarize.py` and `ai/nric_ocr.py` now call `ai/local_llm.py`, a local Ollama
server (`http://localhost:11434` by default, on-prem, opt-**out** not opt-in since
nothing leaves the machine); both degrade automatically to their existing
deterministic/Tesseract fallback if Ollama isn't running. See [[On-Prem Clinical AI]]
and `docs/deployment.md`'s "On-prem AI engine" section for the one-time `ollama pull`
host setup. NIH RxNav/DailyMed calls (`ai/interactions.py`) are a separate, narrower
dependency (drug-identity lookup, not an AI cloud API) — offline path still tracked
as P4.4.

---

## High

### H1 — Emergency endpoints bypass the role/page-permission model
`routers/emergency.py` issue/status/list_nfc/revoke mounted with no
`require_page_access`; a pharmacist/receptionist token could act on any patient's card.
Blocks, PDPA 1/3.
✅ **RESOLVED 2026-09-07 (P2.1).** All 4 endpoints now depend on
`auth.require_page_access("patients")`; `patient` role unaffected (own self-service).
New `_require_patient_present_for_staff` adds facility scoping for staff callers (active
`Admission` or open today's `QueueTicket` at the acting facility, **no admin override**,
matching `_guard_cross_facility_amend`). `POST /emergency/scan` + `/nfc/scan` left
public by design. `test_emergency_access_control.py` (9).

### H2 — No need-to-know / facility scoping on patient records
`patients.py` `list_patients()` = every patient, no scope/pagination; `get_patient_full_record`
= any staff token, any patient, full history. Coherent with CLARION's cross-hospital
premise; a gap against the tender's single-facility need-to-know model. Blocks,
PDPA 1/3, OWASP A01.
✅ **RESOLVED 2026-09-07 (P2.2, design confirmed with the user).** List vs. detail
treated differently:
- `GET /patients` **default-denies cross-facility** — scoped to patients the caller's
  facility has a real relationship to (`_facility_known_patient_ids_select`), paginated
  (`skip`/`limit`, max 200). Explicit non-blank `break_glass_reason` unlocks the full
  list, audit-logged (`list_patients_break_glass`), **no admin override**.
- `GET /patients/{id}` stays fully open (continuity-of-care / emergency-first) but logs
  a distinct `view_full_record_cross_facility` action when the caller's facility has no
  relationship to the patient.
Web `PatientList.jsx` gained a "search all facilities" override UI (reason input +
audited badge). `test_patients_facility_scoping.py` (8).

### H3 — Weak seeded credentials, no forced rotation
`seed.py` ships `admin123` etc., no `must_change_password`, committed. `MIN_PASSWORD_LENGTH=8`,
no complexity. Blocks, 10.1.5, OWASP A07.
✅ **RESOLVED 2026-09-07 (P2.3).** Memorable demo passwords gated behind `APP_ENV`/`DEMO_MODE=demo`;
outside demo mode every seeded account gets a random `auth.generate_temp_password()` +
`must_change_password=True`, printed once. `MIN_PASSWORD_LENGTH` 8→12 +
`_WEAK_PASSWORD_DENYLIST` (deliberately length+denylist over composition rules, per NIST
SP 800-63B). `test_seed_password_policy.py` (4, runs `seed.py` as a subprocess).

### H4 — No encryption at rest; SQLite; startup DDL
`sqlite:///./clarion.db`, unencrypted backups, `_migrate_lightweight()` hand-rolled
ALTER at every startup. Blocks,,.
✅ **STRUCTURALLY RESOLVED 2026-08-30 (P1.3-P1.5).** MariaDB move ([[On-Prem Architecture]]):
env-driven `DATABASE_URL`, 3 least-priv accounts, Alembic is the only schema path,
`_migrate_lightweight` deleted. **Encryption-at-rest itself = P2.7** (MariaDB encrypted
tablespaces + on-prem KMS) — still open.

---

## Medium

- **M1 — no per-IP login throttle; lapsed-lock re-lock DoS.**
  ✅ **RESOLVED 2026-09-07 (P2.4).** `POST /auth/login` → `@limiter.limit("20/minute")`
  per-IP on top of the per-account lockout. Fixed the real DoS: a lapsed lock left
  `login_failed_count` at its old value, so one wrong guess re-locked indefinitely —
  now resets to 0 the moment a lapsed lock is observed. `test_login_rate_limiting.py` (5).
- **M2 — unauthenticated OTP / self-reg endpoints `@limiter.exempt` + O(n) NRIC scan.**
  ✅ **RESOLVED 2026-09-07 (P2.4).** Per-IP limits on both OTP endpoints + self-reg
  `/start`/`/verify-otp` (10/min) + `/complete` (20/min). New indexed
  `Patient.normalized_national_id` (unique), auto-synced by a `@validates` hook;
  `_resolve_patient_by_nric` + 3 other copies of the fetch-every-patient loop
  consolidated to one indexed query. Alembic `649f25aeb36f` backfills.
- **M3 — CORS defaults to `*`.**
  ✅ **RESOLVED 2026-08-30 (P1.8).** `main.py` fails **closed**: wildcard needs an
  explicit `APP_ENV=demo` opt-in; else `allow_origins=[]` + warning. `allow_credentials`
  is `True` only with an explicit `CORS_ALLOWED_ORIGINS` allowlist (P2.5, for the
  refresh cookie — never with the wildcard).
- **M4 — 8h JWT, no revocation list, `localStorage`, watermark gap.**
  ✅ **RESOLVED 2026-09-07 (P2.5, design confirmed with the user).**
  `ACCESS_TOKEN_EXPIRE_MINUTES` 8h→15min; new `models.RefreshToken` (30-day) as an
  `HttpOnly`/`SameSite=Strict` cookie (web) or `flutter_secure_storage` field (Flutter).
  `POST /auth/refresh` rotates + treats reuse of a rotated token as compromise
  (revoke-all). Real `POST /auth/logout`. Password change revokes all refresh tokens.
  Both clients single-flight a refresh-and-retry on 401. Later hardened with
  `client_fingerprint` device binding (migration `e7c1a9b3f2d4`). Verified live
  end-to-end. **Residual:** no app-level meta-tag CSP (the P1.9 edge-proxy CSP covers
  the transport layer).
- **M5 — `POST /ai/digitise/{id}` accepts any file type, no magic-byte check, no AV.**
  ✅ **RESOLVED 2026-09-07 (P2.6).** Image-shaped uploads now go through
  `imaging.validate_image_safe_to_decode` (P1.7's format allowlist / pixel-bomb ceiling
  / frame guard) before any OCR decode; a genuine PDF is still archived with OCR
  skipped. **AV hook re-scoped, not built:** the tender assigns antivirus to PTM
  (University IT) at the host/VM level — already N/A/Contractual in [[Compliance Matrix]].
  `test_digitise_document_safety.py` (3).
- **M6 — emergency-scan audit actor is unverified free-text.**
  ✅ **RESOLVED 2026-09-07 (P2.6).** New `auth.get_optional_current_user`
  (`auto_error=False` → `User | None`; missing OR broken token → `None`, never a 401 —
  used for audit attribution only, scope stays `grant.scope`). A scan with a valid
  staff token is audited under the **real user id + role** (`detail` marked `verified`,
  typed name kept as `self_asserted=`); no/invalid token → audited exactly as before
  (`actor="emergency_responder:<name>"`, role `emergency_responder`) so every existing
  audit-trail consumer keeps working. Action strings unchanged (Flutter audit screen
  switches on them). `test_emergency_scan_audit_identity.py` (6).
- **M7 — NFC emergency cards: raw cloneable UID as key, 1-year default, always returns DOB.**
  ✅ **RESOLVED 2026-09-07 (P2.6)** — user chose HMAC-at-rest + minimise-payload +
  anomaly logging; kept the 1-yr default expiry (explicit choice).
  - **M7a:** `EmergencyToken.nfc_uid` stores `auth.hash_nfc_uid(raw)` (keyed
    HMAC-SHA256; `auth.canonical_nfc_uid` normalises first). New cleartext
    `nfc_uid_last4`; `list`/`register` return `{id, nfc_uid_last4}`; `revoke` by grant
    id. Raw UID never returned, never in an audit detail. Alembic `f3a9d21c5e88`
    (hashes existing rows, indexes `audit_logs.timestamp`, hard-fails on missing
    `OTP_HMAC_KEY`, NULLs `nfc_uid` on downgrade).
  - **M7c:** `_flag_nfc_scan_anomaly_if_needed` — ≥8 scans of one card/hour → one
    debounced `emergency_card_scan_anomaly` audit row (`actor="system"`); two `.count()`
    queries on the timestamp index. `patient_id=None` when off failed scans.
  - **M7b:** `_scoped_fields` returns `age` (`_age_from_dob`), not full DOB;
    `full_name` kept. Flutter `EmergencyScanResult.age` + `scanResultAgeValue` l10n.
  - Tests: `test_emergency_nfc_hardening.py` (9) + `test_emergency_scan_payload.py` (3).
  - **Residuals (accepted, do NOT re-flag):** a *physically cloned* card still works
    (MIFARE UIDs are readable); the scheme depends on `_OTP_HMAC_KEY` secrecy (key+table
    leak → 2³² UID space brute-forceable offline); `register_nfc_card` /
    `revoke_nfc_card` lack `_require_patient_present_for_staff` (pre-existing, has
    senior-citizen-registration workflow implications); whole-year age is coarse for
    under-2s.
- **M8 — clinical data written into `audit_logs.detail`** (diagnosis / drug / allergen).
  ✅ **RESOLVED 2026-09-07 (P2.6).** `add_condition` / `add_medication` / `add_allergy` /
  `add_encounter` log the new row's `id`, never the clinical value (matching the
  `update_*` endpoints). Swept the other routers — clean.
  `test_audit_no_clinical_values.py` (5).
- **M9 — `_migrate_lightweight()` auto-runs DDL at every startup.**
  ✅ **RESOLVED 2026-08-30 (P1.5).** Deleted; Alembic is the only schema path.
  `_ensure_schema()` auto-migrates SQLite and *verifies-or-refuses* on MariaDB;
  `db/check_schema.py` gates migration integrity.

## Append-only / integrity (P2.9, 2026-09-08)

`audit_logs` is now tamper-evident + physically append-only: a per-row keyed
hash chain (`seq` / `prev_hash` / `row_hash`, advanced in-transaction by the
single `log_access` chokepoint) plus `BEFORE UPDATE` / `BEFORE DELETE`
triggers that `SIGNAL` / `RAISE(ABORT)` for **every** account. `verify_chain`
+ `db/verify_audit_chain.py` + `GET /admin/audit/chain-status` walk it;
`db/seal_audit_day.py` writes a daily WORM anchor. Retention is now a
partition-drop DDL job (clarion_migrate), never a `DELETE`. Detail:
[[Implementation Roadmap]] P2.9 changelog. Residual: the chain's forgery
resistance rests on `SECRET_KEY` secrecy — an attacker with both the key and
write access to the raw datadir can rewrite the in-DB chain; the off-box
daily seal is the backstop for that.

---

## Low — open

- **L1 — dependencies.** `python-jose`+`ecdsa` (Minerva CVE-2024-23342, not exploitable
  on HS256); `bcrypt==4.0.1` truncates >72-byte passwords; no SCA in the pipeline
→ move off `python-jose`/`passlib`, add `pip-audit` (P2.11).
- **L2 — size-check-after-full-read** in every upload path; no ASGI body cap.
- **L3 — `bridge/nfc_bridge.py`** well-hardened; residual: any local process can
  `GET /last-scan` to read a UID (a bearer credential for `/emergency/nfc/scan`).
- **L4 — `ai/ocr.py:30-31`** persists exception text into `ClinicalDocument.raw_text`.
- **L5 — `schemas.py` `PatientProfileUpdate`** uses `extra="allow"` (every other Update
  schema uses `extra="forbid"`); safe today only because the handler filters fields.

---

## Post-audit code-review findings (2026-09-07)

Parallel-agent `/code-review` passes over the P2.1-P2.6 work + follow-ups surfaced
findings not in the original static audit. All resolved (git: *"Code-review follow-up
2026-09-07"* + later commits); one-line summaries:

- **CR1 (Critical)** — `backend/_debug_photos/` held real MyKad images + OCR'd NRIC not
  in `.gitignore`. Deleted + ignored.
- **CR2 (High)** — `GET /patients/{id}/appointments` was the one patient-scoped router
  not under `require_page_access`. Gated + role-restricted + cross-facility audit action.
  `test_appointments_access_control.py` (7).
- **CR3 (High)** — blocking OCR (Tesseract / sync Anthropic) inline in the event loop on
  public endpoints → `run_in_threadpool` + `asyncio.gather`.
- **CR4 (High)** — interaction-check re-normalised every drug via RxNorm with a fresh
  client per call → 1h TTL cache + one pooled `httpx` client.
- **CR5 (High)** — `b7f1c0d94a2e` dropped the `*_path` columns with no enforced
  prerequisite → aborts unless the blob-move script has run;
  `CLARION_FORCE_DROP_LEGACY_PATH_COLUMNS=1` override + `migrate` compose service + runbook.
- **CR6 (Medium)** — missing `patient_id` / facility / `(facility_name, queue_date)`
  indexes (`d5e8a1c4b6f2`); `_serialize_patient` de-N+1'd; `list_patients` scope pushed
  into one SQL `UNION`.
- **CR7 (Medium)** — app-wide 500 handler with correlation id + logging on previously
  swallowed ObjectStore-failure paths. (Structured logging / metrics = P5.1.)
- **CR8 (Low)** — dropped unused `argon2-cffi*`; `pytest` → `requirements-dev.txt`.
- **CR9 (Medium)** — refresh cookie `Path=/auth` was never sent on the `/api/auth/refresh`
  proxy path → silent-refresh dead → re-login every 15 min. New `REFRESH_COOKIE_PATH`,
  default `/`.
- **CR10 (Medium)** — concurrent browser tabs racing `/auth/refresh` nuked every
  session → `_is_concurrent_refresh_race` + `REFRESH_REUSE_GRACE_SECONDS` (default 8).
  Also fixed a pre-existing double-issue orphaned-token bug. **Residual:** a same-device
  attacker (exfiltrated token + identical UA) winning a sub-second rotation race —
  narrow after the `client_fingerprint` device binding.
- **CR11 (Low)** — duplication extracted: `backend/app/directory.py`,
  `web/src/lib/{format,upload,image}.js`.
- **CR12** — auth test-coverage gaps closed: `test_password_change_lifecycle.py` (2),
  `test_otp_reset_step2.py` (4).
- **LDAP facility-admin → admin-role escalation** — `_check_mapping_authz`: only a
  platform admin (no facility) may create an admin-granting LDAP mapping. Reversible.
- **God-file splits** — `AdminConsole.jsx` → `web/src/pages/admin/*`; `admin.py` →
  `app/inventory.py`; `reception.py` → `app/routers/reception/` package;
  `consultation.py` stopped calling `reception.py` route handlers as functions
  (`_*_impl` helpers). All delegated to voltagent + Claude-verified + parallel-agent
  reviewed.
- **Lower-sev N+1 + pagination** — `_serialize_inventory_item` / `_serialize_admission` /
  `list_staff_roster` batch their per-row lookups; audit-log + annotations endpoints
  gained `skip`/`limit`.

---

## Checked — clean

No SQL injection. JWT algorithm pinned, no hardcoded secret fallback, role re-resolved
live from DB. OTP reset soundly built — 6-digit keyed HMAC-SHA256 at rest,
`hmac.compare_digest`, 5 attempts then invalidated, 3 req/15 min, 10-min expiry, generic
responses. File store/serve paths always built server-side from row id +
`os.path.basename`. admin/pharmacy/reception/consultation routers tenant-isolated with
non-leaking scoped-404s. Cross-facility record immutability + emergency
annotation-suppression gate are coherent and fail-closed on NULL author.
`routers/display.py` — 128-bit token, per-token rate limit, masked names by default.

---

Feeds [[Implementation Roadmap]] phase P2.
