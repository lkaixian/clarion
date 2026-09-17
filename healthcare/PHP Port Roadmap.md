---
title: PHP Port Roadmap
type: plan
updated: 2026-09-17
tags: [plan, roadmap, clarion, campus, codeigniter, php-port]
---

# CLARION → PHP CodeIgniter 4 port — phased plan

## Context

the tender (`the tender reference`) mandates the delivered system
run on PHP CodeIgniter 4 (CI4). CLARION's strategy from day one was: build and win the
competition demo on FastAPI + React + Flutter, then port the backend to CI4 for the
actual tender delivery (`healthcare/Designing for the PHP Port.md`). That demo build is
now done — every row of the original P0–P5 roadmap has a status (`AGENTS.md`), covering
all 15 tender-mandated modules plus the full P2–P5 security/AI/FHIR/PACS/HL7/analytics
waves. This plan is the next roadmap: **how to port that finished FastAPI backend to
CI4**, in the same phase-by-phase, effort-sized style as [[Implementation Roadmap]].

Decided with the user before planning (not re-litigated below):
1. **Full parity, phased** — every module must eventually exist in CI4; core/mandatory
   modules sequenced before AI/analytics/nice-to-haves.
2. **Keep React web SPA + Flutter mobile as-is** — this is an API-level port. Clients
   get repointed at the new CI4 base URL once each module's contract matches; no
   frontend rewrite.
3. **Solo dev + AI pair-programming pace** — same mode the FastAPI build actually used;
   phases sized in days like the original roadmap's S(1–3)/M(4–7)/L(8–15) tags.

This plan went through two research passes: a first file-size/paragraph-level pass
(~300–330 PD), then a **deep, per-file digest** of all 25 routers + ~20 service modules
(endpoint-by-endpoint, every non-boilerplate business rule, every RBAC/facility-scoping
nuance) done via three parallel research agents. The deep pass surfaced substantially
more discrete business logic per file than the first pass estimated — the numbers below
supersede the first-pass roll-ups.

## Total effort re-estimate (revised after deep research)

**≈ 515 person-days (≈ 24–26 person-months nominal at 20 PD/month).** This is higher
than both [[Designing for the PHP Port]]'s original 2–4-month estimate (written for a
~30-table API with none of P2–P5's scope) and this plan's own first-pass ~300–330 PD
estimate. The deep, file-by-file research is *why* it moved: files that looked like "a
big router, size it M/L" turned out to bundle many independent, non-boilerplate rules
once actually read — e.g. `patients.py` alone has ~15 distinct pieces of logic
(NRIC-derived DOB, cross-facility immutability, break-glass scoping, annotation
effective-status folding, safe content-type serving...); `billing.py` has a 3-branch
price-source resolution + decimal-safe cents math + a 5-field live money computation +
a claim amount-cap rule; `ai/interactions.py` bundles three separate subsystems (rule
tables, RxNorm/DailyMed/RxClass client+cache, class-level screening) in 1341 lines.
None of this was visible from file size alone.

**Calendar-time note (unchanged in spirit):** the original FastAPI build (comparable
scope) landed in ~3 weeks under heavy AI-pairing, but that was green-field authorship.
This port is cross-language transcription-and-verification of already-subtle business
rules — categorically slower per unit of code, though many of the ~515 PD are mechanical
CRUD that compresses hard under AI-pairing once the kernel (CP0) and one or two reference
modules establish the pattern. Budget **6–10 calendar months** for a solo dev at this
project's demonstrated pace — not the naive 24–26-month PD figure, but also not the
original build's 3 weeks.

## Phase table

Dependency-ordered — no phase depends on a later one. **CP0 is deliberately large and
first**: it's the shared kernel (auth, RBAC, facility-scope, audit chain, jobs, storage,
LDAP) every later controller sits on top of.

### CP0 — Platform kernel (~65 PD) — blocks everything else
| # | Task | Size | Source → CI4 |
|---|---|---|---|
| CP0.1 | CI4 8.x skeleton + composer deps (firebase/php-jwt, guzzlehttp/guzzle, aws/aws-sdk-php, intervention/image, ext-ldap, predis, phpunit) | S | new |
| CP0.2 | Freeze FastAPI's `/openapi.json` as contract-of-record; build a cross-backend contract-test harness (schemathesis-style, points at either base URL) | M | `docs/openapi-v1-frozen.json` + `contract-tests/` |
| CP0.3 | ONE squashed `forge` baseline migration reproducing today's schema; `check_schema.php` reflect-and-diff gate | S | `alembic/versions/*` (32 revisions) → 1 CI4 migration |
| CP0.4 | JWT issue/verify/refresh, login/logout, lockout | L | `app/auth.py` |
| CP0.5 | **RBAC page-access Filter + cross-facility scoping/immutability kernel** | L | `app/permissions.py` + `app/clinical_access.py` |
| CP0.6 | **Audit hash-chain writer/verifier + cross-language golden-vector test** | M | `app/audit.py` + `app/audit_hash.py` |
| CP0.7 | DB-table job queue (`spark jobs:work`) | S | `app/jobs.py` — already designed portable, see below |
| CP0.8 | Redis-backed rate-limit Filter, fail-open on Redis outage | S | `app/rate_limit.py` |
| CP0.9 | ObjectStore: Local + MinIO (S3 API, versioning, COMPLIANCE object-lock) | M | `app/storage.py` |
| CP0.10 | Image normalisation + PDF first-page preview + queued thumbnail priming | M | `app/imaging.py` + `app/derived.py` |
| CP0.11 | LDAP/AD: bind→search→bind, JIT provisioning, TLS `CERT_REQUIRED`, Redis-backed concurrency gate | M | `app/ldap_auth.py` |
| CP0.12 | Security-header/request-id Filters, route skeleton, `/healthz` `/readyz` | S | `main.py` slice |
| CP0.13 | Shared on-prem-IP-resolution guard (one PHP helper — Python has this duplicated in `local_llm.py`+`pacs.py`, don't repeat that in the port) | S | `ai/local_llm.py::_is_on_prem_host` |
| CP0.14 | Directory helper (batch user-name resolution) | S | `app/directory.py` |

### CP1 — Identity & core patient record (~61 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP1.1 | Patient create/CRUD: NRIC-derived DOB override, dash/case-tolerant duplicate pre-check + DB IntegrityError fallback | M | `routers/patients.py` |
| CP1.2 | Cross-facility clinical-record immutability for conditions/medications/allergies/encounters (author-facility + patient-currently-present gate, no admin override, NULL-author = immutable to all) | L | `routers/patients.py` + CP0.5 |
| CP1.3 | Append-only annotations (`resolved`/`discontinued`) + effective-status folding on read, signature-required | M | `routers/patients.py` |
| CP1.4 | Patient list/search: facility-relationship default scope + break-glass escape hatch (distinct audit) | M | `routers/patients.py` |
| CP1.5 | Full-record cross-facility read (always allowed, life-safety design) + distinct audit line | S | `routers/patients.py` |
| CP1.6 | Clinical documents: safe content-type serving (never trust client filename), thumbnail cache/ETag, facility opt-out read filter | M | `routers/patients.py` |
| CP1.7 | Patient self-service profile PATCH (identity fields explicitly immutable, 400 not silent-drop) + paginated audit-log w/ batched actor-name resolve | S | `routers/patients.py` |
| CP1.8 | Self-registration state machine: NRIC/name/DOB self-consistency → OTP → dual-photo OCR match → complete, incl. 5-strike flag-to-manual-review dead-end, rate-limit-before-reset-state ordering, concurrent-staff-account race guard | L | `routers/self_registration.py` |
| CP1.9 | Profile: signature CRUD (triple content validation) + colleague lookup (non-leaking 404) + bio/photo self-service (image normalise pipeline) | M | `routers/profile.py` |
| CP1.10 | Staff clock-in/out (409 double-open guard) + clock-out cascading room-release side effect | S | `routers/staff.py` |
| CP1.11 | Admin — staff roster (batched clock-status, no N+1), section assignment, profile/photo admin edit, waiting-room display token mint/revoke | M | `routers/admin.py` (staff/display sections) |
| CP1.12 | The University eligibility adapter (never-raises contract, URL-encode NRIC) + demo mock endpoint | S | `campus_registry.py` + `routers/campus_registry_mock.py` |

### CP2 — Reception, queueing, appointments, emergency (~72 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP2.1 | Check-in: 4-way patient identifier resolution (IC/patient_id/QR/NFC UID — deliberately skips revoked/expired check, staff-authenticated low-risk lookup) + round-robin room assignment | L | `routers/reception/checkin.py` |
| CP2.2 | Race-safe queue-number assignment (bounded retry against DB unique constraint) | M | `routers/reception/checkin.py` |
| CP2.3 | Queue board: call/complete/cancel/assign-room + per-department "now serving" auto-complete-previous semantics | M | `routers/reception/queue.py` |
| CP2.4 | Room claims: claim/release/my-room worklist, requires-clocked-in, DB unique-constraint race → 409 | M | `routers/reception/rooms.py` + `_common.py` |
| CP2.5 | Self-check-in stations: QR mint/revoke (blocked for section-scoped staff) + patient-authenticated self-checkin | S | `routers/reception/stations.py` |
| CP2.6 | Admissions: admit (explicit or gender-aware auto-pick bed) + move (re-validate bounds/collision/gender) + discharge; `Ward.occupied_beds` legacy counter explicitly NOT the source of truth | L | `routers/reception/admissions.py` |
| CP2.7 | Ward-map (nested floors→wards→beds grid, batch-resolved names) | M | `routers/reception/admissions.py` |
| CP2.8 | Shared reception-scope concern: `User.section` per-counter scoping threaded through checkin/queue/rooms/stations/admin — port as one shared service, not per-controller | S | `routers/reception/_common.py` |
| CP2.9 | Appointments CRUD + two-step reschedule-request workflow (accept ≠ reschedule) + computed-not-stored reminder offsets | M | `routers/appointments.py` |
| CP2.10 | Self-booking: live slot computation + DB partial-unique-constraint race fallback (in-Python check is not the real guarantee) | M | `routers/appointments.py` |
| CP2.11 | Emergency QR: issue (auto-revoke prior) / revoke / scan (unauthenticated, rate-limited, category-filtered + omitted-count) | L | `routers/emergency.py` |
| CP2.12 | Emergency facility-presence gate for staff actions (no admin override) + life-safety records-shared-publicly bypass w/ its own distinct audit line | M | `routers/emergency.py` |
| CP2.13 | Emergency NFC: register/scan/revoke (dual QR/NFC credential model) + scan-anomaly debounce (>8/hr) + compact tag-text priority-packing builder | M | `routers/emergency.py` |
| CP2.14 | Waiting-room public display: name-masking algorithm + per-token (not per-IP) rate limit | S | `routers/display.py` |
| CP2.15 | Admin — appointments dashboard, wards/floors (cascade-safe resize rules)/consultation-rooms/facility-sections CRUD (rename cascades to `User.section`) | M | `routers/admin.py` (facility-structure sections) |

### CP3 — Consultation, ancillary engine, dental, pharmacy (~73 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP3.1 | **Ancillary engine confirmed as ONE module** driving Lab/X-ray/Physio/Procedure via a `module` column value, not 4 separate builds — catalog CRUD w/ ownership/global-publish rules | M | `routers/ancillary.py` |
| CP3.2 | Order creation: catalog/module/encounter validation + price snapshot at write + best-effort HL7 push (never blocks) | M | `routers/ancillary.py` |
| CP3.3 | Order list/get: cross-facility read split (patient_id-filtered vs. facility worklist), opt-out filter applied **pre-pagination** | M | `routers/ancillary.py` |
| CP3.4 | Sign-off: atomic perform+sign, signature required, `service_request_id` UNIQUE race→409, immutable after (corrections via annotation only) | M | `routers/ancillary.py` |
| CP3.5 | Document attach/download (one-shot 409 on repeat, magic-byte sniff, safe filename separator) + label PNG | S | `routers/ancillary.py` |
| CP3.6 | Stats endpoint + HL7 analyser-inbox list/discard | S | `routers/ancillary.py` |
| CP3.7 | Dental: chart options (static config) + history (cross-facility read) + create+sign (append-only, thin layer reusing ancillary/consultation/patients) | S | `routers/dental.py` |
| CP3.8 | Consultation session start/end: atomic clock-in+room-claim+rollback-on-race | M | `routers/consultation.py` |
| CP3.9 | Per-room ticket confinement gate + call/cancel delegating to reception's shared `_impl` functions (not HTTP routes) | S | `routers/consultation.py` |
| CP3.10 | Consultation sign-off: encounter+note+referral-ownership validation+signature snapshot; note created even for vitals-only | M | `routers/consultation.py` |
| CP3.11 | CDS-hint + voice-to-SOAP passthrough endpoints (thin, depend on CP5) | S | `routers/consultation.py` |
| CP3.12 | Document generation: 4 fixed-layout single-page PDF renderers (MC/referral/timeslip/visit-summary), library swap to TCPDF/mPDF/Dompdf | M | `document_generation.py` |
| CP3.13 | Pharmacy: inventory list/search/low-stock/summary badges | S | `routers/pharmacy.py` |
| CP3.14 | Pharmacy: `adjust_stock` restock-immediate-vs-needs-approval fork sharing ONE `_apply_restock` primitive with admin's approval path (must not diverge) | M | `routers/pharmacy.py` + `inventory.py` |
| CP3.15 | Pharmacy: medicine image upload/serve/thumbnail (shared service w/ CP0.10) | M | `routers/pharmacy.py` + `inventory.py` |
| CP3.16 | Pharmacy: delete-request + purchase-proposal filing (existing-item restock vs. brand-new item, dup-409 both) + admin approval counterpart | M | `routers/pharmacy.py` + `inventory.py` |
| CP3.17 | Printing: ESC/POS ticket + sample-label PNG builders — **must replicate the control-character-strip security fix** (ESC/GS bytes are the ESC/POS command introducers) | S | `printing.py` |

### CP4 — Billing, reporting, dashboard, admin-remainder, PDPA, data quality (~101 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP4.1 | Charge-master catalog CRUD (no delete, toggle-active) | S | `routers/billing.py` |
| CP4.2 | Bill create/list/get — **facility-local only, no cross-facility mode** (deliberate asymmetry vs. ancillary/dental) | S | `routers/billing.py` |
| CP4.3 | Bill line-item add: 3-branch price-source resolution (charge_master/service_request/pharmacy_item), each 404s outside caller's facility, `Decimal(str(...))` cents conversion (never float round), soft duplicate-billing guard | L | `routers/billing.py` |
| CP4.4 | Bill totals: 5 money fields computed live every read (never stored) — total/paid/claimed-pending/amount-due/patient-due (copay-split model) | M | `routers/billing.py` |
| CP4.5 | Item/payment void (with reversal effects) + bill finalize/void — void-only discipline, never hard-delete | M | `routers/billing.py` |
| CP4.6 | Claims state machine (draft→submitted→approved→paid/rejected/void) + amount-cap validation (net of every OTHER active claim, shared between create+update) + payment-settles/void-reverts-claim linkage | M | `routers/billing.py` |
| CP4.7 | Billing stats endpoint (stand-in for full report builder) | S | `routers/billing.py` |
| CP4.8 | Reporting HTTP surface: run/export/narrative wrappers + template CRUD (visibility rule: shared OR own OR admin, 404-not-403) | M | `routers/reporting.py` |
| CP4.9 | **Reporting engine**: curated Dataset/Field registry (5 datasets, never a raw client column name reaching SQL) + filter/group/sort/anonymize/period-bucket/per-request lookup-cache — preserve the registry pattern as-is, don't flatten | L | `reporting_engine.py` |
| CP4.10 | Notifiable-disease workflow: candidate fuzzy-match (static disease list) + free-text filing + per-condition dedup guard | M | `routers/reporting.py` |
| CP4.11 | Report export: PDF table render (TCPDF/mPDF) + Excel (PhpSpreadsheet ~1:1 API match to openpyxl) + fixed-layout e-Notifikasi PDF form | M | `report_export.py` |
| CP4.12 | Dashboard: 4-factor weighted health-score formula (replicate exact thresholds) + EWMA flow-forecast (α=0.3, weekday-seasonality history) | M | `routers/dashboard.py` |
| CP4.13 | PDPA consent ledger: append-only, newest-per-purpose-wins read — **no erasure mechanism, Malaysian PDPA has none, this covers optional purposes only** | S | `routers/pdpa.py` |
| CP4.14 | PDPA DSR workflow: 4-tier access (self/facility-scoped/break-glass/platform-admin), assign/claim-orphan-request, complete/reject/statutory extend (21+14 day cap), export (bypasses sharing-filter for the data subject's own record, requires assigned+in-progress first) | L | `routers/pdpa.py` |
| CP4.15 | Retention scan: flag-only (never deletes) across 3 entity categories, policy-table-with-hardcoded-Malaysian-law-fallback, idempotent upsert | M | `retention.py` |
| CP4.16 | Data-quality: 13-rule registry (missing/coding/duplicate/anomaly) + upsert/auto-resolve/reopen/disabled-rule/failed-rule state machine — the reconcile logic is the one place a naive re-implementation could silently diverge | L | `data_quality.py` |
| CP4.17 | Admin-remainder: security-alert + data-quality-alert ack/resolve/explain, facility-scoped non-leaking 404 | M | `routers/admin.py` (alert sections) |
| CP4.18 | Admin-remainder: LDAP role-mapping CRUD w/ privilege-escalation guard (facility-scoped admin can't grant `role=admin`) | S | `routers/admin.py` (depends on CP0.11) |
| CP4.19 | Admin-remainder: audit hash-chain integrity endpoint (platform-global) | S | `routers/admin.py` (depends on CP0.6) |

### CP5 — On-prem AI engine (~59 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP5.1 | Ollama HTTP client (Guzzle → `/api/generate`, text + vision), never-raises-returns-null contract | S | `ai/local_llm.py` |
| CP5.2 | NRIC OCR: LLM-vision primary + Tesseract fallback, century-ambiguity DOB heuristic (try both 1900s/2000s, discard implausible) | M | `ai/nric_ocr.py` |
| CP5.3 | Voice→SOAP — **re-platform, not faithful port**: no PHP CTranslate2/faster-whisper binding exists; call a whisper.cpp HTTP sidecar or subprocess, `ffprobe` duration-cap check (anti-CPU-bomb, low-bitrate-long-clip defense), LLM SOAP segmentation w/ raw-transcript-never-lost fallback | L | `ai/voice_soap.py` |
| CP5.4 | CDS hint + handover summarize + report narrative (3 thin prompt-wrapper endpoints; CDS hint's allergy-conflict check shares CP5.5c) | S | `ai/cds_hint.py`, `ai/summarize.py`, `ai/report_narrative.py` |
| CP5.5a | Medication safety: RxNorm/DailyMed/RxClass HTTP client + shared TTL cache (same cache keys across sync/async call sites — the P4.4 dual-cache bug doesn't exist in CI4 since there's no async/sync split, keep it that way) | M | `ai/interactions.py` |
| CP5.5b | Medication safety: 10-pair hardcoded DDI table + 6-class-prefix/3-class-pair ATC screening | M | `ai/interactions.py` |
| CP5.5c | Medication safety: two-tier allergy-conflict check (substring, then class if substring missed) | S | `ai/interactions.py` |
| CP5.5d | Medication safety: duplicate-prescription reconciliation + concurrent multi-drug resolution (Guzzle promise pool vs. sequential — a real perf/complexity tradeoff, no native `asyncio.gather` equivalent) | M | `ai/interactions.py` |
| CP5.6 | Security analytics: fanout (≥20/50 per tumbling hour) + off-hours (00:00–05:00 MYT) rules, `(rule,actor,facility,window)` dedup key, clock-skew-safe `latest` clamping, auto-resolve | M | `security_analytics.py` |
| CP5.7 | Audit-trail AI narrative (canned per-rule context + strictly-alert-fields-only prompt) | S | `ai/audit_intelligence.py` |
| CP5.8 | Predictive analytics: EWMA level+trend forecaster (α=0.3, deliberately not textbook Holt's — can't diverge) over visits/disease-burden/stock | M | `predictive_analytics.py` |
| CP5.9 | Predictive analytics: population risk stratification (additive deterministic score/band, 180-day-windowed ED-visit sub-metric) | S | `predictive_analytics.py` |

### CP6 — Interoperability & imaging (~43 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP6.1 | FHIR façade: shared `_coding`/`_bundle` helpers + reused patient-read access policy + cross-facility view/no-view audit distinction | S | `routers/fhir.py` |
| CP6.2 | FHIR façade: 8 resource-type mappers (get-by-id + search-by-patient each, one repeated template) + static CapabilityStatement | M | `routers/fhir.py` |
| CP6.3 | PACS client: Orthanc upload/get-study/get-instance-file + on-prem guard (reuse CP0.13) | S | `pacs.py` |
| CP6.4 | PACS upload: **zip-bomb-safe bounded extraction** — must track actual decompressed bytes per member against a running budget, never trust `ZipInfo`'s declared size (PHP `ZipArchive` has the identical forgeable-size risk) + DICOM magic-byte check | L | `routers/pacs.py` |
| CP6.5 | PACS metadata/file-streaming: instance-id containment check (requested id must be a member of the granted study) + cross-facility opt-out read | M | `routers/pacs.py` |
| CP6.6 | HL7 codec: ORM^O01/ORU^R01 encode/decode + MLLP framing + **escape/unescape via single regex-callback pass, not sequential `str_replace`** (the one documented correctness bug class in the original) | M | `hl7v2.py` |
| CP6.7 | HL7 outbound client: raw TCP push, advisory-only, never blocks order creation on unreachability | S | `hl7_client.py` |
| CP6.8 | HL7 inbound listener — **architecture decision required first**: CI4's request/response lifecycle has no long-running-daemon-with-thread-per-connection pattern; port as a standalone PHP CLI process (single-threaded sequential accept loop is sufficient at 1–2-analyser real scale) with its own supervisor/systemd-managed restart, not shoehorned into CI4 | L | `hl7_listener.py` |

### CP7 — Ops parity, contract validation, cutover (~41 PD)
| # | Task | Size | Source | Notes |
|---|---|---|---|---|
| CP7.1 | Email service: Mailgun HTTP client, uniform-false-on-any-failure contract (never leak *why* it failed) | S | `email_service.py` |
| CP7.2 | Emergency-export appliance: nightly bulk export (reuses CP2.11's scoped-fields helpers) + `age`-CLI encrypt/decrypt (shell-out, same as backup pipeline) + facility validation + dual audit trail | M | `emergency_export.py` |
| CP7.3 | Observability parity: request-scoped logging context as a CI4 service/DI object (no `contextvars` equivalent needed — PHP's per-request model has no cross-request leak risk to guard against) + `/metrics` (promphp) | M | `log_context.py` |
| CP7.4 | Contract-test harness: freeze OpenAPI, schema-driven battery runnable against either backend base URL | M | uses CP0.2 |
| CP7.5 | Security-critical PHPUnit port: mine the 55 existing pytest files' *assertions* (not just fixtures), reproduce security-critical ones first — auth/RBAC/facility-scoping/immutability, then billing money-math, then HL7 round-trip | L | `backend/tests/*` |
| CP7.6 | Load-test replay: `backend/loadtest/locustfile.py` reused unchanged against CI4 base URL + PHP-FPM pool tuning | M | `backend/loadtest/` |
| CP7.7 | Phased per-module traffic cutover (Caddy prefix routing) + web/Flutter repoint validation + FastAPI decommission after bake period | M | `proxy/Caddyfile` |

## Riskiest phases, ranked

1. **CP0.5 (RBAC + facility scoping)** — a transcription bug here doesn't crash, it
   silently leaks or hides patient data across facilities. Needs its own PHPUnit suite
   mirroring `test_patients_facility_scoping.py`/`test_auth_rbac_immutability.py`
   *before* any router work builds on top of it.
2. **CP0.6 (audit hash-chain, cross-language)** — the wire format
   (`CHAIN_DOMAIN = b"audit-chain-v1:"`) must be byte-for-byte identical to Python's
   canonicalization (`json.dumps(sort_keys=True, ensure_ascii=False, default=str)`) —
   PHP needs `JSON_UNESCAPED_UNICODE` + recursive `ksort`. Hard prerequisite gate for
   §"Cutover" below, since `audit_logs` is one global sequence both backends may write
   to during cutover.
3. **CP4.3/CP4.6 (billing money math)** — `_resolve_bill_item_source`'s 3-branch price
   derivation and the claim amount-cap rule are the two places a subtle bug produces a
   wrong dollar figure, not a crash. `Decimal(str(...))` conversion (never float
   round-trip) must be replicated exactly in PHP (use `bcmath` or integer-cents math
   throughout, never PHP floats for money).
4. **CP6.4 (PACS zip-bomb-safe extraction)** — PHP's `ZipArchive` has the identical
   forgeable-`file_size` risk the Python fix addresses; a naive port that trusts
   `ZipArchive`'s reported size instead of counting actual bytes read reintroduces a
   real DoS vector.
5. **CP6.6 (HL7 escape/unescape)** — must use a single combined-pattern regex-callback
   pass, not sequential `str_replace` calls (provably corrupts round-trips on input
   containing `\F\`-shaped sequences) — reuse the existing `test_hl7v2.py` cases as the
   PHP acceptance test.
6. **CP6.8 (HL7 MLLP listener as a long-lived PHP process)** — no CI4-native
   equivalent; needs an explicit standalone-daemon architecture decision (this plan
   recommends a single-threaded sequential accept loop, given the real 1–2-analyser
   scale) plus a periodic self-restart to bound PHP process memory growth over weeks.
7. **CP5.3 (voice→SOAP re-platform)** — no PHP binding for faster-whisper/CTranslate2
   exists; this is a deliberate re-platform to an external HTTP service, following the
   Ollama precedent, not a line-for-line port — budget the integration, not a rewrite.
8. **CP0.11 (LDAP concurrency gate)** — not the bind/search itself, but that Python's
   `threading.Semaphore` DoS-throttle has no PHP-FPM equivalent — needs a Redis-backed
   counter instead (Redis is already provisioned for exactly this).
9. **CP0.9 (WORM/object-lock from PHP)** — `aws/aws-sdk-php` supports
   `PutObjectRetention` directly, but common abstractions (flysystem) often don't expose
   it — drop to the raw `S3Client`, verify against the live MinIO (not AWS's simulator).
10. **CP0.2/CP7.4 (contract validation, no CI4 stub generator)** — solved by testing at
    the HTTP boundary against a frozen OpenAPI export, not by generating server code.

**Already de-risked, contrary to instinct:** the job queue (CP0.7). `jobs.py` was
deliberately built as a plain SQL polling table specifically because a future PHP port
has neither Redis-queue nor Celery — the atomic claim-one-row UPDATE ports to
`spark jobs:work` unchanged. One of the cheapest tasks in the whole plan.

## Drop / defer / do differently (not faithfully replicated)

- **32 Alembic migrations → 1 squashed CI4 baseline** (CP0.3). Port targets today's
  schema, not its history.
- **`admin.py`'s 108 KB grab-bag → decomposed by concern** into the phase that owns
  that data (staff→CP1, facility-structure→CP2, alerts/LDAP/audit→CP4), not a monolith
  "Admin phase."
- **`main.py`'s `_ensure_schema()`/flock auto-migrate-at-boot → don't port.** SQLite is
  dev-only; CI4's deploy pipeline runs `spark migrate` once at deploy time.
- **`log_context.py`'s contextvars → a plain request-scoped service** (CP7.3). PHP-FPM's
  per-request model has no cross-request leak risk to guard against.
- **`faster-whisper` → whisper.cpp HTTP sidecar** (CP5.3, deliberate re-platform,
  following the Ollama precedent already set).
- **HL7 listener's thread-per-connection + semaphore → single-threaded sequential loop**
  (CP6.8). Ponytail simplification: documented real scale is "1–2 modern analysers."
  `# ponytail: add pcntl_fork concurrency only if a second analyser genuinely connects
  simultaneously in production, not speculatively.`
- **`ai/interactions.py`'s async/sync dual-cache → collapses to one cache** (CP5.5a).
  The P4.4 bug (sync path not sharing the async path's cache) was an artifact of
  FastAPI's async/sync split — CI4 has no such split, don't reintroduce it.
- **`email_service.py`'s two near-duplicate functions → optionally collapse to one
  parameterized method** (CP7.1) — an easy simplification the port can make, not
  required.
- **Everything already flagged in `AGENTS.md`'s "Remaining backlog" stays deferred**:
  RustFS/MinIO migration, real SMP/SMS/e-klinik/Registrar integration (port today's mock
  as-is — CP1.12), P4.7's real Modality Worklist (hardware-gated), MIMS/diagnosis
  screening (no license/data), WhatsApp alerting (no real credentials). The port is not
  license to build any of these speculatively.

## Cutover / coexistence strategy

1. Freeze FastAPI's `/openapi.json` (CP0.2) as the contract of record for both backends.
2. Run a schema-driven contract harness against either `FASTAPI_BASE_URL` or
   `CI4_BASE_URL` (CP7.4) — validates at the HTTP boundary, sidestepping "no CI4
   server-stub generator."
3. Contract tests catch wire-shape drift, not business-rule bugs that return a
   validly-shaped wrong answer — mine the 55 existing pytest files' *assertions*
   (CP7.5), security-critical ones first (auth/RBAC/facility-scoping/immutability),
   then money-math (billing), then protocol correctness (HL7 round-trip).
4. **Per-module phased cutover**, not big-bang: once a module clears its contract gate
   + a UI smoke pass (web + Flutter against the CI4-backed route — a renamed JSON field
   can pass a schema check and still break a page), flip that prefix at
   `proxy/Caddyfile` from FastAPI to CI4 (CP7.7). The proxy already does prefix-based
   routing today.
5. **Hard constraint:** `audit_logs` is one global hash-chain sequence. During
   coexistence, both backends may append to it — safe only if CI4's chain-append
   (CP0.6) is byte-for-byte identical to Python's, which is why that golden-vector test
   is a gate before *any* module cuts over.
6. Bake each cut-over module ~2 weeks (FastAPI kept warm, not decommissioned) before
   considering it settled; decommission FastAPI entirely only once every module has
   cut over and baked.
7. MariaDB, MinIO, Orthanc, Caddy, backup pipeline, and the observability stack need
   **no decommissioning** — they were always stack-neutral; only the app + worker
   containers get replaced.

## Critical files to re-read when each phase starts

- `backend/app/clinical_access.py` — facility-scoping/immutability kernel (CP0.5).
- `backend/app/audit_hash.py` — frozen hash-chain wire format (CP0.6).
- `backend/app/permissions.py` — RBAC page-access matrix (CP0.5).
- `backend/app/jobs.py` — already-portable DB-table job queue (CP0.7).
- `backend/app/routers/patients.py` — largest single port task (CP1.1–1.7); split into
  sub-tasks as listed, don't attempt as one unit.
- `backend/app/routers/billing.py` — money-math correctness (CP4.3/4.4/4.6).
- `backend/reporting_engine.py` — Dataset/Field registry pattern to preserve as-is (CP4.9).
- `backend/app/ai/interactions.py` — largest AI file, 3 bundled subsystems (CP5.5a-d).
- `backend/app/hl7v2.py` + `hl7_listener.py` — protocol codec + standalone-process
  design (CP6.6/CP6.8).
- `backend/app/routers/pacs.py` — zip-bomb-safe extraction pattern (CP6.4).
- `backend/app/storage.py` — ObjectStore/WORM abstraction (CP0.9).
- `healthcare/Designing for the PHP Port.md`, `healthcare/On-Prem Architecture.md`,
  `AGENTS.md` — background/constraints this plan is grounded in.
- [[Implementation Roadmap]] — the style/format this plan mirrors.

## Verification (once execution starts, per phase)

- Each CP0 kernel piece gets its own PHPUnit suite mirroring the named FastAPI test
  file before any controller built on it is considered done.
- CP0.6's golden-vector test (fixed Python-produced canonical strings/hashes checked
  into the repo) must pass before CI4 ever appends an audit row — re-run as a standing
  CI gate, not a one-time check.
- CP6.6's HL7 codec reuses the existing `test_hl7v2.py` cases as its PHP acceptance
  test (round-trip + hand-checked spec examples, no real analyser available).
- CP4.3/4.4's billing math gets dedicated PHPUnit tests asserting the 5 live-computed
  money fields and the 3-branch price-source resolution against known fixture inputs.
- Each module phase (CP1–CP6) is gated by: PHPUnit pass → contract-test pass against
  the frozen OpenAPI spec → a manual web/Flutter smoke pass against the CI4-backed
  route → then (CP7.7) proxy cutover for that prefix.
- `backend/loadtest/locustfile.py` reused unchanged against the CI4 base URL before
  full cutover, same load profile as the original P5.2 run.
- Full-suite regression: the existing 55 FastAPI test files stay green throughout (the
  Python backend keeps serving un-cut-over modules until CP7.7 completes each one).
