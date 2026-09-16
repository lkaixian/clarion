---
title: Security & Stability Test Suite
type: test-plan
updated: 2026-09-16
tags: [security, testing, qa, infrastructure, clarion, campus]
---

# Security & Stability Test Suite — CLARION

**Black-box suite derived from documentation only** — [[CLARION HealthCare|this vault]]
([[Security Audit]], [[Implementation Roadmap]] progress log, [[On-Prem Architecture]],
[[Malaysia Health Regulation]]) + `AGENTS.md`. No source
code was read to author it: every case tests *observable behaviour against the stated
design*, so it stays valid across the mandated PHP/CI4 port ([[Designing for the PHP Port]]).

- **209 test cases** — 137 security, 72 infrastructure-stability
- **58 Critical · 106 High · 44 Medium · 1 Low**
- 67 cases name existing pytest files as prior art (re-run, don't reinvent);
  the rest are new coverage or operational drills that unit tests cannot express.
- Machine-readable export: `healthcare/testcases-security-stability.csv` (same data).

## Conventions

| Field | Meaning |
|---|---|
| Type | `negative` = attack/rejection probe · `regression` = re-prove a specific fixed bug stays fixed · `resilience` = break a dependency, assert graceful degradation · `positive` = required behaviour exists · `audit` = inspect config/artifacts/state · `load` = drive traffic · `manual`-drill = operator procedure |
| Priority | Critical = blocks go-live / reopens an audit Critical-High · High = required for tender security clauses · Medium = hardening/verification · Low = housekeeping |
| Refs | `SA-*` = [[Security Audit]] finding · `P*.*` = roadmap item · `CR*` = post-audit code-review finding · `` = clause |

## Method

Cases are written against the **running stack**, not the code:

- API/HTTP level: `TestClient`/curl against the composed stack (MariaDB profile where pooling matters, SQLite demo topology where the 4-gunicorn-on-one-file race is the subject).
- Edge/network level: real `docker compose` topology — port scans, XFF spoofing, TLS probes (`testssl.sh`), container-to-container reachability.
- Infra level: actually stop containers (`redis`, `minio`, `orthanc`, `mariadb`), run backups/restores, drive Alembic, watch Prometheus/Alertmanager fire.
- Protocol level: real sockets for HL7/MLLP, real `mc`/`restic`/`age` CLIs, real printers or documented mocks.
- Where a finding's own fix note says "not container-tested / live check owed" (P2.7, P2.8, P2.9-MariaDB, P5.1 edge block, MinIO repoint), that owed verification **is** a test case here.

## Summary matrix

| Group | Area | Cases | Critical | High | Med | Low |
|---|---|---|---|---|---|---|
| **A** — Authentication & session | Security | 30 | 10 | 17 | 3 | 0 |
| **B** — Authorization & RBAC | Security | 18 | 5 | 10 | 3 | 0 |
| **C** — Facility scoping (need-to-know) | Security | 10 | 5 | 3 | 2 | 0 |
| **D** — Injection & input handling | Security | 15 | 4 | 8 | 3 | 0 |
| **E** — PHI, PDPA & sovereignty | Security | 14 | 5 | 7 | 2 | 0 |
| **F** — Cryptography & secrets | Security | 10 | 6 | 3 | 1 | 0 |
| **G** — Uploads & object store | Security | 10 | 1 | 5 | 4 | 0 |
| **H** — Edge, transport & headers | Security | 10 | 5 | 4 | 1 | 0 |
| **I** — Rate limiting, lockout & DoS | Security | 9 | 3 | 5 | 1 | 0 |
| **J** — Audit trail & tamper evidence | Security | 11 | 3 | 6 | 2 | 0 |
| **K** — Bootstrap & compose integrity | Infrastructure | 9 | 3 | 4 | 2 | 0 |
| **L** — Migration & schema integrity | Infrastructure | 9 | 2 | 4 | 3 | 0 |
| **M** — Database operations & pooling | Infrastructure | 4 | 0 | 4 | 0 | 0 |
| **N** — Object store & PACS | Infrastructure | 6 | 2 | 2 | 2 | 0 |
| **O** — Observability & alerting | Infrastructure | 9 | 1 | 5 | 3 | 0 |
| **P** — Backup & disaster recovery | Infrastructure | 7 | 1 | 4 | 2 | 0 |
| **Q** — Integration resilience (HL7, registries, NIH, LDAP, printers) | Infrastructure | 8 | 1 | 5 | 2 | 0 |
| **R** — Two-campus rollout & WAN resilience | Infrastructure | 7 | 1 | 4 | 2 | 0 |
| **S** — Load, soak & resource ceilings | Infrastructure | 6 | 0 | 3 | 3 | 0 |
| **T** — CI & supply chain | Infrastructure | 7 | 0 | 3 | 3 | 1 |

---

## Traceability: Security Audit findings → cases

| **Finding** | Cases |
|---|---|
| **C1** | S-E-001, S-E-002, S-E-003, S-E-014, S-D-015, I-Q-006 |
| **H1** | S-B-002, S-B-003, S-B-004, S-I-007 |
| **H2** | S-C-001, S-C-002, S-C-003, S-C-004, S-C-005, S-C-006, S-C-007, S-C-008, S-C-009, S-C-010 |
| **H3** | S-A-001, S-A-002, S-A-003, S-A-004, S-A-005, S-A-018, S-A-019, S-A-020 |
| **H4** | S-F-004, S-F-005, S-F-006, I-K-005, I-M-001–I-M-004 |
| **M1** | S-A-017, S-I-001, S-I-002, S-I-004 |
| **M2** | S-A-018, S-I-003, S-C-009 |
| **M3** | S-H-007 |
| **M4** | S-A-006–S-A-013, S-H-003 |
| **M5** | S-G-002, S-G-003, S-G-004, S-G-005 |
| **M6** | S-B-004, S-J-010 |
| **M7** | S-B-004, S-E-011, S-F-009, S-I-006, S-I-007 |
| **M8** | S-E-010, S-E-013 |
| **M9** | I-K-005, I-L-001, I-T-001 |
| **L1** | S-A-005, I-T-003 |
| **L2** | S-G-001, S-H-010 |
| **L3** | I-Q-008 |
| **L4** | S-E-004 |
| **L5** | S-D-012 |
| **L6** | S-B-010 |
| **CR1** | S-F-009 |
| **CR2** | S-B-005 |
| **CR3** | S-I-008 |
| **CR4** | I-Q-005 |
| **CR5** | I-L-002, I-L-005 |
| **CR7** | S-J-011 |
| **CR9** | S-A-010 |
| **CR10** | S-A-009, S-A-011 |

(Clause map: ``→S-A–S-J · ``→S-D/S-F/I-T · ``/``→I-Q · ``→I-K/L/M/P · ``→S-G · `–17`→S-E-001–S-E-014, I-Q-006.)

---

## Test cases

> [!note] Run history
> **2026-09-16** — first execution on a Windows host without Docker: 117 PASS (34 live + 83 via pytest),
> 20 PARTIAL, 1 FAIL (CI bandit gate drift), 70 blocked pending a composed stack. Details + 6 new findings:
> [[Test Suite Run Report 2026-09-16]]. Status per case: CSV columns `run_status_2026-09-16` / `run_evidence`.

## S-A. Authentication & session  (Security)

### S-A-001 — Minimum password length enforced (12)
**High** · negative · refs: SA-H3; P2.3;

- **Precondition:** Staff signup/password-change form open
- **Steps:** 1) Set a 11-char password; submit
- **Expected:** 422 reject with policy message; password never stored
- **Existing coverage:** test_seed_password_policy.py

### S-A-002 — Weak-password denylist rejects common values
**High** · negative · refs: SA-H3; P2.3

- **Precondition:** Policy active (len>=12 passes)
- **Steps:** 1) Submit 'password123456', 'administrator1', sequential/repeat patterns
- **Expected:** 422 reject via _WEAK_PASSWORD_DENYLIST, regardless of length

### S-A-003 — Non-demo seeding: random temp passwords + forced rotation
**Critical** · regression · refs: SA-H3; P2.3

- **Precondition:** APP_ENV/DEMO_MODE NOT demo
- **Steps:** 1) Run seed.py as a subprocess; inspect emitted credentials; log in as seeded admin
- **Expected:** Every seeded account gets a random generate_temp_password + must_change_password=True; first login forces change; password printed once

### S-A-004 — Demo seeding only under explicit demo flag
**Medium** · positive · refs: P2.3

- **Precondition:** APP_ENV=demo / DEMO_MODE=demo
- **Steps:** 1) Run seed.py
- **Expected:** Memorable demo passwords allowed; label/banner marks demo mode

### S-A-005 — bcrypt 72-byte truncation probe (L1)
**Medium** · negative · refs: SA-L1

- **Precondition:** bcrypt==4.0.1 stack
- **Steps:** 1) Create password A of 80 chars; attempt password B sharing A's first 72 bytes
- **Expected:** Documented behaviour: pass with no false auth (B must NOT log in as A) — if it does, finding confirmed; track against L1 remediation (move off python-jose/passlib/bcrypt)

### S-A-006 — Access token expiry = 15 min
**High** · regression · refs: SA-M4; P2.5

- **Precondition:** Valid login
- **Steps:** 1) Wait/pastiche expiry (decode JWT exp); call an API with the stale token
- **Expected:** 401 after exp; exp claim ≈ 15 min from issue, not 8 h

### S-A-007 — Refresh rotation: old refresh token rejected
**Critical** · negative · refs: P2.5; SA-M4

- **Precondition:** Refresh obtained
- **Steps:** 1) POST /auth/refresh; then reuse the FIRST (now rotated) token
- **Expected:** Second use refused; treated as compromise — every family/session revoked

### S-A-008 — Concurrent-tab refresh does not nuke sessions
**High** · regression · refs: CR10

- **Precondition:** Two tabs, same device, near-simultaneous expiry
- **Steps:** 1) Fire /auth/refresh from both within REFRESH_REUSE_GRACE_SECONDS (8s default)
- **Expected:** One rotation wins; both tabs continue with new tokens; no forced re-login; race outside grace still triggers revoke-all

### S-A-009 — Refresh cookie flags: HttpOnly/Secure/SameSite=Strict/Path=/
**Critical** · negative · refs: P2.5; CR9; SA-M4

- **Precondition:** Web login over HTTPS
- **Steps:** 1) Inspect Set-Cookie for refresh
- **Expected:** HttpOnly; Secure; SameSite=Strict; Path=/ (must be sent on /api/auth/refresh — CR9 regression)

### S-A-010 — Refresh token device binding (client_fingerprint)
**High** · negative · refs: CR10 follow-up; migration e7c1a9b3f2d4

- **Precondition:** Refresh token stolen from browser storage
- **Steps:** 1) Replay it from a different UA/device fingerprint
- **Expected:** Refused; alert/revoke path per compromise policy

### S-A-011 — Real logout revokes + clears cookie
**High** · positive · refs: P2.5

- **Precondition:** Logged-in session
- **Steps:** 1) POST /auth/logout; then try /auth/refresh and an API call
- **Expected:** Refresh token revoked server-side; cookie cleared; access token unusable after expiry

### S-A-012 — Password change revokes every refresh token
**High** · regression · refs: P2.5

- **Precondition:** Sessions on 2 devices
- **Steps:** 1) Change password; attempt refresh on both
- **Expected:** All refresh tokens revoked; both devices must re-authenticate; old access token dead (pwd_changed_at check)

### S-A-013 — JWT alg pinned — 'none'/confusion rejected
**Critical** · negative · refs: SA audit 'Checked-clean';

- **Precondition:** Own valid token
- **Steps:** 1) Forge token with alg:none and with a public-key confusion variant; send
- **Expected:** 401 both; library never accepts attacker-chosen alg

### S-A-014 — JWT tamper → 401
**Critical** · negative · refs:

- **Precondition:** Own valid token
- **Steps:** 1) Flip role/facility/sub claim bytes; send
- **Expected:** 401 signature failure; no partial trust

### S-A-015 — Empty SECRET_KEY refuses to start
**Critical** · resilience · refs: P2.9 review hardening

- **Precondition:** SECRET_KEY unset/empty
- **Steps:** 1) Boot backend
- **Expected:** Process exits fail-closed; no implicit default secret

### S-A-016 — Role re-resolved live from DB
**High** · negative · refs: SA audit 'Checked-clean'

- **Precondition:** Clinician logged in; admin demotes/deactivates the account mid-session
- **Steps:** 1) Next API call with the still-valid 15-min token
- **Expected:** New/absent role applied immediately — stale JWT claims do not extend privilege

### S-A-017 — Account lockout + lapsed-lock re-lock DoS fixed
**High** · regression · refs: SA-M1; P2.4

- **Precondition:** Account locked after N failures
- **Steps:** 1) Wait for lock to lapse; make exactly ONE wrong guess
- **Expected:** Not locked out again indefinitely — failed counter resets to 0 at lapsed-lock observation; correct password works

### S-A-018 — OTP reset: at-rest HMAC, 5 tries, 3 req/15min, 10-min expiry, generic responses
**Critical** · regression · refs: SA audit 'Checked-clean'; M2; P2.4

- **Precondition:** Self-service reset flow
- **Steps:** 1) Brute-force code >5; request >3 in 15 min; replay after 10 min; probe with unknown NRIC
- **Expected:** Codes stored as 6-digit keyed HMAC-SHA256 (never plaintext); flow invalidates after 5; per-IP limit 429s; expiry honoured; responses identical for known/unknown subject (no enumeration)

### S-A-019 — Login response identical for existing vs non-existing user
**High** · negative · refs: SA-H3 family;

- **Precondition:** —
- **Steps:** 1) Wrong password for a real user vs a fake user; diff body + timing samples
- **Expected:** Same message, same status, no distinguishable timing gap

### S-A-020 — must_change_password gates the API
**High** · negative · refs: P2.3

- **Precondition:** Fresh non-demo seeded account logged in
- **Steps:** 1) Hit clinical/admin endpoints before changing password
- **Expected:** 403 (or equivalent) on everything except password change

### S-A-021 — LDAP: empty-password bind rejected pre-bind
**Critical** · negative · refs: P1.10 voltagent guard

- **Precondition:** LDAP_ENABLED, reachable server
- **Steps:** 1) POST /auth/login username=x password=""
- **Expected:** Rejected before any directory bind — anonymous-bind bypass impossible

### S-A-022 — LDAP filter injection escaped
**Critical** · negative · refs: P1.10

- **Precondition:** —
- **Steps:** 1) Logins like `*)) (uid=*)`, `admin)(; 2) (password=*`
- **Expected:** Escape applied; no auth bypass, no filter widening; normal failure only

### S-A-023 — LDAP TLS cert validation REQUIRED
**Critical** · negative · refs: P1.10 H3 (ldap3 CERT_NONE default)

- **Precondition:** Server with self-signed / untrusted cert; LDAP_CA_CERT_FILE unset or wrong
- **Steps:** 1) Bind attempt
- **Expected:** Refused (explicit CERT_REQUIRED); never silent validate=NONE

### S-A-024 — LDAP plaintext bind fail-closed
**High** · regression · refs: P1.10 M3

- **Precondition:** Config points at ldap:// without TLS
- **Steps:** 1) Login attempt
- **Expected:** Fails closed unless LDAP_ALLOW_INSECURE_BIND explicitly true; loud startup validation otherwise

### S-A-025 — LDAP directory outage = 'wrong password', app stays up
**High** · resilience · refs: P1.10

- **Precondition:** Stop AD/LDAP server
- **Steps:** 1) Local and LDAP logins; /healthz
- **Expected:** LDAP users get generic auth failure (500 never leaks); LOCAL accounts unaffected; healthz 200

### S-A-026 — LDAP JIT provision keyed on raw login string
**High** · regression · refs: P1.10 C1 fix (User.ldap_username)

- **Precondition:** Search filter on sAMAccountName (no mail attr)
- **Steps:** 1) First login then re-login; then revoke group membership
- **Expected:** Provisioning + re-login + resync all work with non-mail filters; identity = ldap_username, not email

### S-A-027 — LDAP group revocation resyncs role on next login
**High** · negative · refs: P1.10

- **Precondition:** User mapped to clinician via AD group
- **Steps:** 1) Remove group in AD; user logs in; call clinician endpoints
- **Expected:** Role downgraded/denied on re-login (resync every login); no residual privilege

### S-A-028 — Unmapped LDAP user denied — no default role
**High** · negative · refs: P1.10

- **Precondition:** Valid AD creds, no LdapRoleMapping match
- **Steps:** 1) Login
- **Expected:** Denied; never a silently defaulted role

### S-A-029 — LDAP failures feed the same per-account lockout
**Medium** · positive · refs: P1.10

- **Precondition:** LDAP user
- **Steps:** 1) Bad-password 20x
- **Expected:** Same lockout curve as local accounts; per-account DoS guard intact

### S-A-030 — LDAP concurrency semaphore holds under flood
**High** · resilience · refs: P1.10 H1

- **Precondition:** —
- **Steps:** 1) 100 parallel /auth/login LDAP attempts
- **Expected:** Semaphore gates upstream binds; app responsive; excess queued/rejected 429 — no thread exhaustion

## S-B. Authorization & RBAC  (Security)

### S-B-001 — Full endpoint × role matrix vs page-access model
**Critical** · negative · refs:; SA-H1/H2; P1.12

- **Precondition:** openapi.json reachable in test env
- **Steps:** 1) Enumerate every route × every role token; call unauthenticated
- **Expected:** Every non-public route 401/403 for the roles the model denies; matrix equals documented role map; zero 200 surprises

### S-B-002 — Emergency issue/status/list/revoke require patients page access
**Critical** · regression · refs: SA-H1; P2.1

- **Precondition:** Pharmacist + receptionist tokens (no patients page access)
- **Steps:** 1) Call all 4 endpoints
- **Expected:** 403 + audit; clinician/admin/records roles pass; patient role keeps own self-service
- **Existing coverage:** test_emergency_access_control.py

### S-B-003 — Staff emergency actions need patient PRESENT at acting facility
**Critical** · negative · refs: P2.1

- **Precondition:** Staff token; patient has no active Admission/queue ticket today at my facility
- **Steps:** 1) Issue/status/revoke against that patient
- **Expected:** Denied; NO admin-override path exists; with active admission at my facility → allowed
- **Existing coverage:** test_emergency_access_control.py

### S-B-004 — /emergency/scan + /nfc/scan public by design — minimal payload
**High** · positive · refs: P2.1; SA-M7

- **Precondition:** No token
- **Steps:** 1) Scan valid QR/NFC
- **Expected:** 200 but ONLY critical fields: blood type, allergies, active meds/conditions, AGE not DOB, name; sharing-bypass respected

### S-B-005 — GET /patients/{id}/appointments gated (CR2)
**High** · regression · refs: CR2

- **Precondition:** Low-priv token
- **Steps:** 1) Call for own-facility and other-facility patient
- **Expected:** Denied for under-privileged roles; cross-facility attempt audited
- **Existing coverage:** test_appointments_access_control.py

### S-B-006 — 'patient' not in assignable role set
**High** · negative · refs: P1.10 M1

- **Precondition:** Admin role-assign UI/API
- **Steps:** 1) Try assign role=patient via staff-role endpoints and via LDAP mapping
- **Expected:** 422/403; patient role only via self-registration paths

### S-B-007 — Facility admin cannot create admin-granting LDAP mappings
**Critical** · negative · refs: P1.10; LDAP escalation fix

- **Precondition:** Facility-scoped admin token
- **Steps:** 1) POST /admin/ldap-role-mappings mapping a group → admin
- **Expected:** Refused — only a platform admin (no facility) may; reversible check for non-admin roles allowed

### S-B-008 — LDAP mapping CRUD restricted to acting admin's own facility
**High** · regression · refs: P1.10 H3

- **Precondition:** Facility A admin
- **Steps:** 1) PUT/DELETE mappings carrying facility=B; read others'
- **Expected:** 404/403; own-facility CRUD works
- **Existing coverage:** test_admin_ldap_role_mappings.py

### S-B-009 — Security-alert ack/resolve/explain facility-scoped → 404
**High** · regression · refs: P4.5 fix #4

- **Precondition:** Facility A admin; alert id from facility B (shared screenshot scenario)
- **Steps:** 1) POST acknowledge / resolve / explain
- **Expected:** 404 not 403 (existence not confirmed); facility-matching alert succeeds
- **Existing coverage:** test_admin_security_alerts.py

### S-B-010 — Data-quality alert ack/resolve facility-scoped → 404 (L6)
**High** · regression · refs: SA-L6 fix

- **Precondition:** Facility A admin; facility B alert id
- **Steps:** 1) acknowledge / resolve
- **Expected:** 404; same shape as P4.5; break-glass with reason audited where designed
- **Existing coverage:** test_data_quality.py

### S-B-011 — PDPA DSR detail/export/consent read+write facility-scoped
**High** · negative · refs: P2.10 voltagent M2/M3/H1

- **Precondition:** RO/admin of facility A
- **Steps:** 1) GET detail + POST export of facility B's DSR; staff export not assigned-to-self
- **Expected:** Denied without break_glass_reason; export requires assigned-to-self + in_progress; every view audited (get_request/view_consent_ledger log_access)
- **Existing coverage:** test_pdpa.py

### S-B-012 — Retention + DPO config are platform-admin-only
**Medium** · negative · refs: P2.10 M4

- **Precondition:** Facility admin token
- **Steps:** 1) PUT /admin/retention-policies; POST /admin/retention/scan
- **Expected:** 403; platform admin succeeds

### S-B-013 — Reporting & predictive endpoints: server-side facility scope only
**High** · negative · refs: P4.6; P3.6

- **Precondition:** Clinician token
- **Steps:** 1) Call /reports/predictive/* incl. forged ?facility_name= / body facility
- **Expected:** Client-supplied facility parameter ignored or rejected; results bounded to caller's facility cohort
- **Existing coverage:** test_predictive_analytics.py

### S-B-014 — FHIR façade is read-only + inherits patients read policy
**High** · negative · refs: P4.1/P4.2

- **Precondition:** Any token incl. admin
- **Steps:** 1) POST/PUT/DELETE /fhir/*; cross-facility Patient read
- **Expected:** Writes never permitted (405/404); reads follow P2.2 policy incl. audit action
- **Existing coverage:** fhir test file from P4.1+P4.2 landing

### S-B-015 — Display/TV token endpoints hardened
**Medium** · positive · refs: SA checked-clean (display.py)

- **Precondition:** —
- **Steps:** 1) Fetch queue display; try without token; try token replay beyond rate
- **Expected:** 128-bit tokens; per-token rate limit; patient NAMES masked by default

### S-B-016 — PACS/DICOM boundary: auth + facility scope in front of Orthanc
**Critical** · negative · refs: P4.7

- **Precondition:** Unauth + wrong-facility tokens
- **Steps:** 1) GET study metadata/frames via backend routes; try direct Orthanc port externally
- **Expected:** 401/404 via app; Orthanc never reachable off the internal network; only its compose creds work against it
- **Existing coverage:** P4.7 tests from changelog

### S-B-017 — Ancillary sign-off roles (SIGNOFF_ROLES) enforced on analyser inbox
**High** · negative · refs: P4.8

- **Precondition:** Roles across the board
- **Steps:** 1) GET/POST /ancillary/analyser-inbox*
- **Expected:** Only sign-off roles, facility-scoped; others 403/404
- **Existing coverage:** test_ancillary_analyser_inbox.py

### S-B-018 — the University eligibility endpoint RBAC = create_patient set
**Medium** · positive · refs: P4.8 mock landing

- **Precondition:** patient/pharmacist tokens vs admin/records/clinician
- **Steps:** 1) GET /patients/campus-eligibility/{nric}
- **Expected:** Same role list as create_patient; mock always labelled "(mock campus registry — demo)" in UI
- **Existing coverage:** test_campus_registry.py

## S-C. Facility scoping (need-to-know)  (Security)

### S-C-001 — GET /patients default view = own-facility relationships only
**Critical** · regression · refs: SA-H2; P2.2

- **Precondition:** Facility A clinician token
- **Steps:** 1) List patients; search for a facility-B-only patient
- **Expected:** B patient absent entirely (not masked); pagination skip/limit max 200
- **Existing coverage:** test_patients_facility_scoping.py

### S-C-002 — Break-glass requires explicit non-blank reason + audit row
**Critical** · negative · refs: P2.2

- **Precondition:** Facility A clinician
- **Steps:** 1) List with break_glass_reason='' then with a reason
- **Expected:** Blank → cross-facility stays hidden; with reason → full list + `list_patients_break_glass` audit row; admin role gets NO silent override
- **Existing coverage:** test_patients_facility_scoping.py

### S-C-003 — Cross-facility full-record read audited, not blocked
**High** · positive · refs: P2.2 design (continuity of care)

- **Precondition:** Facility A staff, patient known only to B
- **Steps:** 1) GET /patients/{id}
- **Expected:** 200 (emergency-first design) + distinct `view_full_record_cross_facility` audit action; P4.5 scan can see the actor's fanout
- **Existing coverage:** test_auth_rbac_immutability.py family

### S-C-004 — Cross-facility clinical records immutable (amend/deny triple)
**Critical** · negative · refs: P1.12;

- **Precondition:** Same-facility-present, same-facility-absent, cross-facility patients
- **Steps:** 1) Attempt amend/update on each
- **Expected:** Cross-facility denied+audit; present-at-facility allowed; absent-at-facility still denied; NULL author fails closed
- **Existing coverage:** test_auth_rbac_immutability.py

### S-C-005 — Scoped 404 not 403 on tenant-scoped admin/pharmacy/reception/consultation reads
**High** · negative · refs: SA checked-clean

- **Precondition:** Facility A token
- **Steps:** 1) Fetch facility B ids across admin/pharmacy/reception/consultation
- **Expected:** 404 everywhere (no existence oracle); the one documented 403 family is role-level only
- **Existing coverage:** reception smoke + module tests

### S-C-006 — Unmatched HL7 results never exposed to ANY role
**High** · negative · refs: P4.8 (raw HL7 can carry a real patient name)

- **Precondition:** Ingest ORU^R01 with unknown order id
- **Steps:** 1) Query inbox as every role incl. platform admin
- **Expected:** Row staged in DB but no endpoint returns it; no admin break-glass added
- **Existing coverage:** test_hl7_listener.py

### S-C-007 — Emergency export appliance: facility registry + scoping
**Critical** · regression · refs: P5.3 voltagent High/Med

- **Precondition:** DB has two facilities; patient with identical name at both
- **Steps:** 1) build --facility Unknown / --facility A
- **Expected:** Unknown → refusal (UnknownFacilityError); A-only patients included; audit row per build (facility+count); per-patient sharing-bypass trail
- **Existing coverage:** test_emergency_export.py

### S-C-008 — NRIC resolution uses indexed normalized column — exact match only
**Medium** · negative · refs: SA-M2; P2.4 (indexed lookup replaces O(n) scan)

- **Precondition:** Patients at different facilities with near-miss NRIC punctuation
- **Steps:** 1) Resolve by NRIC variants
- **Expected:** Only normalized-exact match; no cross-facility fuzzy leak; single indexed query (no full-table scan on load)

### S-C-009 — Risk-stratification cohort = facility relationship, PII posture deliberate
**Medium** · positive · refs: P4.6 review

- **Precondition:** Facility A clinician
- **Steps:** 1) GET /reports/predictive/risk-stratification
- **Expected:** Cohort limited to A's relationship patients; names shown (clinical worklist) but RBAC + audit identical to router family
- **Existing coverage:** test_predictive_analytics.py

### S-C-010 — Sharing-bypass (opt-out) respected by every emergency reader path
**Critical** · negative · refs: P5.3 reuses _scoped_fields/_resolved_discontinued_ids

- **Precondition:** Patient with sharing bypass
- **Steps:** 1) Public scan; appliance build; offline tag content
- **Expected:** Bypassed everywhere it applies; appliance applies the same _audit_sharing_bypass_if_any trail

## S-D. Injection & input handling  (Security)

### S-D-001 — SQL injection sweep across every string filter
**Critical** · negative · refs: SA checked-clean; semgrep rule SQL-string-interp

- **Precondition:** Authenticated
- **Steps:** 1) Inject ' OR 1=1 / ; DROP / UNION payloads into search params, break-glass reason, names, filters
- **Expected:** No 500s with SQL echo, no data exfil; all queries parameterized; semgrep local rule stays zero-hit

### S-D-002 — HL7 escape/unescape round-trip on escape-shaped values
**High** · regression · refs: P4.8 voltagent #1

- **Precondition:** —
- **Steps:** 1) Feed values containing \F\ \S\ \R\ \T\ \E\ and boundary combos; encode→decode
- **Expected:** Round-trip equals input byte-for-byte (single-pass re.sub fix); no value corruption
- **Existing coverage:** test_hl7v2.py

### S-D-003 — HL7 ACK never echoes unescaped attacker control_id
**High** · regression · refs: P4.8 voltagent #2

- **Precondition:** Listener running
- **Steps:** 1) Send message with MSH-10 = '; 2) ^\E\\r' shaped payload
- **Expected:** ACK builds with control_id escaped; frame structure intact; parser of own ACK unaffected
- **Existing coverage:** test_hl7v2.py

### S-D-004 — HL7 structural injection impossible
**High** · negative · refs: P4.8 (MSH-2 hardcoded constants)

- **Precondition:** Listener running
- **Steps:** 1) Raw separators; 2) ^ & in field values
- **Expected:** Segments/fields cannot be forged; structure fixed by constants; values escaped

### S-D-005 — ESC/POS printer command injection via patient/queue text
**High** · regression · refs: P3.9 review finding

- **Precondition:** Ticket/label printer attached or mocked
- **Steps:** 1) Enqueue a patient name containing ESC/POS control bytes (0x1B...), long lines, NUL
- **Expected:** Control chars neutralized/stripped; no arbitrary printer commands (cash-drawer open, config change); label output sane
- **Existing coverage:** P3.9 fix wave

### S-D-006 — Control characters in NRIC degrade, never 500
**High** · regression · refs: P4.8 mock review (httpx.InvalidURL)

- **Precondition:** The University mock mounted
- **Steps:** 1) GET /patients/campus-eligibility/<NRIC with tab/newline/NUL>
- **Expected:** URL-quoted; response = advisory not-found {available:...}; zero 500 (contract: adapter never raises)
- **Existing coverage:** test_campus_registry.py

### S-D-007 — Stored XSS in free-text clinical fields
**Critical** · negative · refs:; CSP P1.9

- **Precondition:** Staff token
- **Steps:** 1) Store <script>, <img onerror>, svg payloads in notes/allergy/comment fields; render in web console
- **Expected:** Output escaped at render; CSP script-src 'self' blocks any inline execution as defense-in-depth; no cookie theft (refresh is HttpOnly anyway)

### S-D-008 — Path traversal / object-key validation
**Critical** · negative · refs: P1.6 sanitize_filename/validate_key; SA checked-clean

- **Precondition:** Any upload/read path
- **Steps:** 1) Keys/ids with ../../, absolute paths, NUL, encoded variants; probe every {id} with foreign object keys
- **Expected:** Server-side key construction from row id + basename only; 404/422; never reads outside bucket namespace

### S-D-009 — web entrypoint API_BASE interpolation injection
**High** · regression · refs: P1.8 F1

- **Precondition:** web container build/run
- **Steps:** 1) Feed entrypoint.sh 7 hostile inputs: `$(...)`, backticks, quotes, newline, `</script>`, `'; DROP`
- **Expected:** Validated BEFORE interpolation into the JS literal — refuse or sanitize loudly; config.js stays inert data
- **Existing coverage:** P1.8 injection guard suite (7 inputs)

### S-D-010 — CRLF/header injection via identifiers and X-Request-Id
**Medium** · negative · refs: P5.1 request-id

- **Precondition:** —
- **Steps:** 1) Send X-Request-Id with CRLF/injection; logins with CRLF in username
- **Expected:** No response-header splitting; id sanitized before echo/logging

### S-D-011 — Oversized/deeply-nested JSON and form bodies
**High** · resilience · refs: L2 residual; P1.9 L5 16MB body cap

- **Precondition:** —
- **Steps:** 1) POST 17MB body; 10k-deep nested JSON; 10k-key object
- **Expected:** 413 at edge or 4xx from app; worker memory flat; no 500 storm; edge `encode` off /api so streaming unaffected

### S-D-012 — Unknown-field posture incl. L5 residual
**Medium** · negative · refs: SA-L5

- **Precondition:** —
- **Steps:** 1) PUT /patients profile with injected role=/is_admin=/facility= unknown fields
- **Expected:** Every Update schema extra=forbid EXCEPT PatientProfileUpdate (L5: extra=allow — verify handler-side filtering means zero effect); privilege fields never settable via body

### S-D-013 — Offset-bearing client datetimes → clean 422
**Medium** · regression · refs: 2026-09-16 datetime fixes

- **Precondition:** —
- **Steps:** 1) POST appointment with `2026-01-01T00:00:00+08:00` past/future
- **Expected:** 422 with validation message — never a naive/aware TypeError 500
- **Existing coverage:** test_datetime_utc_fixes.py

### S-D-014 — Static SAST gates zero-hit
**High** · audit · refs:; P2.11

- **Precondition:** ci/run.sh available
- **Steps:** 1) Run ruff F/E9/B006, bandit -ll, semgrep ci/semgrep/clarion.yml
- **Expected:** All hard gates green: no SQL-interp, unpinned jwt.decode, shell=True, yaml.load, hardcoded secret, requests-no-timeout

### S-D-015 — SSRF guard on local-LLM URL + egress endpoints
**Critical** · negative · refs: P4.3 local_llm _is_on_prem_host;

- **Precondition:** Ollama down or attacker can influence CLARION_LOCAL_LLM_URL
- **Steps:** 1) Point LLM URL at metadata endpoint (169.254.169.254), at a public host, at internal 3306
- **Expected:** Non loopback/private/link-local refused by guard; no outbound from request-handler to attacker-chosen hosts; user-input never forms an outbound URL (only nric→quoted path on the FIXED registry base)

## S-E. PHI, PDPA & sovereignty  (Security)

### S-E-001 — AI runs with ALL external egress firewalled
**Critical** · regression · refs: SA-C1; P4.3

- **Precondition:** Ollama on-prem; iptables/netns drop every non-LAN egress from every container
- **Steps:** 1) Run summarize, MyKad OCR, CDS hint, voice→SOAP, report narrative, alert explain
- **Expected:** All features complete locally or degrade to deterministic/Tesseract fallback; tcpdump: ZERO packets off-prem
- **Existing coverage:** demo 'cable unplugged' scenario

### S-E-002 — No cloud-AI SDK can reappear
**Critical** · audit · refs: SA-C1; P0.4 lesson

- **Precondition:** Fresh checkout
- **Steps:** 1) pip deps / lockfile / SBOM scan for anthropic; 2) openai; 3) google-ai; 4) azure-ai + import grep
- **Expected:** absent; `ai/_cloud_guard.py` stays deleted; CI gate (semgrep custom rule) fails the build if a cloud-AI dep is added
- **Existing coverage:** pipeline

### S-E-003 — NIH RxNav/DailyMed egress carries drug identity ONLY
**High** · negative · refs: SA-C1 carve-out; P4.4

- **Precondition:** MITM proxy on the egress path
- **Steps:** 1) Trigger interaction screening; capture outbound queries
- **Expected:** No NRIC/patient name/facility in any outbound request; payload = drug names only; offline/cached path when NIH unreachable (P4.4 residual tracked)

### S-E-004 — MyKad images: scratch bucket 7-day expiry, never elsewhere
**High** · negative · refs: P1.6 bucket policy; P2.6 M5

- **Precondition:** Upload NRIC photo
- **Steps:** 1) Check bucket, audit detail, logs, OCR error paths
- **Expected:** Stored in clarion-scratch only; ILM 7d; not in audit_logs, not in logs; OCR failure text never persisted into raw_text (SA-L4 probe: force OCR exception, inspect ClinicalDocument.raw_text)

### S-E-005 — Consent ledger append-only, newest-wins
**High** · positive · refs: P2.10

- **Precondition:** Patient consent history
- **Steps:** 1) POST consent change; attempt UPDATE/DELETE of prior row
- **Expected:** Prior rows immutable (ledger); reads honour newest; DSR and clinical gates consult current state

### S-E-006 — DSR 'erasure' refused; access SLA 21d(+14)
**High** · regression · refs: P2.10; PDPA s.30 (Malaysia has NO erasure right)

- **Precondition:** —
- **Steps:** 1) File DSR kind=erasure; file access; request +14 extension endpoint
- **Expected:** 400 on erasure; SLA fields enforce 21-day clock; extension endpoint works; retention overrides documented
- **Existing coverage:** test_pdpa.py

### S-E-007 — DSR export = machine-readable own-record JSON
**Medium** · positive · refs: P2.10; PDPA s.43A portability

- **Precondition:** Assigned in_progress DSR
- **Steps:** 1) Staff export; subject portal export
- **Expected:** clarion-patient-record/v1 JSON; facility-scoped access; each export log_access-ed
- **Existing coverage:** test_pdpa.py

### S-E-008 — Retention scan flags — NEVER deletes
**Critical** · regression · refs: P2.10; PDPA s.10 + Act 586

- **Precondition:** Rows past retain_years
- **Steps:** 1) POST /admin/retention/scan; run db/retention_scan.py
- **Expected:** Rows land in retention_review_items; source tables byte-identical (row counts before==after); disposition audited; retain_years>=1, leap-safe math
- **Existing coverage:** test_pdpa.py

### S-E-009 — Structured logs contain zero PHI
**Critical** · negative · refs: P5.1; On-Prem Architecture 'never log PHI/OTP/token/NRIC'

- **Precondition:** LOG_FORMAT=json; full clinical session exercised (register NRIC, allergy, break-glass, DSR)
- **Steps:** 1) Grep stdout/Loki for NRIC pattern, diagnosis strings, token values, OTP digits
- **Expected:** Hits = 0; log fields = identifiers only (ids, role, facility, request_id); exception bodies never rendered to logs/response
- **Existing coverage:** P5.1 logging + correlation test

### S-E-010 — audit_logs detail never carries clinical values
**High** · regression · refs: SA-M8; P2.6

- **Precondition:** add/update condition, medication, allergy, encounter
- **Steps:** 1) Read back audit rows; regex for value strings
- **Expected:** Rows log new-row `id` only; sweep of all routers clean; data-quality alert `detail` describes shape, never raw dates/values
- **Existing coverage:** test_audit_no_clinical_values.py

### S-E-011 — Raw NFC UID appears nowhere outside its HMAC
**High** · regression · refs: SA-M7a; P2.6

- **Precondition:** Register + scan NFC card
- **Steps:** 1) Dump EmergencyToken rows, audit detail, API responses, logs
- **Expected:** Stored = hash_nfc_uid(raw) canonicalised; API exposes nfc_uid_last4 only; raw never in audit/log/response
- **Existing coverage:** test_emergency_nfc_hardening.py

### S-E-012 — AI anomaly explanation prompt leaks nothing
**Medium** · negative · refs: P4.5

- **Precondition:** Security alert exists; capture Ollama request (local proxy/log)
- **Steps:** 1) POST /admin/security-alerts/{id}/explain
- **Expected:** Prompt fields = role/facility/rule/window/counts only — never actor id, patient name or value; output framed as reference aid, not verdict
- **Existing coverage:** test_admin_security_alerts.py

### S-E-013 — WORM retention truly enforced (COMPLIANCE)
**Critical** · resilience · refs: P1.6 voltagent go-live gate;

- **Precondition:** clarion-documents / -dicom / -reports-archive provisioned with object_lock + versioning
- **Steps:** 1) As MinIO ROOT user, attempt delete + overwrite of a retained object; attempt bucket policy loosening at runtime
- **Expected:** Delete/overwrite refused until retention expiry (compliance mode); versioning keeps prior revisions; provisioning steps are a deployment gate (docs/deployment.md)
- **Existing coverage:** test_storage.py (32+) / live-MinIO smoke

### S-E-014 — Cross-border posture: nothing leaves Malaysia
**High** · audit · refs: PDPA s.129 (abolished whitelist regime); SA-C1

- **Precondition:** Network-level egress audit from call 1 of E-001
- **Steps:** 1) Enumerate every outbound destination class from the running stack
- **Expected:** Only campus-LAN + documented NIH egress for drug identity (+ NTP/DNS policy decisions recorded); no CDN/telemetry/analytics calls from web SPA
- **Existing coverage:** sources: Malaysia Health Regulation note

## S-F. Cryptography & secrets  (Security)

### S-F-001 — OTP_HMAC_KEY missing → hard fail
**Critical** · resilience · refs: SA-M7a migration f3a9d21c5e88

- **Precondition:** OTP_HMAC_KEY unset
- **Steps:** 1) Boot / run migration that hashes UIDs
- **Expected:** Hard-fails loudly; never falls back to unkeyed hash or plaintext UID

### S-F-002 — Password hashes at rest are bcrypt/argon2-class
**High** · audit · refs: SA-H3 family

- **Precondition:** DB access
- **Steps:** 1) Inspect User.password_hash
- **Expected:** Strong adaptive hash with salt; never plaintext/MD5/SHA1; argon2-cffi pin state matches requirements

### S-F-003 — MariaDB TDE active on real data
**Critical** · regression · refs: SA-H4; P2.7;

- **Precondition:** compose with encryption.cnf + generated keyfile; MariaDB 11.4
- **Steps:** 1) Create table + insert unique canary string; flush; grep raw datadir/ibd/binlog/tmp
- **Expected:** Canary NOT found in plaintext; innodb_encrypt_tables=FORCE + encrypt_binlog + encrypt_tmp_files ON in running server; ~3-10% perf delta noted
- **Existing coverage:** P2.7 was config-verified only — this is the owed live test

### S-F-004 — Keyfile gate: empty encryption dir → server won't start
**High** · resilience · refs: P2.7

- **Precondition:** Remove generated keyfile; start mariadb
- **Steps:** 1) Server refuses to start (provision-the-key gate); 0400 perms on keyfile; file never in git
- **Expected:** check .gitignore coverage

### S-F-005 — Backups age-encrypted; negative decrypt
**Critical** · regression · refs: P2.8;

- **Precondition:** backup.sh full run
- **Steps:** 1) Inspect restic repo blobs; try restore with wrong age identity
- **Expected:** Every stream age-encrypted; wrong key fails; no plaintext staging file left on age failure (check=True contract)
- **Existing coverage:** backend/backup scripts

### S-F-006 — Emergency export never writes plaintext
**Critical** · regression · refs: P5.3 review (found sound — keep it)

- **Precondition:** No recipients configured / age missing
- **Steps:** 1) Run appliance build
- **Expected:** Raises BEFORE write_bytes; only <export>.age exists; private key only on appliance
- **Existing coverage:** test_emergency_export.py

### S-F-007 — Timing-safe comparisons
**Medium** · negative · refs: SA checked-clean (OTP compare_digest); M7

- **Precondition:** —
- **Steps:** 1) Statistical timing probe on OTP/UID comparison endpoints
- **Expected:** No distinguishable early-exit timing; hmac.compare_digest in paths

### S-F-008 — TLS floor + modern-only suites at the edge
**Critical** · negative · refs: P1.9 M3 (tls1.2/1.3 pinned)

- **Precondition:** proxy up on 443
- **Steps:** 1) testssl.sh / nmap ssl-enum-ciphers
- **Expected:** TLS 1.0/1.1 + weak ciphers/renegotiation rejected; HSTS present with env max-age, NO preload (P1.9 M1 decision); strict_sni_host on; HTTP→HTTPS 308

### S-F-009 — Secrets stay out of images, env dumps, git
**Critical** · audit · refs: P1.11 (Docker secrets TODO); P5.3 anchor leak; CR1

- **Precondition:** Built stack
- **Steps:** 1) docker inspect every container's env; git status/ls-files for proxy/certs, encryption/, smtp_password, key.properties, *.db, uploads
- **Expected:** Only each service's own vars present (branch regression: NO central secrets in branch-proxy); cert/keys/SMTP password git-ignored; no committed real-PHI artifacts (CR1 class never recurs)

### S-F-010 — No credentials or tokens in URLs / referable GETs
**High** · negative · refs:

- **Precondition:** —
- **Steps:** 1) Grep access logs + code-level audit (CI) for secrets in query strings incl. Orthanc basic-auth posture
- **Expected:** Token transport = Authorization header / HttpOnly cookie only; Orthanc creds never in any URL

## S-G. Uploads & object store  (Security)

### S-G-001 — Upload size enforced BEFORE full read
**High** · regression · refs: P1.6 voltagent; SA-L2

- **Precondition:** —
- **Steps:** 1) Stream a slow 200MB upload to a doc endpoint; monitor backend RSS
- **Expected:** Reject/413 at cap with bounded memory (enforce_upload_size pre-.read()); L2 residual documented — confirm cap behaviour, not buffer-everything

### S-G-002 — Server-side MIME sniff beats declared type
**High** · negative · refs: P1.6/P2.6 M5

- **Precondition:** —
- **Steps:** 1) Upload PE/ELF/script bytes named .pdf and .jpg; upload with content-type lies
- **Expected:** Sniffed type governs; non-image/PDF rejected; exec-content never served inline

### S-G-003 — Image format allowlist incl. HEIC; TIFF excluded
**Medium** · regression · refs: P1.7 + P1.7b HEIC

- **Precondition:** —
- **Steps:** 1) Submit JPEG/PNG/GIF/WEBP/HEIC (allowed) + TIFF/BMP/raw-exotic (per allowlist)
- **Expected:** Allowlist exactly as documented; HEIC gets identical pixel-bomb/frame/concurrency guards; sniffer checks ISO-BMFF ftyp brand

### S-G-004 — Decompression-bomb: pixel ceiling + frames + concurrency gate
**Critical** · resilience · refs: P1.7; P2.6 M5

- **Precondition:** —
- **Steps:** 1) Upload 100MP-declared small file, animated 10k-frame, 24MP+ bomb; flood 50 parallel image uploads
- **Expected:** All rejected via ImageProcessingError→4xx or queued behind Semaphore(4); worker RSS/CPU bounded; no OOM kill of gunicorn
- **Existing coverage:** test_imaging.py

### S-G-005 — PDF render cost bounded + web-preview variant
**Medium** · resilience · refs: P1.7b (accepted Medium residual)

- **Precondition:** —
- **Steps:** 1) Upload pathological PDF (huge declared page size, deep XObject recursion); request ?size=1400
- **Expected:** Size cap computed from declared page size; output long-edge exact; worst-case render bounded by upload cap + concurrency gate — documented residual, confirm 504/timeout not worker death
- **Existing coverage:** test_imaging PDF cases

### S-G-006 — EXIF/GPS stripped on medicine photos in place; clinical originals untouched
**High** · regression · refs: P1.7

- **Precondition:** Photo with EXIF GPS
- **Steps:** 1) Re-upload as medicine image vs clinical doc; read stored bytes
- **Expected:** Photo: re-encoded JPEG, info.clear()'d, no EXIF/XMP/ICC-GPS; clinical doc original bytes + hash unchanged (WORM never modified); thumbnail generated separately
- **Existing coverage:** test_imaging.py

### S-G-007 — sha256 integrity verified on serve; corrupted object refused
**High** · regression · refs: P1.6 voltagent (get_checked)

- **Precondition:** Tamper stored object bytes directly in MinIO (out-of-band)
- **Steps:** 1) GET document/thumb
- **Expected:** Serve refuses / alerts on sha mismatch — silent corrupt PHI never reaches clinician
- **Existing coverage:** test_storage.py

### S-G-008 — Derived thumbnails: content-addressed, fresh on re-upload, outage-safe
**Medium** · regression · refs: P1.7 voltagent bug fix + P1.7b

- **Precondition:** Re-upload a different image under the SAME filename; stop MinIO
- **Steps:** 1) GET thumbnail each time
- **Expected:** Key folds source sha → never stale image; cache-miss regenerates; store outage → 503 clean (no 500), strong ETag/304 on hit
- **Existing coverage:** test_derived.py

### S-G-009 — Least-privilege S3 users enforced at API level
**High** · negative · refs: 2026-09-14 minio least-priv pass

- **Precondition:** Use clarion-orthanc creds directly
- **Steps:** 1) Attempt ops on clarion-documents; list outside granted bucket; clarion-backup attempt write/delete
- **Expected:** 403 per policy JSON; clarion-backend scoped to clarion-* buckets; documented residual: s3:* within its own domain pending out-of-band bucket provisioning TODO

### S-G-010 — Filename sanitization on user uploads
**Medium** · negative · refs: P1.6 sanitize_filename

- **Precondition:** —
- **Steps:** 1) Upload names: ../../etc/passwd, null byte, 300 chars, unicode homoglyphs, ;script
- **Expected:** Stored under server-generated/sanitised keys; original-name metadata only

## S-H. Edge, transport & headers  (Security)

### S-H-001 — HTTP→HTTPS 308 + HSTS
**High** · positive · refs: P1.9

- **Precondition:** proxy serving 80+443
- **Steps:** 1) curl -v http://host/
- **Expected:** 308 to https; Strict-Transport-Security with configured max-age; HSTS NOT preload-flagged (P1.9 M1 decision)

### S-H-002 — Security header set on every response
**High** · audit · refs: P1.9;

- **Precondition:** —
- **Steps:** 1) curl -I through proxy on /, /api/..., error pages
- **Expected:** CSP present; X-Frame-Options DENY; COOP/CORP/Permissions-Policy set; X-Content-Type-Options nosniff; Server token suppressed ('-Server'); headers live ONLY at the edge (single source of truth)

### S-H-003 — CSP substance: script-src 'self'; documented inline-style allowance
**Critical** · negative · refs: P1.9; SA-M4 residual

- **Precondition:** SPA loaded
- **Steps:** 1) Inject via any sink a <script> inline + external src; attempt eval; check style-src-elem/attr split (L2)
- **Expected:** script-src 'self' blocks inline/external script; style-src 'unsafe-inline' tolerated as DOCUMENTED residual pending hash/nonce tightening (P1.9 prod TODO) — record, don't fail; upgrade-insecure-requests absent by design

### S-H-004 — /api/metrics + /api/readyz blocked at edge (prefix-strip bypass)
**Critical** · regression · refs: P5.1 voltagent real bug

- **Precondition:** proxy live
- **Steps:** 1) GET /api/metrics, /api/readyz, /api/healthz and casing/path-normalisation variants (%2e, //api, /API/) through proxy; direct to backend on internal net for contrast
- **Expected:** 404 at edge for metrics/readyz (explicit @backend_diag matcher before /api/* catch-all); reachable ONLY from internal; LIVE verification is owed — this test IS that owed verification
- **Existing coverage:** Caddyfile block unverified live since landing

### S-H-005 — X-Forwarded-For spoof rejected; trust anchor exact
**Critical** · regression · refs: P1.8 F2; P1.9 FORWARDED_ALLOW_IPS anchor

- **Precondition:** Rate limit at known threshold
- **Steps:** 1) Direct to backend: forged XFF to vary the key; via proxy: legit client
- **Expected:** Direct forged XFF ignored (FORWARDED_ALLOW_IPS=172.28.0.2 only, default 127.0.0.1 elsewhere) → limiter keys on real socket IP; via proxy the proxy-set XFF is honoured; never `*`

### S-H-006 — Only the proxy publishes host ports
**Critical** · audit · refs: P1.9; On-Prem Architecture (3 networks, proxy only 443)

- **Precondition:** Full stack up
- **Steps:** 1) From host + a second machine: nmap/masscan 80,443 + attempt web:80, backend:8000, mariadb:3306, minio:9000/9001, redis:6379, orthanc:8042, hl7:2575, grafana:3000, prometheus:9090
- **Expected:** Connect succeeds ONLY to proxy 80/443 (+ any deliberately-published observability ports per profile); every data-tier port closed/filtered; web+backend are expose-only

### S-H-007 — CORS fail-closed matrix
**Critical** · regression · refs: SA-M3; P1.8 F3

- **Precondition:** Non-demo env
- **Steps:** 1) Preflight + simple request from (a) allowlisted origin, (b) random origin, (c) origin=null; toggle APP_ENV=demo wildcard attempt
- **Expected:** (a) ACAO exact + credentials true; (b) no CORS headers; (c) refused; wildcard only with explicit APP_ENV=demo AND allow_credentials=False; warning logged on fail-closed path
- **Existing coverage:** P1.8 CORS matrix + preflight E2E

### S-H-008 — Edge request hardening: header cap, timeouts, protocols
**High** · negative · refs: P1.9 M2

- **Precondition:** —
- **Steps:** 1) 200KB header; slow-loris trickle; HTTP/1.0; h2c attempt
- **Expected:** max_header_size → 431; idle/timeout limits drop; servers{} timeouts; protocols h1+h2 only; app backend unaffected by per-connection abuse

### S-H-009 — /config.js runtime API base + SPA integrity
**Medium** · positive · refs: P1.8

- **Precondition:** web container running
- **Steps:** 1) GET /config.js; load SPA; change API_BASE env → recreate
- **Expected:** config.js reflects env; load order (classic script before deferred module) intact; fallback chain window.__CLARION_API_BASE__ → VITE → localhost honoured; prod console.error on localhost fallback (F6)

### S-H-010 — Response split risk: web walled from data tier
**High** · audit · refs: P1.9 M5 residual (data tier↔backend → P1.11-rem)

- **Precondition:** —
- **Steps:** 1) From web container exec: reach mariadb:3306, minio:9000
- **Expected:** web CANNOT reach data tier (edge/internal split); backend→data reachable by design; document the known residual exactly as the vault states it

## S-I. Rate limiting, lockout & DoS  (Security)

### S-I-001 — Login limit exact across 4 gunicorn workers (shared Redis counters)
**Critical** · regression · refs: P5.2 bug (a)

- **Precondition:** MariaDB stack profile, 4 workers
- **Steps:** 1) Burst 100 wrong-password POST /auth/login from one IP
- **Expected:** Exactly 20 succeed /minute then 429 — not ~50+ via per-worker undercount; Redis is the storage
- **Existing coverage:** P5.2 verified burst pattern

### S-I-002 — Global 60/min default enforced on UNdecorated routes
**Critical** · regression · refs: P5.2 bug (b): SlowAPIMiddleware was a total no-op

- **Precondition:** —
- **Steps:** 1) 75 rapid GETs on dashboard/patients/pharmacy/reception route with no explicit decorator
- **Expected:** 60 pass then 15×429; EVERY route covered by enforce_rate_limits global dependency; decorator + exempt semantics intact

### S-I-003 — OTP / self-registration per-IP limits
**High** · regression · refs: SA-M2; P2.4

- **Precondition:** —
- **Steps:** 1) Burst OTP request endpoints + self-reg /start /verify-otp /complete
- **Expected:** 10/min and 20/min caps honoured; @limiter.exempt nowhere on unauthenticated endpoints

### S-I-004 — Redis outage degrades instead of failing closed site-wide
**Critical** · regression · refs: P5.2 voltagent CRITICAL

- **Precondition:** Stack up, traffic flowing
- **Steps:** 1) docker stop redis; hit /healthz, /readyz, POST /auth/login, /emergency/scan; restart redis
- **Expected:** All 200 (rate limiting degrades to per-worker in-memory — documented); _storage_dead clears on restart, shared counters resume; NEVER 500-on-every-request

### S-I-005 — HL7 listener hostile connection exhaustion attempt
**High** · resilience · refs: P4.8 voltagent #3

- **Precondition:** listener on 2575 (internal)
- **Steps:** 1) Open 64 sockets, send nothing; then malformed bytes; then full rate traffic
- **Expected:** ≤16 concurrent handled (semaphore, excess queues in backlog); 30s read timeout reaps idlers; accept() wrapped — transient error logs+retries, process NEVER dies

### S-I-006 — NFC scan anomaly debounce fires once
**Medium** · regression · refs: SA-M7c

- **Precondition:** Card registered
- **Steps:** 1) 8+ scans of one card in an hour
- **Expected:** Exactly one debounced emergency_card_scan_anomaly audit row (actor=system); failed scans count with patient_id=None; two indexed count queries only

### S-I-007 — Public emergency scan cannot be weaponised
**High** · negative · refs: H1 carve-out by design

- **Precondition:** No token
- **Steps:** 1) Enumerate QR ids at volume; request other-facility cards; compare payloads
- **Expected:** Randomized 128-bit-class ids → no enumeration; rate limit present (emergency endpoints exempted ONLY from fail-closed redis dependency, per P5.2 fix reasoning — confirm still limited); payload minimal (no DOB/hidden fields)

### S-I-008 — Image/OCR CPU flood against demo topology
**High** · resilience · refs: P1.7 Semaphore(4); P5.2 gunicorn --timeout 60

- **Precondition:** SQLite 4-worker demo topology
- **Steps:** 1) 50 concurrent uploads + digitise while polling /healthz
- **Expected:** Healthchecks green throughout; OCR never inline in event loop (CR3 run_in_threadpool); queue depth → 429/503, no worker SIGKILL storm

### S-I-009 — Jobs queue: single-claim under race + crashed-worker reclaim
**High** · regression · refs: P1.7b voltagent HIGH+MEDIUM

- **Precondition:** 4 processes (or spawned pollers)
- **Steps:** 1) Enqueue N thumbnail primes; kill -9 a worker mid-job; wait
- **Expected:** Atomic conditional UPDATE claim → zero double-runs on SQLite AND MariaDB; 'running' row reclaimed after 5-min staleness; queue drains; table growth documented (accepted LOW)
- **Existing coverage:** test_jobs.py

## S-J. Audit trail & tamper evidence  (Security)

### S-J-001 — Hash chain verifies intact and catches every tamper class
**Critical** · regression · refs: P2.9;

- **Precondition:** Audit activity
- **Steps:** 1) Run verify_chain happy path; then out-of-band: ALTER one row's detail; DELETE middle; truncate tail; forge mid-chain recompute
- **Expected:** verify + CLI exit 1 with location for each class; intact chain exit 0; GET /admin/audit/chain-status admin-gated
- **Existing coverage:** test_audit_hash_chain.py (18)

### S-J-002 — UPDATE/DELETE on audit_logs blocked for EVERY account
**Critical** · negative · refs: P2.9 triggers; SA-H4

- **Precondition:** As clarion_app, clarion_migrate, clarion_report, and root
- **Steps:** 1) UPDATE/DELETE audit_logs; direct INSERT attempt
- **Expected:** BEFORE UPDATE/DELETE triggers SIGNAL/RAISE(ABORT) regardless of account; app path is INSERT-only through log_access chokepoint
- **Existing coverage:** test_audit_hash_chain.py

### S-J-003 — clarion_app grants = DML-only, audit append-only
**High** · audit · refs: P1.3;

- **Precondition:** DB access
- **Steps:** 1) SHOW GRANTS for clarion_app/migrate/report/metrics
- **Expected:** app: no UPDATE/DELETE on audit_logs, no DDL; migrate: DDL deploy-time only; report: read-only; metrics: no clarion schema access; MAX_USER_CONNECTIONS set

### S-J-004 — Daily WORM seal + read-back + idempotency
**High** · regression · refs: P2.9 voltagent (write-only-seal hole)

- **Precondition:** MinIO reports-archive up
- **Steps:** 1) seal_audit_day twice; truncate the sealed object tail out-of-band; verify_chain --worm
- **Expected:** Seal idempotent; WORM readback detects tail truncation; failed mirror retried on next seal
- **Existing coverage:** test_audit_hash_chain.py

### S-J-005 — Concurrent audit appends keep chain gap-free
**High** · resilience · refs: P2.9 (4 gunicorn workers, one SQLite file; FOR UPDATE no-op)

- **Precondition:** 4 concurrent processes hammer log_access
- **Steps:** 1) verify_chain
- **Expected:** No fork/gap; flock holds on SQLite; MariaDB SELECT...FOR UPDATE path correct
- **Existing coverage:** test_audit_hash_chain.py concurrent case

### S-J-006 — audit.py fails closed on empty SECRET_KEY
**Critical** · regression · refs: P2.9 voltagent fix

- **Precondition:** SECRET_KEY=''; app running oddly anyway
- **Steps:** 1) Any audit-writing request
- **Expected:** Refuses to append with error — never writes a chain row under a default/empty key

### S-J-007 — Retention by partition DROP, never DELETE
**High** · audit · refs: P2.9 design

- **Precondition:** MariaDB with partitions
- **Steps:** 1) Run the retention DDL job on a copied partition
- **Expected:** DROP PARTITION DDL only; trigger still blocks DELETE; row counts of hot partitions unchanged
- **Existing coverage:** deployment.md cadence

### S-J-008 — Anomaly rules behave + clock-skew guard
**High** · regression · refs: P4.5 fixes #1-3

- **Precondition:** Seed audit rows
- **Steps:** 1) Actor touches 20+ distinct patients/hour; same actor at 2 facilities in one window; row with future timestamp; off-hours-only access
- **Expected:** fanout alert fires (≥20/20 = threshold); TWO alerts, correct per-facility attribution; latest clamped to now → no silent mass auto-resolve; off_hours stays info unless ≥5 same night; dedup key naive-datetime consistent (window rotation auto-resolve works)
- **Existing coverage:** test_security_analytics.py

### S-J-009 — Every designed audit read-point actually writes + correlates
**High** · audit · refs: P2.2/P2.10/P5.3 log_access obligations

- **Precondition:** Known request_id of a session
- **Steps:** 1) Perform: cross-facility view, break-glass list, DSR view/export, consent ledger view, bulk emergency export, thumbnail reads (medicine photo gap was a documented fix)
- **Expected:** Each emits its documented action row; request_id + actor + role + facility fields populated; no PHI in detail

### S-J-010 — 500 handler: correlation id, no stack trace leak
**Medium** · positive · refs: CR7; P5.1

- **Precondition:** Force a server error
- **Steps:** 1) Trigger 500 via a safe fault (bad object-store state)
- **Expected:** Body = correlation id (same as X-Request-Id) — no traceback/SQL/paths; error JSON logged with context

### S-J-011 — Accepted-residuals register (do NOT re-flag; re-verify posture only)
**Medium** · audit · refs: Security Audit residuals; MinIO CVE note; P1.7b Medium; P2.9 residual

- **Precondition:** —
- **Steps:** 1) Confirm each documented residual still matches reality: physical NFC clone works (by design); HMAC key secrecy dependency; MinIO tag predates CVE-2025-62506 (non-service-account creds → precondition absent); PDFium wall-clock residual; chain forgery vs SECRET_KEY+datadir attacker (off-box seal backstop); on-tag offline data unrevocable
- **Expected:** Posture statements still TRUE and DOCUMENTED; any drift = new finding; nothing here is a failure

## I-K. Bootstrap & compose integrity  (Infrastructure stability)

### I-K-001 — From-zero `docker compose up` on MariaDB profile boots fully
**Critical** · resilience · refs: P5.2 bugs 1-4; P1.11

- **Precondition:** Fresh volumes, complete .env from .env.docker.example
- **Steps:** 1) compose up --profile mariadb; watch every service to healthy; query backend
- **Expected:** No crash loops; migrate service completes `alembic upgrade head` (working_dir /app — silent no-op regression); mariadb accounts incl. clarion_metrics all exist (P5.2 bug-1 regression: one missing var once silently killed ALL accounts); backend /healthz 200

### I-K-002 — Second `docker compose up` after provisioning (idempotency)
**Critical** · regression · refs: 2026-09-14 minio-init voltagent bug

- **Precondition:** Stack provisioned once
- **Steps:** 1) compose down && up; repeat ×3
- **Expected:** minio-init survives `mc admin policy attach` already-attached errors (tolerates ONLY that class, still aborts on typos/perm errors) — stack NEVER wedges past the first boot; bucket ensure / account scripts idempotent on restart

### I-K-003 — `docker compose config` valid in every profile combination
**High** · regression · refs: P5.3 :?/-var bug

- **Precondition:** —
- **Steps:** 1) compose config with: no profile; mariadb; backup; observability; branch-edge (origin set/unset); all-at-once
- **Expected:** Zero parse errors; a disabled profile's required vars never break a plain up (the :- vs :? lesson); rendered env shows correct per-service creds

### I-K-004 — SQLite demo bootstrap: auto-migrate under 4-worker race
**High** · regression · refs: P1.9 _schema_lock fix

- **Precondition:** Demo topology, 4 gunicorn workers on one clarion.db
- **Steps:** 1) docker compose up (no mariadb); repeat cold starts ×10
- **Expected:** _ensure_schema upgrades head exactly once; POSIX flock prevents concurrent-migration corruption; zero 'table already exists' crashes

### I-K-005 — MariaDB startup refuses pre-Alembic / drifted DB (verify-or-refuse)
**Critical** · regression · refs: P1.5

- **Precondition:** Point DATABASE_URL at a hand-created schema (no alembic.version_info) / at an old head
- **Steps:** 1) Boot
- **Expected:** Refuses to serve (verify-or-refuse; pre-Alembic DB refused, NOT stamped); clear error; old DDL hacks (_migrate_lightweight/create_all) confirmed absent (M9 stays closed)

### I-K-006 — Backend boots on uvicorn≥0.36 (worker pin)
**High** · regression · refs: P1.9 uvicorn-worker 0.3.0→0.4.0

- **Precondition:** requirements applied
- **Steps:** 1) Boot + graceful restart
- **Expected:** No boot crash (0.3.0 died on ≥0.36 — the stack had never booted before that fix); pin documented

### I-K-007 — Healthchecks probe real endpoints
**Medium** · audit · refs: P5.1

- **Precondition:** Stack up
- **Steps:** 1) Inspect container health + docker inspect .State.Health; break DB, watch backend readyz vs healthz
- **Expected:** backend healthcheck hits plain-HTTP /healthz (P1.9 M4); /readyz 503 when DB/object-store down but /healthz stays 200

### I-K-008 — Restart / shutdown ordering + graceful drain
**High** · resilience · refs: P5.2 gunicorn tuning

- **Precondition:** Load trickling in
- **Steps:** 1) docker compose restart mariadb; SIGTERM backend mid-request
- **Expected:** depends_on ordering brings dependents up only after healthy; graceful-timeout 30 drains in-flight (no truncated uploads/audit writes); --max-requests recycling shows jitter (no synchronized restart storm)

### I-K-009 — Air-gapped deploy: offline image delivery
**Medium** · resilience · refs: P1.11 (offline bundle TODO); architecture 'nothing pulled from internet'

- **Precondition:** VM-BACKUP registry / docker-save tarball; NIC down
- **Steps:** 1) Load digest-pinned images from private registry; compose up
- **Expected:** All images resolve by DIGEST without internet; unauthenticated pull attempt from running containers = 0 (monitor DNS); private registry TLS/auth sane

## I-L. Migration & schema integrity  (Infrastructure stability)

### I-L-001 — `alembic upgrade head` on genuinely fresh MariaDB 11.4
**Critical** · regression · refs: P5.2 bug 3 (a1b2c3d4e5f6 import-time models); P2.9 leftover

- **Precondition:** Empty database + creds
- **Steps:** 1) upgrade head; check_schema
- **Expected:** Zero errors — every migration reflects the DB at its chain position, never live models; audit triggers created (log_bin_trust_function_creators, not SUPER); DATETIME(6) applied on mysql only; 57-table end state == models

### I-L-002 — Full downgrade base → upgrade head round-trip
**High** · regression · refs: P2.11 CI gate; 5e6a60dfe274 FK-safety

- **Precondition:** Migrated DB
- **Steps:** 1) downgrade base; upgrade head; check_schema
- **Expected:** No FK-order failures (downgrade FK-safe on MariaDB); final hash/counts stable; b7f1c0d94a2e refuses dropping *_path columns unless blob-move ran (CR5) — override env honoured

### I-L-003 — check_schema drift gate both engines
**High** · audit · refs: P1.5; P2.11

- **Precondition:** CI env
- **Steps:** 1) python -m db.check_schema (SQLite + MariaDB)
- **Expected:** Autogenerate vs models = 0 ops on BOTH; wired into ci/run.sh; fails loudly (this is the migration-integrity backbone for the PHP port)

### I-L-004 — Audit-chain migration: restartability + backfill correctness
**High** · regression · refs: P2.9 (inspector guards, streamed batches, trigger-drop during backfill)

- **Precondition:** Pre-P2.9 DB with rows
- **Steps:** 1) Run migration, kill mid-backfill, re-run; verify chain
- **Expected:** Resumes cleanly, chain intact over REAL pre-P2.9 rows ordered (timestamp,id); id tiebreak correct; empty table edge case OK
- **Existing coverage:** test_audit_hash_chain.py backfill case

### I-L-005 — MariaDB run of b2d7e4a9c1f6 (owed) + autogen/upgrade on real creds
**High** · regression · refs: P2.9 leftover; P1.7b note

- **Precondition:** MariaDB 11.4 with creds
- **Steps:** 1) Upgrade head incl. this revision
- **Expected:** The one never-live-run migration passes on MariaDB; PARTITION-based audit retention DDL valid; no 1419-class surprises

### I-L-006 — SQLite→MariaDB migrator: pre-flight catches, reconciliation proves
**Critical** · regression · refs: P1.4

- **Precondition:** Demo clarion.db with planted FK orphans + over-length + ci-collision + dup active claim + bad JSON
- **Steps:** 1) Run migrate_sqlite_to_mariadb.py with/without --prune-orphans; read report
- **Expected:** Every pre-flight defect named; FK-ordered copy; coercion correct; final report: counts+checksums MATCH on all 30 tables; app runs on migrated data; orphans pruned only with flag
- **Existing coverage:** P1.4 verified on real MariaDB 11.4

### I-L-007 — Alembic runs keep app.* loggers alive
**Medium** · regression · refs: P1.10 repo-wide env.py fix

- **Precondition:** LOG config active
- **Steps:** 1) alembic upgrade; observe app logs during migration
- **Expected:** disable_existing_loggers=False holds — no silent logger death during CI/migration

### I-L-008 — DATETIME(6) + TZDateTime round-trip
**Medium** · regression · refs: P1.2b; the naive-round-trip convention

- **Precondition:** Both engines
- **Steps:** 1) Write sub-second timestamps; read back; compare in Python
- **Expected:** 6-dp preserved on MariaDB; no-op on SQLite; values come back naive-UTC per documented convention — comparisons never mix naive/aware (zero TypeError paths; 2026-09-16 sweep holds)
- **Existing coverage:** test_datetime_utc_fixes.py

### I-L-009 — utf8mb4 end-to-end charset
**Medium** · positive · refs: P1.3

- **Precondition:** MariaDB profile
- **Steps:** 1) Store names/notes with emoji, BM diacritics, Chinese, RTL; read via API + reports export
- **Expected:** Round-trip byte-identical everywhere incl. search; collation-driven LIKE behaviour asserted (SQLite-ism #9)

## I-M. Database operations & pooling  (Infrastructure stability)

### I-M-001 — Pool math holds at concurrency ceiling
**High** · load · refs: P1.3/P5.2 (pool 10 + overflow 30, 4 workers, max_connections 200)

- **Precondition:** MariaDB profile; pgbouncer-less
- **Steps:** 1) Drive >160 simultaneous DB-touching requests (multi-IP or authorized bypass; single-machine limit documented)
- **Expected:** No Too-many-connections from server; overflow conns recycle; saturation → pool_timeout(10s) → clean 5xx, never hangs; max_user_connections per account respected

### I-M-002 — Dead-connection recovery (pool_pre_ping/recycle)
**High** · resilience · refs: P1.3 pool config

- **Precondition:** Idle stack past wait_timeout
- **Steps:** 1) Kill DB server-side connections / restart mariadb container; first API wave
- **Expected:** pre_ping transparently reconnects; no 500 wave; LIFO reuse normal

### I-M-003 — READ COMMITTED isolation + no audit-tip deadlock
**High** · resilience · refs: P1.3 dialect config

- **Precondition:** Concurrent audit appends + clinical writes
- **Steps:** 1) Hammer log_access + clinical endpoints in parallel
- **Expected:** No lock-waits > pool_timeout; chain tip lock never deadlocks with app traffic; READ COMMITTED asserted

### I-M-004 — Binlog shipping within RPO ≤ 1h
**High** · audit · refs: P2.8/P2.7;

- **Precondition:** backup profile
- **Steps:** 1) Write a row; wait one 15-min ship; inspect restic repo + last_ship timestamp
- **Expected:** --log-bin ROW + expire 7d live; ship cadence ≤15min → published RPO claim ≤1h holds with 4× margin

## I-N. Object store & PACS  (Infrastructure stability)

### I-N-001 — Bucket lifecycle: derived 180d, scratch 7d; excluded from backup
**Medium** · regression · refs: P1.6/P1.7b ILM bump

- **Precondition:** Live MinIO with mc
- **Steps:** 1) Set/verify ILM rules; age synthetic objects past expiry; run backup objectstore pass
- **Expected:** clarion-scratch 7d, clarion-derived 180d expiry enforced; clarion-derived NOT mirrored in backup (excluded by design); ILM wiring per deployment.md present (P1.7 loose end closed)

### I-N-002 — MinIO outage blast radius + recovery
**Critical** · resilience · refs: P1.6 hardening; P5.1 readyz

- **Precondition:** Stack serving traffic
- **Steps:** 1) docker stop minio; exercise: upload, doc view, thumbnail, DICOM, report archive; restart
- **Expected:** Uploads fail 503-class with clean error + audit; reads 503 (never corrupt); /readyz 503, /healthz 200; login/queue/emergency-LAN paths unaffected; auto-recovers without process restart (or documented if)

### I-N-003 — MinIO connection-leak soak
**Medium** · regression · refs: P1.6 voltagent open_stream fix

- **Precondition:** mc/admin monitoring
- **Steps:** 1) 10k sequential object reads + 1k uploads
- **Expected:** Connection count steady-state flat; no fd exhaustion; open_stream closes on client disconnect

### I-N-004 — Orthanc persistence + auth + storage triple
**High** · regression · refs: P4.7 go-live (auth+PG+S3)

- **Precondition:** Compose stack
- **Steps:** 1) Upload study via backend route; restart orthanc; query without/with creds; verify pixels land in clarion-dicom
- **Expected:** Study survives restart (PG index + S3); 401 without registered user; backend sends matching creds; per-request graceful degrade if Orthanc down (app stays up — deliberately not a /readyz dependency)

### I-N-005 — DICOM ingest rejects size-declared zip bomb
**Critical** · regression · refs: P4.7 voltagent real bug

- **Precondition:** —
- **Steps:** 1) Upload archive with honest-but-huge declared size and real bomb bytes; also oversized DICOM
- **Expected:** Cap enforced on REAL bytes, not declared; 4xx; viewer path never OOMs
- **Existing coverage:** P4.7 regression test

### I-N-006 — Object-store WORM provisioning is a live go-live gate
**High** · audit · refs: P1.6 deployment gate

- **Precondition:** Fresh environment
- **Steps:** 1) Run provisioning steps from docs/deployment.md end-to-end; attempt delete during retention
- **Expected:** object_lock+versioning+COMPLIANCE actually created (original bug: they were NOT); gate executed + verified live

## I-O. Observability & alerting  (Infrastructure stability)

### I-O-001 — Prometheus scrapes backend + exporters
**High** · positive · refs: P5.1

- **Precondition:** observability profile
- **Steps:** 1) targets page + queries: up{backend}, mysqld_*, node_*, http metrics
- **Expected:** All targets UP; counters move under traffic; exporters least-priv

### I-O-002 — Disk-full alert fires at 75%/90% — architecture's #1 named risk
**Critical** · resilience · refs: P5.1 rules; On-Prem Architecture

- **Precondition:** Prometheus/Alertmanager up
- **Steps:** 1) fallocate to push object volume past 75% then 90%
- **Expected:** DiskSpaceWarning then DiskSpaceCritical → Alertmanager → email within cadence; thresholds match architecture doc; recovery resolves

### I-O-003 — BackendDown + HighHttp5xxRate rules fire
**High** · resilience · refs: P5.1

- **Precondition:** —
- **Steps:** 1) docker stop backend past for-duration; synthetically 5xx a route
- **Expected:** Both alerts email; resolve signals sent

### I-O-004 — Alertmanager graceful without SMTP; secrets file handling
**Medium** · resilience · refs: P5.1 design

- **Precondition:** SMTP placeholder removed
- **Steps:** 1) Boot alertmanager; place smtp_password
- **Expected:** No crash loop without SMTP; password file git-ignored, never in image; receiver values are operator-edited placeholders (documented)

### I-O-005 — request-id end-to-end correlation
**High** · regression · refs: P5.1 propagation test

- **Precondition:** LOG_FORMAT=json
- **Steps:** 1) Authenticated request; capture header, JSON log line, forced 500
- **Expected:** X-Request-Id == log field == 500 correlation id; bound before CORS/401; user/role/facility after auth

### I-O-006 — Grafana dashboards render (pinned datasource uid)
**Medium** · regression · refs: P5.1 integration bug

- **Precondition:** Grafana up
- **Steps:** 1) Open both dashboards
- **Expected:** No 'datasource not found'; every panel has live data path

### I-O-007 — Log pipeline stdout→Promtail→Loki + retention
**Medium** · positive · refs: P5.1; 30-90d design

- **Precondition:** —
- **Steps:** 1) Search Loki; verify retention config
- **Expected:** Logs searchable end-to-end; retention set; docker-socket residual recorded as documented (file-scrape upgrade path), not re-litigated

### I-O-008 — /metrics & /readyz posture split (live edge-block verification)
**High** · audit · refs: P5.1 owed live check

- **Precondition:** Internal exec + external probe
- **Steps:** 1) Internal GET /metrics; external GET /api/metrics
- **Expected:** Internal served; external 404 — closes P5.1's 'not yet verified live' flag

### I-O-009 — mysqld-exporter PHI surface pinned off
**High** · regression · refs: P5.1 Medium (PROCESS + PyMySQL interp)

- **Precondition:** —
- **Steps:** 1) As clarion_metrics: SELECT clarion.* denied; collector flag; PHI query visibility check
- **Expected:** performance_schema-only grant holds; --collect.info_schema.processlist=false; metrics password = app-cred secrecy tier

## I-P. Backup & disaster recovery  (Infrastructure stability)

### I-P-001 — backup.sh every mode emits status JSON and succeeds
**High** · resilience · refs: P2.8;

- **Precondition:** backup profile up
- **Steps:** 1) Run full / incremental / logical / binlog / objectstore / prune / daily / weekly
- **Expected:** Each completes with ONE parseable JSON status line per run; failure paths also emit status (never silence)
- **Existing coverage:** backend/backup/backup.sh

### I-P-002 — Quarterly restore drill: full+incr+binlog PITR
**Critical** · resilience · refs: P2.8; RTO≤4h

- **Precondition:** Backup set exists
- **Steps:** 1) restore-test.sh into throwaway mariadbd; replay binlogs to last txn; reconcile Alembic head + every table row count vs prod
- **Expected:** Restored DB == head, counts reconcile, signed report emitted; drill completed within RTO≤4h (timed); last drill date + report filed with the University (manual gate)

### I-P-003 — PITR proves RPO ≤ 1h on real transactions
**High** · regression · refs: P2.8; architecture RPO

- **Precondition:** Ship cadence 15min
- **Steps:** 1) Write row T0; kill DB; restore to just-before-crash via binlog
- **Expected:** Row present; data loss window ≤ ship interval; mydumper logical + mariadb-backup physical both independently restorable

### I-P-004 — 30-day retention + rotation policy enforced
**Medium** · audit · refs:

- **Precondition:** restic repo aged synthetically
- **Steps:** 1) restic snapshots + prune with --keep-daily 30 --keep-weekly 12 --keep-monthly 84 --keep-yearly 7
- **Expected:** Correct snapshots survive each window; weekly `restic check` (with --verify) green; 7y archive tiers exist

### I-P-005 — Pre-update snapshot gate blocks deploys
**High** · resilience · refs: P2.8;

- **Precondition:** Pending stack update
- **Steps:** 1) Run pre-update-snapshot.sh; attempt deploy without it
- **Expected:** Fresh full+logical backup recorded; Alembic downgrade target + running image digests captured; hypervisor snapshot id prompted; deploy pipeline gate refuses to proceed without a passing run

### I-P-006 — 3-2-1 posture: offline monthly disk in another building
**Medium** · audit · refs: P2.8 runbook; architecture

- **Precondition:** Manual process
- **Steps:** 1) Verify procedure documented + exercised quarterly: monthly rotated disk, different building, restic repo readable from it
- **Expected:** Runbook steps match reality; restore-from-offline-disk spot check works; contacts current

### I-P-007 — Backup creds least-privilege
**High** · regression · refs: 2026-09-14 clarion-backup user

- **Precondition:** minio-init run
- **Steps:** 1) As backup container creds: attempt write/delete on app buckets
- **Expected:** clarion-backup read-only on its 6 mirror-source buckets; restic repo append-only/object-lock honoured; root creds not required at runtime

## I-Q. Integration resilience (HL7, registries, NIH, LDAP, printers)  (Infrastructure stability)

### I-Q-001 — MLLP socket round-trip under production shapes
**High** · positive · refs: P4.8

- **Precondition:** hl7-listener service (own process, NOT a gunicorn worker)
- **Steps:** 1) Send valid ORU^R01 over real socket; variants: unicode, multi-obx, empty fields
- **Expected:** Parsed + staged AnalyserResultInbox; ACK returned; ORM^O01 push path verified against fake analyser socket
- **Existing coverage:** test_hl7_listener.py / test_hl7_client.py

### I-Q-002 — Unreachable analyser never blocks order creation
**Critical** · resilience · refs: P4.8 'advisory, never authoritative'

- **Precondition:** HL7_HOST unset or black-holed
- **Steps:** 1) Create lab order; time the response
- **Expected:** Order commits at normal latency; push best-effort queued/skipped + logged; zero user-visible failure
- **Existing coverage:** test_ancillary_analyser_inbox.py

### I-Q-003 — HL7 listener restart reconciliation
**High** · resilience · refs: P4.8 (own process design)

- **Precondition:** Listener up, then crash/restart
- **Steps:** 1) Deliver during outage window; restart; check inbox
- **Expected:** Lost connections don't corrupt state; re-delivery dedups sanely; matched→sign-off flow still clinician-only (never auto-signed)
- **Existing coverage:** test_hl7_listener.py

### I-Q-004 — the University registry adapter: any failure mode = advisory degrade
**High** · regression · refs: 2026-09-15 landing + httpx.InvalidURL bug

- **Precondition:** Mock at /mock-campus-registry; real URL unset
- **Steps:** 1) Kill mock mid-call, 500 it, slow it, send garbage, feed control-char NRIC
- **Expected:** check_eligibility NEVER raises: {available:false} or not-found every time; registration flow never blocks; swap to real endpoint = env-only change
- **Existing coverage:** test_campus_registry.py (9)

### I-Q-005 — RxNav/DailyMed outage handled by cache + pooled client
**High** · resilience · refs: CR4; P4.4 cache-sharing fix

- **Precondition:** Block NIH at network layer
- **Steps:** 1) Run interaction screens warm vs cold
- **Expected:** Warm: 1h-TTL cache serves, screen OK; cold: graceful 'check unavailable' advisory, no 500, no per-call new client stampede; sync+async paths share the cache (fixed drift bug)

### I-Q-006 — Local LLM/whisper outage = fallbacks not failure
**High** · resilience · refs: P4.3 (opt-out not opt-in)

- **Precondition:** Stop Ollama
- **Steps:** 1) Run summarize/OCR/CDS/voice/narrative/explain
- **Expected:** Tesseract/deterministic fallbacks answer; endpoints 200 with reduced fidelity; CPU-fallback latency under gunicorn --timeout 60 (P5.2 tuning)

### I-Q-007 — ESC/POS printer offline doesn't wedge queue ops
**Medium** · resilience · refs: P3.9

- **Precondition:** Printer unplugged
- **Steps:** 1) Issue ticket / sample label
- **Expected:** Queue operations succeed; print job errors surfaced + retryable; TV display audio/branding unaffected
- **Existing coverage:** P3.9 suite

### I-Q-008 — NFC bridge local-process exposure (L3) posture check
**Medium** · audit · refs: SA-L3 residual

- **Precondition:** Bridge running
- **Steps:** 1) From another local process GET /last-scan
- **Expected:** Behaviour matches documented residual (any local process reads UID = bearer-ish for /emergency/scan); re-flag ONLY if scope widened; anomaly debounce (M7c) compensates

## I-R. Two-campus rollout & WAN resilience  (Infrastructure stability)

### I-R-001 — branch-edge starts on isolated network, minimal env
**High** · regression · refs: P5.3 self-caught anchor leak

- **Precondition:** Compose with --profile branch-edge
- **Steps:** 1) Start edge; inspect its network + env list
- **Expected:** Its own isolated network (not edge/internal/observability); EXACTLY the 4 vars it needs (no MariaDB/MinIO root creds, SECRET_KEY, OTP_HMAC_KEY leak); reuses central web image unchanged

### I-R-002 — Central origin must be https:// or the edge refuses to start
**High** · regression · refs: P5.3 voltagent Low fix

- **Precondition:** Branch env
- **Steps:** 1) Set CLARION_CENTRAL_BACKEND_ORIGIN = http://… / bare host:port / valid https
- **Expected:** First two: container exits with loud validation error (verified against real caddy:2.8-alpine); https proceeds — no silent plaintext WAN proxying

### I-R-003 — Branch has its own cert dir
**Medium** · regression · refs: P5.3 voltagent Medium

- **Precondition:** Production-shaped certs in proxy/certs
- **Steps:** 1) Inspect branch-proxy mounts
- **Expected:** Mounts proxy/branch-edge/certs/ — central TLS private key never copied to the less-trusted site

### I-R-004 — Simulated WAN latency/loss: SPA local, API degraded cleanly
**High** · load · refs: P5.3 simulate-wan.sh

- **Precondition:** tc netem on loopback
- **Steps:** 1) Inject 150ms±50 / 2% loss; run Locust through branch-proxy
- **Expected:** Static SPA served from Branch LAN (no WAN hit); API requests slower but correct — no cascading timeouts; P5.2 suite green under impairment

### I-R-005 — Full WAN cut at Branch
**High** · resilience · refs: P5.3 + appliance design

- **Precondition:** tc netem 100% loss
- **Steps:** 1) Browse Branch edge; attempt API ops; tap offline NFC tag
- **Expected:** Static shell serves; API fails with clear offline messaging (never stale-as-fresh); NFC reader falls back to on-card text ONLY on no-response (statusCode==null) with loud OFFLINE banner — a real 404 never masquerades as offline

### I-R-006 — Appliance build→offline query→reconciliation loop
**Critical** · resilience · refs: P5.3; emergency-first clause

- **Precondition:** age keypair
- **Steps:** 1) Nightly-style build; detach; query by NRIC offline; reconnect; run reconciliation procedure into audit_logs
- **Expected:** Only encrypted export + private key on appliance; query returns critical-only fields; local access log holds sha256(NRIC) not NRIC; post-reconnect audit rows land

### I-R-007 — Self-booking across campuses (P3.9 timezone fix)
**Medium** · regression · refs: P3.9 review (Critical timezone bug)

- **Precondition:** Flutter device, non-MYT locale
- **Steps:** 1) Book at both campuses; check slot resolution
- **Expected:** Device-timezone safe (the fixed bug class); DB-level double-book guard holds under concurrent tap-race
- **Existing coverage:** P3.9 fix wave

## I-S. Load, soak & resource ceilings  (Infrastructure stability)

### I-S-001 — Locust weighted-mix baseline green
**High** · load · refs: P5.2

- **Precondition:** MariaDB profile; seeded accounts; Redis live
- **Steps:** 1) Run 18 users @1/s ×3min (default weights)
- **Expected:** ≥ ~1200 requests, ZERO 5xx/DB errors/timeouts; median latency within 9-28ms envelope per route class; only failures = expected per-route 60/min on heaviest weights

### I-S-002 — Rate-limit ceiling vs capacity ceiling — labelled honestly
**Medium** · audit · refs: P5.2 scope limit

- **Precondition:** —
- **Steps:** 1) Attempt to derive a '23k-user capacity number' from the single-IP run
- **Expected:** NOT permissible: run is one apparent client IP; capacity conclusion requires distributed generator or operator-authorized staging bypass (repo-level decision — the declined unilateral FORWARDED_ALLOW_IPS widening is the anti-pattern); test asserts the README carries this caveat

### I-S-003 — Long soak: memory, fd, connections flat
**High** · load · refs: P5.2 gunicorn recycling

- **Precondition:** Stack under 4h continuous mixed load + uploads
- **Steps:** 1) Watch RSS/fd/DB conns/LRU per worker
- **Expected:** No unbounded growth (recycling max-requests=2000±200 masks slow leaks — recycle boundaries show clean resets not error spikes); jobs table drains; Loki/Prometheus ingest keeps pace

### I-S-004 — Audit + clinical write storm keeps chain intact
**High** · load · refs: P2.9/P1.3

- **Precondition:** Concurrent writers
- **Steps:** 1) 4 workers × high-rate log_access + clinical mutations
- **Expected:** Chain gap-free under contention (tip lock throughput measured); no lock-wait 500s; if tip becomes bottleneck → recorded finding for CI4 port sizing

### I-S-005 — CPU-heavy endpoints under gunicorn timeout
**Medium** · resilience · refs: P5.2 --timeout 60 rationale

- **Precondition:** No GPU; CPU quantized model
- **Steps:** 1) Run voice→SOAP + narrative on cold model under concurrent API load
- **Expected:** No SIGKILL mid-inference; other routes unaffected (workers); degradation curve visible in /metrics

### I-S-006 — 24MP pixel-bomb fleet vs Semaphore(4)
**Medium** · resilience · refs: P1.7 decode gate

- **Precondition:** —
- **Steps:** 1) 50 near-ceiling images simultaneously
- **Expected:** Gate holds: queue → 429/503, never OOM; ceiling exact at 24MP; HEIC path included

## I-T. CI & supply chain  (Infrastructure stability)

### I-T-001 — ci/run.sh hard gates all green
**High** · audit · refs: P2.11;

- **Precondition:** Repo checkout
- **Steps:** 1) bash ci/run.sh (ruff→bandit→semgrep→osv-scanner→trivy→check_schema→pytest)
- **Expected:** Every hard gate passes (currently ~561 tests); --fast/--no-sca variants work; failure modes exit non-zero loudly

### I-T-002 — Air-gapped CI data feeding
**Medium** · resilience · refs: P2.11 design

- **Precondition:** VM-BACKUP Gitea/Woodpecker
- **Steps:** 1) Refresh osv DB, trivy DB, semgrep rules, devpi mirror offline; re-run
- **Expected:** osv-scanner runs from pre-downloaded DB (pip-audit rejected FOR this reason); pipeline green with no internet

### I-T-003 — SCA: dep pins + known-CVE posture
**High** · audit · refs: SA-L1; MinIO repoint;

- **Precondition:** SBOM (syft) per image
- **Steps:** 1) Scan requirements.txt/pins + base images
- **Expected:** python-jose/ecdsa Minerva CVE-2024-23342 tracked (unexploitable on HS256) + migration plan open; bcrypt note; quay.io MinIO predates CVE-2025-62506 — accepted residual re-asserted vs current advisories; no NEW criticals untriaged

### I-T-004 — Frontend build integrity
**Medium** · audit · refs: P4.3c incident (await-in-callback broke the build)

- **Precondition:** —
- **Steps:** 1) npm run build + lint; flutter analyze
- **Expected:** All green — a broken build fails CI, not the demo; no VITE_-prefixed secret bleed to bundle (P1.8 F5 doc note checked against actual bundle)

### I-T-005 — Secrets scanning on commits
**High** · audit · refs: CR1 (MyKad photos staged);

- **Precondition:** Pre-commit/CI
- **Steps:** 1) Run secret-scan over staged diff (gitleaks-class tool) + PHI-pattern scan (NRIC format, image magic bytes)
- **Expected:** Zero hits; .gitignore covers uploads/, encryption/, proxy/certs/*, smtp_password, key.properties, *.db

### I-T-006 — Shell lint gate
**Low** · audit · refs: P2.8 shellcheck wiring

- **Precondition:** —
- **Steps:** 1) shellcheck all *.sh incl. new ones
- **Expected:** Zero warnings (10-accounts.sh idempotency helpers included); minio/mariadb init scripts stay lint-clean

### I-T-007 — Flutter release signing present, debug fallback loud
**Medium** · positive · refs: P1.13

- **Precondition:** Release build
- **Steps:** 1) Build without/with key.properties
- **Expected:** Without: loud warning + debug key (never silent); with: signed release APK

