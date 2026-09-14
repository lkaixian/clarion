---
title: Implementation Roadmap
type: plan
updated: 2026-09-14
tags: [plan, roadmap, clarion, campus]
---

# Implementation Roadmap — CLARION → University HealthCare

Phased plan from the current competition demo to a tender-grade system. Effort:
**S** = 1–3 person-days, **M** = 4–7, **L** = 8–15. Ordered by dependency — no phase
has a forward dependency on a later one.

This file is the live plan. No older snapshot is kept in the repo. Backbone:
[[Compliance Matrix]], [[Security Audit]], [[On-Prem Architecture]].

> [!tip] Apply the [[Designing for the PHP Port]] checklist to **every** P1–P4 task as
> you write it — retrofitting portability later doubles the CI4 estimate.

> [!note] The per-task `Status` column below is the source of truth for what's done.
> The Changelog is the narrative thread (which passes ran, key decisions, delegation
> notes). Full implementation detail is in git — search the commit log for the task id.

## Changelog

### 2026-09-14 — MinIO is dead upstream: quay.io repoint + per-service least-privilege

Found while doing a MinIO least-privilege pass (the follow-up the previous
entry's voltagent review flagged): **MinIO's Docker Hub org was pulled
entirely on 2026-09-11** (`minio/minio` + `minio/mc` both 404 there now),
the tail end of a wind-down that started Oct 2025 (stopped publishing free
images) and finished Feb 2026 (repo archived, "no longer maintained").
`docker-compose.yml`'s pinned `minio/minio:RELEASE.2025-04-22T22-12-26Z` was
**no longer pullable** — a real, current break, not hypothetical.

Evaluated actively-maintained alternatives against the one hard bar
(real S3 Object Lock COMPLIANCE enforcement — the WORM guarantee
P1.6/P2.9's audit-chain and sealed-reports immutability already ship):
SeaweedFS disqualified (COMPLIANCE-mode delete still succeeds, open bug
seaweedfs/seaweedfs#8350), Garage disqualified (Object Lock isn't
implemented at all yet), RustFS the only non-disqualified option but
alpha/RC maturity with `mc`/admin-API compatibility undocumented — the user
(rightly) wasn't comfortable landing alpha software under a compliance
path. **Decision: repoint to quay.io (MinIO's own last free-tier mirror),
revisit a real migration later** once an alternative clears alpha and
confirms tooling compat.

`docker-compose.yml`'s `minio` service now pulls
`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` — the newest tag still
on the free stream there (`latest` points at it too; everything newer is a
`.hotfix.*`-suffixed enterprise/paid build). Documented, accepted residual:
this tag predates **CVE-2025-62506** (privilege-escalation via
session-policy bypass in service accounts/STS, CVSS 8.1, fixed
2026-10-15 but never back-pushed to quay.io's free tier) — exploiting it
needs credentials for an already-restricted service account, and MinIO
stays `internal`-network-only here.

**Same session, the least-privilege pass itself:** NEW
`backend/db/minio/10-accounts.sh` + `backend/db/minio/policies/*.json`
(same shape as `backend/db/mariadb/10-accounts.sh`, P1.3's three-role
split), run by a NEW one-shot `minio-init` compose service (`quay.io/minio/
mc:RELEASE.2025-08-13T08-35-41Z` — MinIO has no `/docker-entrypoint-
initdb.d/`-equivalent first-boot-only hook, so this runs, idempotently,
every `docker compose up`). Three scoped users replace the shared root key
`backend`/`orthanc`/`backup` all used to hold: `clarion-backend` (`s3:*` on
`clarion-*` only — still broad within its own domain, since
`ObjectStore._ensure_buckets()` runs at app startup in this topology;
tightening further is gated on moving to out-of-band bucket provisioning,
already a separate tracked TODO in `docs/deployment.md`'s P1.6 section),
`clarion-orthanc` (`s3:*` on `clarion-dicom` only), `clarion-backup`
(read-only on the 6 buckets `backup.sh`'s own mirror loop already names).

Verified via `docker compose config` only (rendered env/creds/dependency
graph for `minio-init` + all three consumers, including under `--profile
backup`) — no Docker daemon running this session to boot the stack live,
same ceiling as this session's other infra changes. `backend/tests/
test_storage.py` (unaffected — mocked/local backend, not live MinIO) still
33/33.

**voltagent security-auditor reviewed this same-day and caught one real
bug:** `mc admin policy attach` (unlike `policy create`/`user add`) is not
idempotent — it errors on a policy already attached, which under `set -e`
would kill `minio-init` on every `docker compose up` after the first, and
since `backend`/`orthanc`/`backup` all gate on it completing, wedge the
whole stack from ever restarting past the first successful provisioning
run. Fixed: `attach_policy()` tolerates only that specific "already"
error class, still aborts on anything else (typo, permission problem).
Confirmed correct against mocked `mc` output covering all three cases
(fresh attach / already-attached / a real unrelated error) — no live
MinIO to test against this session. Everything else in the pass reviewed
clean: the `s3:*`-on-`clarion-*` grant covers every `ObjectStore` call
`_ensure_buckets()`/`set_retention()` make (all plain `s3:` actions, never
`admin:*`), the `depends_on` graph resolves correctly in every profile
combination, and the CVE-2025-62506 acceptance reasoning holds for an
even stronger reason than originally stated — none of the three new
accounts are service/STS accounts (the vulnerable credential type), so
the bug's precondition doesn't arise in this topology at all, not just
"is hard to reach."

### 2026-09-14 — Security Audit L6 fix + P4.7 go-live: Orthanc auth/PG/S3

**L6 fixed.** `_get_dq_alert_or_404` (data-quality alerts, P2.12) was the
one leftover unscoped-by-facility lookup P4.5's review flagged but didn't
fix (it belonged to a different, unrelated module). Now reuses
`_dq_facility_filter` — the same scope `list_data_quality_alerts` already
applies — so `acknowledge`/`resolve` 404 on a facility mismatch, same shape
as the `_get_security_alert_or_404` fix it mirrors. New test
`test_admin_acknowledge_resolve_is_facility_scoped`.

**P4.7 go-live TODOs, two of three done.** `docker-compose.yml`'s `orthanc`
service: turned on HTTP basic auth (`ORTHANC__REGISTERED_USERS`, creds from
new `ORTHANC_HTTP_USER`/`PASSWORD`) and wired the PostgreSQL index +
AWS-S3-storage plugins that were already scaffolded-but-commented — index
against the pre-existing `orthanc-postgres` service, storage against the
existing `minio` service's `clarion-dicom` bucket (the one
`app/storage.py`'s `ObjectStore` already provisions at its own boot).
`backend/app/pacs.py`'s client now sends the matching
`CLARION_ORTHANC_USER`/`PASSWORD` creds (`None` if unset — degrades to no
auth only for bare local dev against a non-compose Orthanc, never against
the real compose stack, which has auth on). Auth is explicitly documented
as defense-in-depth on top of the existing internal-network-only boundary,
not a replacement for it. Verified with `docker compose config` (no
daemon available in this session to boot the stack live — same
verification ceiling as P1.11's "not yet run" `docker compose build`).

**voltagent security-auditor reviewed both changes clean** (correctness of
the `_dq_facility_filter` reuse across every edge case, the new test
actually catching the pre-fix bug, no credential leakage in the Orthanc
wiring); two non-blocking hardening notes actioned: unescaped
`ORTHANC_HTTP_USER`/`PASSWORD` interpolated into a JSON env literal (no `"`
or `\` — documented in `.env.docker.example`, not code-fixed, deploy-trust
boundary already), and Orthanc's S3 plugin using MinIO root creds like
every other service in this stack does today (no per-service MinIO
policy/user scoping exists yet anywhere — flagged as a stack-wide follow-up
in `docker-compose.yml`, not built here).

**Real Modality Worklist remains the one open P4.7 item** — needs hardware
this environment doesn't have, same documented-gap class as the TLS
cert/thermal printer. 457/457 backend tests pass, `check_schema.py` PASS.
agy not delegated (small, judgment-heavy config + a targeted RBAC fix,
below the break-even).

### 2026-09-14 — P4.5: access-anomaly detection + AI audit-trail intelligence

**Done.** New `backend/app/security_analytics.py`, same registry-of-rules /
UPSERT-by-key shape as `data_quality.py` (P2.12) but reading `audit_logs`
instead of clinical rows, keyed on `(rule, actor, window_start)` instead of
`(entity_type, entity_id)`. NEW `security_alerts` table (Alembic
`17f8b8eec362`), `GET/POST /admin/security-alerts*` (list/summary/scan/
acknowledge/resolve/explain, mirroring the data-quality admin endpoints),
`db/security_analytics_scan.py` cron CLI.

Two rules ship this pass, both read-only heuristics over existing
`audit_logs` data with hardcoded thresholds (explicitly asks for
"no manual rule config" -- the opposite of the tender's wording that
justified data_quality.py's env-var rule-disable knob, so this module
deliberately has none):
- `distinct_patient_fanout` -- an actor touching >=20 distinct patients
  within one calendar hour (exfiltration-shaped: routine care is
  one-patient-at-a-time).
- `off_hours_access` -- an actor touching patient records 00:00-05:00 MYT
  (UTC+8, no DST). Not auto-flagged as malicious (CLARION is
  emergency-first; genuine after-hours care is expected) -- stays `info`
  unless the same actor also fanned out across >=5 patients that night.

**the tender's AI half**: `ai/audit_intelligence.py` + `POST
/admin/security-alerts/{id}/explain` -- local-LLM prose (same
`ai/local_llm.py` Ollama path as every other AI feature here) explaining
why one already-flagged alert is worth a look and a next step, from the
alert's own fields only (role/facility/rule/window/counts, never a patient
name). Same "reference aid, never an autonomous verdict" framing as
cds_hint.py/report_narrative.py -- the LLM never decides what's an anomaly,
the deterministic rules already did.

**Deliberately cut**: a third rule (flag the first time an actor's audit
rows are attributed to a facility they've never used before) was drafted
and dropped -- keying "new" off "no SecurityAlert row exists yet for this
(actor, facility) pair" floods a freshly-seeded/migrated DB with a false
positive for every pre-existing combination on the very first scan. A
correct version needs an explicit backfill/baseline step this pass didn't
have room for; the `RULES` registry is designed so adding it later is a
one-line addition. No web admin tab either -- same precedent as
data-quality alerts (P2.12), which also shipped backend/API-only.

**Real bug found + fixed while writing tests**: `SecurityAlert.window_start`
(a `TZDateTime` column) round-trips through SQLite/MariaDB as a *naive*
datetime (same documented quirk noted in this file's "small follow-ups"
section), but `off_hours_access`'s dedup key was built from a freshly
constructed *aware* `datetime` (`tzinfo=timezone.utc`). An aware and a
naive value representing the identical instant hash differently as dict
keys, so `run_scan`'s "does this alert already exist" lookup missed every
time for that rule -- every re-scan of the same night re-attempted an
INSERT and hit the `(rule, actor, window_start)` unique constraint.
`distinct_patient_fanout` accidentally avoided the same bug because its
bucket key is derived from an already-DB-read (already-naive) timestamp,
not a freshly constructed one. Fixed by making the constructed value naive
too, matching every other timestamp read back from `audit_logs`. Caught
because a two-actor same-night off-hours test failed with a real
`IntegrityError`, not a wrong-answer assertion -- worth calling out since it
would have shipped invisibly (the retry-on-IntegrityError in `run_scan`
means a single-actor scan never surfaces it; it only breaks once TWO
distinct actors are flagged for the same historical night, which single-
actor manual testing would never exercise).

**voltagent security-auditor reviewed the diff** and found four real
issues, all fixed before this landed:
1. **Facility misattribution** -- both rules bucketed by `(actor, window)`
   only and resolved a single `actor_facility` via "last non-null wins"
   over an unordered row set; `AuditLog.actor_facility` is a per-row
   snapshot (a transferred/multi-site actor can legitimately carry
   different facilities across rows), so the picked facility -- the exact
   field `_security_alert_facility_filter` uses to decide which
   facility-scoped admin even sees the alert -- was arbitrary. **Fixed**:
   `actor_facility` joined the bucket key (and the DB's own unique
   constraint, `uq_security_alerts_rule_actor_facility_window`), so an
   actor touching two facilities in one window now produces two alerts,
   one per facility -- covered by a new test.
2. **Unbounded auto-resolve vs. wall-clock time** -- `latest = max(audit_logs.timestamp)`
   drove both the lookback window and the auto-resolve cutoff with no
   sanity check against real time; one clock-skewed or bad-seed row with a
   future timestamp would push `latest` forward and silently auto-resolve
   every open alert in the next scan. **Fixed**: `latest` is now clamped to
   `min(latest, now)`.
3. **Redundant queries** -- each rule independently re-queried `latest` and
   the full lookback row set, doubling the "load N hours of audit_logs"
   cost the module's own docstring said it was written to avoid. **Fixed**:
   `run_scan` computes both once and passes them into every rule (`Rule.fn`
   signature changed from `Callable[[Session], ...]` to
   `Callable[[list, datetime], ...]`).
4. **Cross-facility mutation via `acknowledge`/`resolve`/`explain`** -- these
   three endpoints looked up an alert by id alone, no facility filter (list/
   summary were already correctly scoped). If an alert id ever reached a
   facility-scoped admin outside normal channels (a shared triage note, a
   screenshot), they could acknowledge/resolve/overwrite the AI explanation
   on another facility's security incident -- for `explain` specifically a
   *write*, not just a read. **Fixed**: `_get_security_alert_or_404` now
   404s (not 403, to avoid confirming existence) on a facility mismatch,
   covered by a new test. **Noted, not fixed here**: the reviewer found the
   identical unscoped pattern already shipped in `_get_dq_alert_or_404`
   (data-quality's own acknowledge/resolve, P2.12) -- pre-existing, not a
   P4.5 regression, but a real gap worth a follow-up pass; tracked in
   AGENTS.md's leftovers.

Also confirmed clean: no naive/aware datetime collision (the fix from
writing tests -- see below -- is complete, verified line-by-line), no
information exposure in the LLM prompt (only role/facility/rule/window/
counts, never the actor id or a patient value), no SQL correctness issue
beyond the redundancy in #3. Left as a documented (`ponytail:`-tagged)
limitation, not fixed: `distinct_patient_fanout`'s hourly buckets are
tumbling, not sliding, so a burst straddling an hour boundary (e.g. 19
patients at 10:50, 19 more at 11:00) can under-count against the 20/hour
bar -- a real detection gap at the margin, not a correctness bug, and a
sliding window is a meaningfully bigger change than this pass's scope.

**Real bug found + fixed while writing the first draft of these tests**
(independent of the voltagent pass above): `SecurityAlert.window_start` (a
`TZDateTime` column) round-trips through SQLite/MariaDB as a *naive*
datetime (same documented quirk noted in this file's "small follow-ups"
section), but `off_hours_access`'s dedup key was originally built from a
freshly constructed *aware* `datetime` (`tzinfo=timezone.utc`). An aware
and a naive value representing the identical instant hash differently as
dict keys, so `run_scan`'s "does this alert already exist" lookup missed
every time for that rule -- every re-scan of the same night re-attempted an
INSERT and hit the unique constraint. `distinct_patient_fanout` accidentally
avoided the same bug because its bucket key is derived from an
already-DB-read (already-naive) timestamp, not a freshly constructed one.
Fixed by making the constructed value naive too. Caught because a two-actor
same-night off-hours test failed with a real `IntegrityError`, not a
wrong-answer assertion -- it would have shipped invisibly otherwise (the
retry-on-IntegrityError in `run_scan` means a single-actor scan never
surfaces it; it only breaks once TWO distinct actors are flagged for the
same historical night).

**Test-architecture correction, also found while iterating**: the rule/scan
tests originally ran against the shared conftest session DB (like the
admin-endpoint tests). Because `run_scan` deliberately queries `audit_logs`
GLOBALLY with no scoping, that made assertions hostage to whatever
timestamp every other test's audit rows happened to carry -- exactly the
failure mode `test_data_quality.py` already solved for its own rule/scan
tests via an isolated throwaway migrated SQLite DB per test
(`_throwaway_db`/`fresh_db`). `test_security_analytics.py` now follows the
same split: rule/scan logic against an isolated DB, admin-endpoint tests
(hand-built alert rows, no scan involved) against the shared conftest DB.

Verified: `backend/tests/test_security_analytics.py` (10 tests -- rule
logic, hardcoded thresholds, multi-facility bucketing, UPSERT/times_seen,
auto-resolve-on-window-rotation, pseudo-actor exclusion, a throwing rule
not aborting the scan) + `backend/tests/test_admin_security_alerts.py` (5
tests -- RBAC, facility-scoping by `actor_facility`, cross-facility
acknowledge/resolve/explain all 404, explain caching, explain
graceful-degrade), `db/check_schema.py` PASS (autogen zero-ops, downgrade
round-trip clean) after widening the unique constraint, full suite
456/456. agy not delegated (judgment-heavy: choosing real, defensible
heuristics and thresholds, not mechanical).

### 2026-09-14 — P4.4: medication-safety engine, ATC class layer + real-time pre-save alert

**Done.** Closes the two concrete gaps the Compliance Matrix flagged for
: the DDI/allergy checks were name-matching only, and nothing was
wired as a pre-prescription real-time alert.

**ATC drug-class layer** (`backend/app/ai/interactions.py`) — `RxClass`
(free NIH/NLM data, same family as the already-used RxNorm/DailyMed) resolves
a medication to its ATC classIds; `RISK_CLASS_PREFIXES`/`CLASS_INTERACTIONS`
generalize the existing named-pair `KNOWN_INTERACTIONS` table to therapeutic
classes (e.g. any NSAID + any anticoagulant/antiplatelet, not just the
specific pairs listed by name) — `check_interactions` tries the named table
first, falls back to the class table. Every class code used was checked live
against RxClass for its example drugs before being hardcoded (not guessed).
Explicitly did **not** attempt a licensed formulary integration (MIMS) — no
public API, requires a paid clinical-data license, same call as declining a
fabricated ICD-10/MyDrug/LOINC seed list at P4.1/P4.2.

**Class-aware allergy check** — `ai/cds_hint.py`'s allergy-conflict flag was
plain-substring-only (a "Penicillin" allergy did not catch an "Amoxicillin"
prescription). Moved it to `interactions.py` as `check_allergy_conflicts`
(now shared with the new endpoint below, so the two panels can't disagree)
and added a second, class-based check via `ALLERGY_CLASS_PREFIXES` — a
*synchronous*, separate RxNorm/RxClass path (`resolve_drug_classes_sync`),
deliberately not reusing the async `MedicationProvider`'s event-loop-bound
client, since this is called from both a sync route (cds-hint) and, via
`run_in_threadpool`, an async one (prescription-screen) — sharing a client
across those would risk a cross-event-loop error.

**Real-time pre-save alert** (`GET /ai/prescription-screen/{patient_id}`,
`backend/app/routers/ai_router.py`) — screens a candidate drug name that has
**not been saved yet** against the patient's active medications + allergies.
Wired into the Add Medication modal (`web/src/pages/PatientDetail.jsx`):
Save first runs the screen; if it finds anything, the form shows the
findings and requires a second click ("Add anyway") to actually persist —
the tender's literal "real-time alerts before confirmation" ask. Fails open
on a screening-service outage (never blocks a save over an optional check
being down), same discipline as the existing Interaction Check panel.
Editing an existing medication's dose/frequency does not re-trigger the
screen — only adding a new one does.

**Deliberately out of scope:** diagnosis-based screening (the tender's
clause text also says "existing diagnoses") — a real drug-contraindicated-
by-condition table needs clinical validation this environment can't provide
without fabricating data, so it's not attempted; Compliance Matrix stays
Partial for that reason alone.

**voltagent security-auditor reviewed the diff** (RBAC/facility-scoping
parity with the existing interaction-check endpoint, injection/SSRF in the
new sync RxNorm/RxClass calls, fail-open behavior, frontend state) — no RBAC
leak, no injection, no fail-closed regression, no test regression. One real
finding: `resolve_drug_classes_sync`'s cache key namespace never overlapped
the async path's, so `GET /ai/prescription-screen` resolved the same
candidate drug through RxNorm/RxClass **twice** per request (once via
`check_interactions`, again via `check_allergy_conflicts`) instead of
sharing the hit — undermining the exact caching rationale the 2026-09-07
code-review comment in this file exists to explain. **Fixed**:
`resolve_drug_classes_sync` now reads/writes the identical
`("resolve_rxcui", ...)`/`("get_drug_classes", ...)` cache keys the async
provider methods use, not a separate namespace — a drug already resolved
earlier in the same request is a cache hit, not a second round trip.

Verified: new `backend/tests/test_interactions.py` (9 tests, including a
regression test that asserts `resolve_drug_classes_sync` makes zero HTTP
calls for a drug the async path already cached — the exact scenario
voltagent's finding described; RxNorm/RxClass calls monkeypatched
throughout, no live network dependency in CI), existing `test_cds_hint.py`
(3 tests) still pass unchanged, full suite 441/441, `npm run build` clean.
agy was not delegated here — this was judgment-heavy (choosing/verifying
real ATC class codes, layering two rule engines without duplicating logic),
below the break-even for a mechanical hand-off.

### 2026-09-14 — P4.1 + P4.2: FHIR coding triples + read-only façade

Both **done**. Per [[FHIR Schema Readiness]]'s "annotate + thin façade, don't
restructure" recommendation — no new resource tables, no terminology
server; CLARION's existing Condition/MedicationStatement/AllergyIntolerance/
Encounter/ServiceRequest/ServiceResult/ClinicalDocument tables already are
FHIR-shaped, they just needed codes.

**P4.1**: nullable `code_system`/`code_code`/`code_display` triples added to
`conditions`, `medication_statements`, `allergy_intolerances` (`code_display`
only on `service_catalog_items`, whose existing free-text `code` doubles as
`code_code`). NEW `resource_identifiers` table (repeatable patient
identifiers — MRN, future MHNexus id — beyond the single `national_id`
column): this is the concrete mechanism behind the tender's "MySejahtera/
PADU later = zero table changes" claim. NEW `app/fhir_terminology.py` —
an allowlist of code-system URIs, deliberately **no seed ICD-10/MyDrug/
LOINC code list**: those are licensed/MOH-provided reference data, not
something to fabricate for a demo (a wrong hand-rolled medical code is worse
than an honest gap). Alembic `a3f7c92e6b1d`. Skipped the roadmap's other
"new tables the modules need anyway" (`observations`, `diagnostic_reports`,
`procedures`, `immunizations`, `document_references`) — every one either
already has a real CLARION table backing it (ServiceResult ↔
Observation/DiagnosticReport, ClinicalDocument ↔ DocumentReference) or, for
`immunizations`, backs a module that doesn't exist in CLARION at all
(checked [[Module Coverage]]/[[Compliance Matrix]] — not a mandated module,
so no consumer would ever populate it).

**P4.2**: NEW `backend/app/routers/fhir.py` — GET-only R4 façade
(`/fhir/metadata` CapabilityStatement + `/fhir/{Type}/{id}` +
`/fhir/{Type}?patient={id}` search Bundles) over Patient, Condition,
MedicationStatement, AllergyIntolerance, Encounter, ServiceRequest,
DiagnosticReport (from ServiceResult), DocumentReference (from
ClinicalDocument). Reuses the exact access policy already audited for GET
/patients/{id} (`clinical_access._patient_known_to_facility` +
`audit.log_access`, `routers/patients.py::get_patient_full_record`): any
authenticated staff member with the `patients` page can read any patient
(cross-hospital continuity), a cross-facility read gets a distinctly-logged
audit action instead of being blocked, and the `patient` role is denied
outright (404) rather than wired to a narrower self-service scope — nothing
consumes that yet. Registered in `main.py` behind the same
`require_page_access("patients")` gate as `patients.router`/`ai_router`, no
new page. Skipped an ImagingStudy resource for `DicomStudy` — that's P4.7's
own domain (`routers/pacs.py` already has a purpose-built API), adding a
second one here would be scope creep, not readiness.

**agy used** for the mechanical part: wrote `backend/tests/test_fhir_facade.py`
(9 tests: read + patient-scoped search Bundle for all 8 resources, 404 on a
nonexistent patient, 404 on the `patient`-role self-service attempt, the
metadata route's page-gate) from a spec naming the exact fixtures to reuse
(`conftest.py`'s `test_client`/`db_session`/`make_user`/`auth_headers`,
`_facility`/`_make_patient`) and the exact assertions — Claude wrote every
resource mapper/route (the security-relevant half: the facility-scoping
call, the 404 postures) directly rather than delegating it. Verified,
per the project's own agy-flakiness lesson: read every line before trusting
it (all 9 assertions matched real fixtures, nothing hallucinated), then
re-ran the file myself rather than trusting agy's self-reported pass — real
result **9/9 passed**.

Verified: `backend/db/check_schema.py` PASS (autogen-empty + downgrade/
upgrade round-trip) with `a3f7c92e6b1d` at head; full backend suite
**432/432** (423 prior + 9 new); `npm run build` clean (unaffected, no web
change this task).

**Also this session:** re-ran an independent, from-scratch voltagent
security-auditor pass over all of P4.7 (PACS/DICOM) as a sanity check —
this session had no access to whatever review session originally produced
the "voltagent security review caught one real bug" note below, so rather
than take that changelog entry's word for it, a fresh reviewer re-derived
the zip-bomb fix and the facility-scoping reuse from the actual code paths
independently. **Confirmed sound, no new findings**: the bounded-streaming
zip guard genuinely never trusts `ZipInfo.file_size`, `_study_or_404`/
`_request_or_404` facility-scoping matches the already-hardened
`ancillary.py` pattern byte-for-byte, Orthanc stays internal-network-only
with no attacker-reachable SSRF path, and the DICOM viewer has no unsafe
frontend sink. Two informational nits noted (a zip edge-case exception type
not caught, falls through to the generic 500 handler; a missing app-level
lock lets a concurrent double-upload race `IntegrityError` into a 500
instead of 409) — both cosmetic, not fixed, not security bugs.

### 2026-09-14 — P4.7 core: DICOM imaging (upload + embedded viewer)

The last unstarted top-5 demo priority ("DICOM viewer — open a chest X-ray
inside a record, zoom & measure"). Deliberately a **scoped core slice, not
the full clause**: real DICOM ingest from a modality via IHE Modality
Worklist + accession-number auto-link ([[PACS and DICOM]]'s documented
workflow) needs hardware this environment doesn't have, same class of gap
as P1.9's TLS cert / P3.9's thermal printer — tracked as a go-live TODO, not
built. What *is* real: an actual on-prem Orthanc DICOM server storing
actual DICOM Part10 data, served through this app's own RBAC, viewable
with real zoom/pan/window-level/measure tools — not a mock.

NEW `backend/app/pacs.py` (thin Orthanc REST client, same on-prem-only
`_is_on_prem_host` guard class as `ai/local_llm.py`) + `backend/app/routers/
pacs.py` (the auth boundary in front of Orthanc, which has no per-user auth
of its own in this demo config — safe only because it's `internal`-network-
only in docker-compose.yml, never host-exposed). A DICOM study (`.dcm` or a
`.zip` of one study's instances) is uploaded against an already-placed
X-ray `ServiceRequest`, gated to the same `SIGNOFF_ROLES` +
`_request_or_404`/`_hidden_author_facilities` facility-scoping ancillary.py
already uses for result documents -- reused directly, not reimplemented.
NEW `models.DicomStudy` (one per ServiceRequest, stores the Orthanc study id
+ its own instance-id list -- the source of truth
`GET .../study/instances/{id}/file` checks a requested id against, so a
caller who can see study A can never read study B's pixel data by
supplying a real-but-foreign instance id). Alembic `4c1cb27217d3`.

Web: `web/src/components/DicomViewer.jsx` embeds `dwv` (MIT -- the library
[[PACS and DICOM]] names for this), loading each instance straight from the
authenticated backend proxy via dwv's own `requestHeaders` option (no
separate blob-fetch step). Wired into `Ancillary.jsx`'s X-ray rows: an
upload control before a study exists, a "View imaging" button after.
`dwv`'s exact API (ViewConfig/AppOptions/App, `loadURLs` requestHeaders
shape, tool names, the Draw+Ruler measure tool) was verified against the
library's own source on GitHub before writing the component, not
guessed -- confirmed `App`/`AppOptions`/`ViewConfig` are real exports via
the installed package's `.d.ts`.

**voltagent security review caught one real bug, fixed:** the zip upload
path's bomb guard summed `ZipInfo.file_size` -- an attacker-controlled
central-directory field zipfile never cross-checks against the real
decompressed size until after fully decompressing -- so a hand-forged
small declared size could hide a multi-GB real deflate stream past the
check, and the extraction wasn't offloaded to a threadpool, so it would
have also stalled the whole event loop. Fixed: bounded streaming reads
(`zf.open(info)` in 1MB chunks, aborting the instant real bytes exceed a
shared running budget, never consulting `file_size`) + `run_in_threadpool`.
New regression test reproduces the exploit shape (tiny compressed zip,
oversized real payload) and confirms the 413.

**agy note:** delegated the deployment-docs write (`docs/deployment.md`,
fully-specified single-section insert) -- failed outright, needs an
interactive Google OAuth sign-in this headless session can't do. No files
touched by agy; Claude wrote the docs directly instead (small enough that
waiting on agy auth wasn't worth it).

Verified: `backend/tests/test_pacs.py` (14, incl. the zip-bomb regression),
full backend suite 423/423, `check_schema.py` PASS (autogen-empty +
downgrade/upgrade round-trip), `pyflakes` clean, `npm run build` + `oxlint`
clean. **Not done here:** enabling Orthanc's Postgres index/S3-storage
plugins (compose already provisions them, commented out) and Orthanc's own
auth -- both documented as go-live TODOs in `docs/deployment.md`, tracked
under P4.7 in the phase table below (still 🟡, not ✅, for exactly this
reason).

### 2026-09-14 — P4.3c finished: NL report narrative

The one remaining piece of P4.3c (voice→SOAP landed earlier the same day —
see the entry below). NEW `backend/app/ai/report_narrative.py`: takes
`reporting_engine.run_report()`'s already-structured, already-facility-
scoped, already-anonymized-if-requested result (columns + rows) and asks
the local LLM (`ai/local_llm.py`, same engine every other P4.3 feature
uses) for a 3-5 sentence prose narrative — explicitly told to use only the
numbers in the table, never invent a figure. Capped at the first 30 rows
into the prompt (the engine's own `_MAX_ROWS=5000` already bounds the
query); `None` on any Ollama failure, same never-raise contract as
`cds_hint.py`/`summarize.py`, so the table itself is never blocked on it.

NEW `POST /reports/narrative` (`routers/reporting.py`) — same
`ReportRunRequest` body, same `REPORTING_ROLES` gate and facility scoping
as `/reports/run`/`/reports/export` (reuses the router's existing `_run()`
helper, so there's no second code path to drift), `report_narrative_generated`
audit action with dataset+row-count only (no clinical values, matching the
M8 rule). Web: `Reporting.jsx` gained a "✨ Narrate" button next to the
export buttons and a narrative block above the table, with the disclaimer
shown alongside; `client.js` `narrateReport`.

**Incidentally fixed while verifying the web build:** `HospitalSettingsTab.jsx`'s
logo-upload handler had `await` inside a plain (non-async) `setForm`
updater callback — a pre-existing bug from the P3.9 commit that failed
`npm run build` outright (not a runtime-only bug — the whole production
build was broken). Resolved the data URL before calling `setForm`.

voltagent security-auditor reviewed the new endpoint (RBAC/facility-scope
reuse, prompt-injection exposure, PII/audit-log hygiene, DoS/row-cap,
consistency with `/reports/run`/`/export`) — verdict: clean, no findings.
Verified: full backend suite 409/409 pass, `pyflakes` clean, `npm run
build` clean.

**P4.3 (on-prem AI engine, all sub-parts) is now fully done** — see P4.3's
row in the phase table below.

### 2026-09-14 — P3.9 + P3.10: calling-system hardware + mobile booking/vitals/PDF/announcements

Both remaining P3 rows, done together (share the same review/verify pass).

**P3.9**: NEW `backend/app/printing.py` — pure-
stdlib ESC/POS queue-ticket byte formatter + Pillow+`qrcode` sample-label
PNG builder (QR stands in for Code128 — this codebase already depends on
`qrcode`, not a barcode-symbology lib, and has no Code128 reader anywhere).
`GET /reception/queue/{id}/ticket.escpos`, `GET /ancillary/requests/{id}/
label`, web "Print ticket"/"Label" buttons. No thermal/label printer
attached in this environment — wiring the bytes to real hardware is a
documented deploy-time step, same call P1.9 made for the TLS cert pair.
TV display: `HospitalSetting.brand_primary_color`/`logo_data_url` (small
inline data URI, not a new ObjectStore bucket — cosmetic/non-clinical/not
WORM) + Web Audio chime/SpeechSynthesis call-out on `WaitingRoomDisplay.jsx`
when a ticket transitions to "called".

**P3.10**: `Appointment.department/clinician_id/
self_booked` + `GET /patients/appointment-slots` (fixed 30-min grid within
Malaysia-local clinic hours, recomputed server-side on both list AND book
so a double-booking race / out-of-hours booking is actually prevented) +
`GET /patients/booking-options` + `POST .../self-book`. `ConsultationNote`
gained `bp_systolic/diastolic/temperature_c/pulse_bpm`, captured in the
existing SOAP sign-off flow and surfaced on the patient's own record read
(previously staff-only per-facility — see `_serialize_encounter`).
Visit-summary PDF rendered on the fly from an already-signed
Encounter/ConsultationNote (reuses the P3.5 reportlab pattern, zero new
dependency, deliberately not stored as a second WORM copy). NEW
`Announcement` model + admin CRUD + patient read, filtered to
currently-live ones server-side — **real-time alerts use the EXISTING
`RemindersProvider` polling pattern, not FCM/push**: no Firebase project
available, and polling keeps the on-prem/no-third-party-cloud posture this
project has held everywhere else (P4.3's local-LLM wave, P1.9's edge proxy,
etc.). Flutter: NEW `book_appointment_screen.dart` (facility picker sourced
from the patient's own encounter history — no facility-directory endpoint
exists anywhere in this system, documented limitation not a bug — →
department → clinician → date → slot), home_screen.dart encounter card
gained department/vitals/diagnosis lines + a per-encounter PDF share button
(`share_plus`, the one new pubspec dependency — Bearer-auth means a plain
`url_launcher` can't fetch the PDF), reminders_screen.dart gained an
Announcements section. l10n: every new string in all 4 languages.

Backend: 1 additive Alembic migration (`e1c0629c392f`), verified full
downgrade/upgrade round-trip + autogenerate-empty on SQLite. NEW
`backend/tests/test_p3_9_p3_10.py` (17 tests) — full suite 401/401 pass.
Flutter: `flutter analyze` clean (0 errors/warnings beyond pre-existing
style infos), `flutter pub get` resolves cleanly.

**Caught and fixed during implementation** (the kind of thing this
project's review discipline exists for):
- `GET /patients/appointment-slots` was originally defined on
  `appointments.router`, which shares the `/patients` prefix with
  `patients.router` but is included into the app AFTER it — `patients.
  router`'s `GET /{patient_id}` would have silently swallowed
  "appointment-slots" as a patient_id before the real route was ever
  reached. Fixed by moving both new literal routes onto `patients.router`,
  ahead of `/{patient_id}` (see the inline comment there for the rule going
  forward: any literal top-level `/patients/...` route belongs on that
  router, never a sibling one sharing the prefix).
- A vitals-only sign-off (no SOAP text typed) would have silently dropped
  the vitals — `consultation.py`'s `structured_values` guard only checked
  the SOAP fields before vitals were added to it.
- `_serialize_appointment`'s manual response dict was missing the 3 new
  `Appointment` fields, so a successful self-book response reported
  `self_booked=false` back to the caller (data was correct in the DB, only
  the echo was wrong) — caught by the test suite, not by inspection.

Delegation note: the mobile Flutter work was originally planned for
antigravity (agy) per this project's usual split, but agy's `--yolo`
(needed for file-write permission) was blocked outright by the harness's
own safety classifier this session — built directly by Claude instead.

**voltagent security-auditor + flutter-expert review actioned (2 Medium/
High-equivalent + 1 Critical, all fixed):**
- **[Critical, flutter-expert]** `compute_available_slots` returned NAIVE
  UTC datetimes; Pydantic serializes those with no 'Z'/offset suffix, which
  Dart's `DateTime.parse` silently mis-parses as LOCAL time -- chased
  through `ApiClient.selfBookAppointment`'s `.toUtc()` call, this produced
  a real double-shift that made self-booking 409 on essentially every
  attempt from an actual Malaysia-timezone device. Fixed by returning
  AWARE UTC datetimes from `compute_available_slots` instead (confirmed
  Pydantic then emits a literal `Z` suffix, which Dart parses correctly
  with zero Dart-side changes needed) -- `_to_aware_utc` (renamed from
  `_naive_utc`) now converts rather than strips tzinfo, fixing the
  reviewer's related minor observation about a genuinely-offset client
  payload too.
- **[Medium, security-auditor]** `self_book_appointment`'s slot check was
  read-then-write with no DB-level guard -- the same concurrent-threadpool
  race `models.QueueTicket`'s own docstring warns about. Fixed with
  `Appointment.active_clinician_slot_key` + `uq_appointments_active_
  clinician_slot`, the identical VIRTUAL-generated-column pattern P1.3's
  RoomClaim already established (migration `aa914ee7cc2f`), plus a
  catch-`IntegrityError`-and-409 in the router (no retry-with-a-different-
  slot, unlike ticket numbering -- the patient asked for one specific time).
- **[Low-Medium, security-auditor]** `printing.py`'s ESC/POS text encoder
  passed ASCII control bytes -- including its own ESC/GS command-introducer
  bytes -- through unfiltered from `QueueTicket.department`/`HospitalSetting.
  display_name`, letting a receptionist/admin inject raw printer commands
  (cash-drawer-open, paper-waste DoS, lock-ups) into every subsequently
  printed ticket. Fixed by stripping `\x00-\x1f`/`\x7f` in `_escpos_line`,
  the one place every text field funnels through.
- **[High, flutter-expert]** `book_appointment_screen.dart` had a
  stale-response race (no guard against an older facility/slot fetch
  landing after a newer one) and the department/clinician dropdowns
  cleared `_slots` on change without ever re-fetching, leaving the slot
  list stuck empty. Fixed with a monotonic per-request-type id checked
  before each `setState`, plus calling `_loadSlots()` from both `onChanged`
  handlers.
- Also actioned: `reminders_provider.dart::syncAnnouncements` fetched
  per-facility sequentially (`Future.wait` now), and a `ponytail:` comment
  on `home_screen.dart`'s un-cleaned share-temp-file (deliberately not
  auto-deleted -- the OS share sheet can still be reading it after
  `shareXFiles` returns).

Both reviews' remaining findings were reviewed and found to already be
correctly handled (access control on the new endpoints, cross-facility
visibility, announcement/facility scoping, `_BulletLine`'s additive params,
`mounted` checks, `DropdownButtonFormField.initialValue` re-sync) -- see
the review transcripts for detail if revisiting this wave. Regression
tests added to `test_p3_9_p3_10.py` (21 total now) for every backend fix;
`flutter analyze` re-run clean after the Dart fixes. Compliance Matrix /
Module Coverage already updated to reflect P3.9=Demo-on-hardware /
P3.10=Have.

### 2026-09-13 — P4.3c Voice→SOAP (demo priority #2)

New second local model alongside the Ollama LLM: `faster-whisper`
(CTranslate2, MIT — pinned `1.2.1` in `requirements.txt`) transcribes a
clinician's dictation, then the same local LLM (`ai/local_llm.py`)
segments the transcript into SOAP fields. Fully local after the one-time
model download (same category as `ollama pull`, see `docs/deployment.md`).

NEW `backend/app/ai/voice_soap.py`: `transcribe()` (lazy, process-wide
`WhisperModel` singleton; `CLARION_WHISPER_MODEL`/`CLARION_WHISPER_DEVICE`
env-configurable, `int8`/CPU by default so it runs on a demo laptop with
no GPU) and `structure_as_soap()` (strict-JSON prompt, same
parse-defensively pattern as `ai/nric_ocr.py`). Never loses what was said:
a segmentation failure still returns the full transcript in `subjective`
rather than dropping it. NEW endpoint `POST
/consultation/tickets/{id}/voice-to-soap` (multipart audio upload, 15MB
cap via the existing `enforce_upload_size` helper, same room-claim gate as
sign-off and cds-hint, blocking work off-threaded via
`run_in_threadpool`) + schemas `SoapDraftOut`/`VoiceToSoapOut`.

Web: `CompleteConsultationModal` gained a "🎙 Dictate SOAP" button using
the browser's native `MediaRecorder` API (no new frontend dependency) —
records, uploads the blob, fills only the SOAP fields still empty (never
silently overwrites text the clinician already typed), and shows the raw
transcript for reference. Recording is stopped on modal unmount so a
dropped session doesn't leave the mic open.

Verified: NEW `backend/tests/test_voice_soap.py` (7 tests — model-
unavailable degrades cleanly at both `transcribe()` and the full
`voice_to_soap()` pipeline, JSON segmentation happy path, unparseable-JSON
and LLM-unavailable both fall back to the raw transcript, the endpoint
round-trips a mocked transcription end-to-end, 409 when the caller hasn't
claimed the ticket's room). None of this touches real Whisper weights —
offline-CI-safe (P2.11) regardless of whether `faster-whisper` happens to
be installed. Full backend suite green, web build clean, `pyflakes` clean.

**voltagent security-auditor review:** one Medium, one Low, rest clean.
Medium — the 15MB upload cap bounds bytes, not audio *duration* (a
low-bitrate clip packs a long recording into few bytes), so an over-long
clip could tie up a shared threadpool worker for minutes; also flagged
in-process media decoding (PyAV/ffmpeg, a decoder family with a CVE
history) as a longer-term hardening item. Fixed the duration side:
`_duration_seconds` (via PyAV container metadata, already a
`faster-whisper` transitive dep) refuses a clip over
`CLARION_WHISPER_MAX_SECONDS` (default 600s) before the expensive
`model.transcribe` call — best-effort (proceeds if duration can't be read,
so a legitimate short clip with unusual container metadata isn't wrongly
rejected). **Accepted as a residual, matching existing precedent:**
in-process decoding without subprocess isolation — every other upload path
in this codebase (Pillow for images/PDFs, Tesseract, RxNorm's httpx calls)
runs the same way, in the same process, with no sandboxing; this endpoint
is also only reachable by an authenticated clinician account (same trust
level as those), not the public internet. Low finding (a transient
model-load failure latches "unavailable" until process restart) — no fix,
availability nit only, matches the existing degrade-forever design of
every other `ai/` lazy-load.

Verified again: NEW 2 tests (over-duration clip refused without reaching
the model, unknown-duration clip still proceeds) — 9/9 in
`test_voice_soap.py`, full backend suite green, `pyflakes` clean.

**voltagent ponytail-review + code-reviewer pass, same session:**
ponytail-review cut `schemas.SoapDraftOut` (one-caller wrapper model —
`VoiceToSoapOut.soap` is now a plain `dict[str, str]`) and collapsed
`voice_soap.py`'s two-variable model-load-singleton into one `_UNSET`
sentinel — which caught a real bug the "simplification" itself would have
introduced (the faster-whisper-not-installed branch never wrote `_model`,
so every call would re-attempt the import instead of caching "unavailable"
once); fixed before it shipped. Considered and **rejected** a third
finding (extracting `MAX_AUDIO_UPLOAD_BYTES` as a "duplicate" of
`ai_router.py`/`self_registration.py`'s own upload caps) — `self_registration.py`
already documents why each endpoint keeps its own named cap rather than a
shared one; not real duplication. code-reviewer pass found one real Medium:
a race in `PatientList.jsx` where closing the modal while the browser's
mic-permission prompt was still pending left `isMountedRef`-less code with
nothing to stop, so granting permission after the modal was gone would
start (and never stop) recording. Fixed with an `isMountedRef` guard
checked after the `getUserMedia` await and in the `onstop`/catch paths.
Added the 2 tests code-reviewer flagged as a coverage gap (the markdown
code-fence-stripping path in both `voice_soap.py` and `nric_ocr.py` was
real, previously-untested logic). Final tally: 384/384 backend tests
passing, web build clean, `pyflakes` clean.

**Not done here:** NL report narrative (the other P4.3c item) — a smaller,
separate piece (local LLM over Reporting engine's already-structured
output), not started.

### 2026-09-13 — P4.3b CDS hint (demo priority #1)

New clinician-facing reference aid, built on P4.3's local-LLM plumbing —
NOT a diagnosis or prescription decision (every open-weight model's
acceptable-use terms forbid that; framed explicitly as advisory in the UI
copy and a fixed `disclaimer` field). NEW `backend/app/ai/cds_hint.py`:
`generate_cds_hint(patient, draft_note, reason)` builds a prompt from the
patient's active/chronic conditions, allergies, active medications, reason
for visit, and whatever SOAP text the clinician has typed so far (never
persisted before sign-off), asks `ai/local_llm.py` for 2-4 short
"things to consider" bullets. Separately, `_allergy_conflicts` does a
deterministic (no LLM) case-insensitive substring match between recorded
allergy substances and active medication names — medication-safety
screening stays a rule-engine job per the vault's stack table, real
drug-class awareness is P4.4 (licensed drug DB), this is a cheap floor.

NEW endpoint `POST /consultation/tickets/{id}/cds-hint` (schemas
`CdsHintRequest`/`CdsHintOut`), gated by the same room-claim ownership
check as sign-off (`_ticket_in_my_room_or_404`) — reuses
`routers/patients.py::_serialize_patient` for patient context (same
already-shared-across-routers helper `ai_router.py` uses for the
interaction-check endpoint) so the existing `records_shared_publicly`
opt-out filtering applies here too, no new privacy logic. Callable
repeatedly while drafting, writes nothing, logged via `log_access`.

Web: `CompleteConsultationModal` (`web/src/pages/PatientList.jsx`) gained a
"Get CDS hint" button that sends the in-progress SOAP fields and renders
the hint, any allergy-conflict warnings, and the disclaimer inline —
`getCdsHint` in `api/client.js`.

Verified: NEW `backend/tests/test_cds_hint.py` (3 tests — LLM hint +
allergy conflict together, hint absent but conflict check still runs when
the local model is unavailable, 409 when the caller hasn't claimed the
ticket's room); `web/` build clean; full backend suite green.

**Not done here (P4.3c):** `faster-whisper` voice→SOAP, NL report
narrative — separate, larger features, not started.

### 2026-09-13 — P4.3 On-prem AI engine, core (Security Audit C1 resolved)

Replaced every Claude-API call with a local Ollama client. NEW
`backend/app/ai/local_llm.py`: thin `httpx` wrapper around Ollama's
`/api/generate` (text + vision via base64 `images`), never raises — any
failure (server down, model not pulled, timeout, bad JSON) returns `None`
so callers fall back exactly as before. Opt-**out**, not opt-in
(`CLARION_DISABLE_LOCAL_AI`) — unlike the old cloud guard, nothing here
ever leaves the machine, so there's no data-sovereignty reason to default
it off.

`ai/summarize.py` and `ai/nric_ocr.py` rewired onto it; `ai/_cloud_guard.py`
**deleted** (nothing left to guard); `anthropic` dropped from
`requirements.txt`. `docker-compose.yml` backend service points at
`host.docker.internal:11434` by default (Ollama needs the GPU directly, so
it runs on the host, not as a compose service) + `extra_hosts` for
Linux/Mac/Windows parity. `.env.example` / `.env.docker.example` swapped
the "Cloud AI opt-in" block for local-model config. `docs/deployment.md`
gained an "On-prem AI engine" section with the one-time `ollama pull`
host-setup steps. Stale `_cloud_guard.py` cross-references fixed in
`ldap_auth.py` / `schemas.py` / `self_registration.py` comments.

**voltagent security-auditor review: clean (no Critical/High/Medium).** One
Low/informational finding actioned: `CLARION_LOCAL_LLM_URL` had no runtime
check that it actually points at an on-prem host — not attacker-reachable
today, but a copy-paste deploy mistake (pasting a cloud/tunnel URL into
`.env`) would have silently reintroduced C1 with no error. Fixed:
`local_llm.py::_is_on_prem_host` resolves the configured host and refuses
(logs + treats as unavailable, same never-raise contract) anything that
isn't loopback/private/link-local. Everything else confirmed clean: no
SSRF (URL isn't attacker-influenced), size caps + rate limiting + off-thread
execution already in place on the unauthenticated NRIC-OCR path, no cloud-AI
env var reintroduced anywhere, `docker-compose.yml`'s `host.docker.internal`
wiring doesn't widen the backend's network exposure.

Verified: NEW `backend/tests/test_local_llm.py` (11 tests — disabled flag
and a non-private host both make zero network calls, a real closed loopback
port degrades to `None` without raising, happy-path text/vision via
monkeypatched `httpx.post`, vision payload carries base64 with no `data:`
prefix, `summarize.py`/`nric_ocr.py` both use the local result when present
and fall back correctly when it's `None` or unparseable); full `pytest`
suite still green (369→370); `pyflakes` clean on every touched file.

**Not done here (tracked as P4.3b):** CDS hint, medication-safety alert
wiring, `faster-whisper` voice→SOAP, NL report narrative — the local-LLM
plumbing is in place, those are separate net-new features on top of it,
scoped out of this pass per user direction (surfaced as a choice — the
demo-priority ranking in this file put the core cloud-removal ahead of the
new-feature work).

### 2026-09-13 — P3.8 Management Dashboard

: summarised operational data (12.1.1), patient-flow prediction
(12.1.2), operational health score (12.1.3). Zero new tables -- everything
computed live off rows that already exist (`QueueTicket`, `StaffClockEvent`,
`ServiceRequest`, `Appointment`), same "thin, reuse existing engines" call
P3.2 made. NEW `routers/dashboard.py`:

- `GET /dashboard/summary` -- patients in queue / attended today (from
  `QueueTicket.status`), physicians on duty vs total (`StaffClockEvent`
  with an open shift, joined to `User.role == "clinician"`), average
  time-to-called today (not time-in-system, which would conflate wait
  time with consultation length), unresolved physician referrals
  (`ServiceRequest.source == "physician_order"` still `status ==
  "ordered"`), and a composite **operational health score** (0-100,
  weighted 40/25/20/15 over wait/availability/queue/referral sub-scores --
  ponytail-flagged as heuristic thresholds, not a clinically-validated
  index, tune per deployment if it needs to mean something more precise).
- `GET /dashboard/flow-forecast` -- **EWMA** (alpha 0.3, most-recent-
  weighted) over the past 8 same-weekday occurrences of `QueueTicket`
  counts, forecasting both "today" (net of what's already checked in) and
  "tomorrow"; deliberately the EWMA half of the roadmap's "EWMA/GBM"
  sizing note -- a real GBM needs a training pipeline and a new
  scikit-learn dependency for a clinic-scale forecast a smoothed average
  already serves. Already-`scheduled` `Appointment` counts are reported
  alongside as a separate number (not blended into the EWMA) to avoid
  double-counting walk-in-derived history against booked-ahead load.
  Malaysia-local calendar days throughout, reusing
  `routers/reception._common._malaysia_today`/`MALAYSIA_TZ` rather than
  re-deriving timezone handling.

NEW page `PAGE_DASHBOARD` (`app/permissions.py` +
`add_dashboard_to_legacy_role_pages` backfill, same pattern as every prior
P3.x page) -- clinician/records_officer by default, not receptionist/
pharmacist (a management tool, same split as reporting). Frontend: NEW
`web/src/pages/Dashboard.jsx` -- plain stat tiles + thin proportion bars
(no chart library), reusing the app's existing green/amber/red status-
color convention rather than introducing a new palette; polls every 60s.

5 new tests (`test_dashboard.py`), including an exact EWMA arithmetic
check (2 historical weeks seeded at counts 2 and 3 -> asserts the forecast
is exactly 1.32 rounded to 1.3, not just "some positive number"). Full
suite 354 → 359 passed. `ruff check --config ci/ruff.toml` clean. `oxlint`
+ `npm run build` clean. No schema change, so `check_schema.py` is
unaffected (not re-run).

### 2026-09-13 — P3.7 MOH / statutory reporting

: "notifiable disease reports", "quality & safety compliance
reports", "data anonymization" -- 12.2's "automate daily/weekly/monthly
reporting" folded in too since it's the same mechanism. Reused P3.6's
engine throughout rather than building a parallel one:

- **Data anonymization:** NEW `Field.pii` flag on `reporting_engine`'s
  field registry (set on every patient-name/NRIC field across all 5
  datasets) + `run_report(..., anonymize=True)` replacing any selected
  `pii` field's value with a stable per-value pseudonym
  (`sha256(value)[:8]`, unsalted -- ponytail-flagged: fine for de-
  identifying an ad-hoc export, a keyed HMAC would be the upgrade if
  cross-export unlinkability ever becomes a real requirement, same
  pattern `audit_hash.py` already uses). Generic across every dataset, not
  a notifiable-disease-only feature. `GET /reports/datasets` now exposes
  `pii` per field so the UI can show the checkbox only when relevant.
- **Automated periodic reporting:** NEW groupable `<field>_day`/`_week`/
  `_month` bucket fields on `encounters`/`ancillary_results` (a date
  column run through `_period_bucket`) -- "group by month" is just another
  groupable field, no separate scheduling/period-parameter machinery. This
  is also HMIS's "attendance ... service provision" ask; "morbidity"
  (top diagnoses) was already covered by grouping `conditions` by `name`.
- **Notifiable disease reports:** NEW `models.NotifiableDiseaseReport`
  (migration `cf87c9db42e8`) + a small workflow in `routers/reporting.py`.
  No public e-Notifikasi API exists (confirmed against `healthcare/
  National Interoperability.md` / `Malaysia Health Regulation.md` -- same
  "schema-readiness, not a live integration" situation as MHNexus/FHIR),
  so per the clause's own wording ("must GENERATE these") this is a
  checklist + PDF generator, not a live submission: `GET .../candidates`
  suggests cases from `Condition.name` matched against a new
  `models.NOTIFIABLE_DISEASES` starter list (Act 342, explicitly disclaimed
  as not gazette-synced -- free-text filing is never gated on the match),
  `POST .../notifiable-diseases` files one (409 on a duplicate against the
  same condition), `.../submitted` self-reports the manual portal
  submission, `.../document` renders a one-page PDF via NEW
  `report_export.render_notifiable_disease_pdf` (raw reportlab Canvas,
  same "simplest tool that draws a form" choice as
  `document_generation.py`). Facility-local, same as every other P3.6/P3.7
  surface.
- **Quality & safety compliance reports:** no new code -- this is P2.9's
  audit hash-chain (`GET /admin/audit/chain-status`) + P2.12's
  `data_quality_alerts`, already built. Documented here rather than
  re-derived, same "thin, reuse existing engine" call P3.2 made for its
  clause overlaps.

Frontend: `Reporting.jsx` gained an "Anonymize" checkbox (shown only when
the current field selection includes a `pii` field) and a new
"Notifiable disease reports" panel (candidate list with an inline
file-with-onset-date/notes form, filed-reports list with a PDF link and
"Mark submitted" action).

6 new tests. Full suite 348 → 354 passed. `check_schema.py` PASS
(upgrade / autogenerate-empty / downgrade round-trip). `ruff check
--config ci/ruff.toml` clean. `oxlint` + `npm run build` clean.

### 2026-09-13 — P3.6 Reporting engine

Canned operational reports + Custom Report Builder
 -- the two P3.6 clauses; 12.2/12.3/12.6-12.9 are separately
scoped (dashboard/MOH-reporting/predictive/NL-insight tasks later in the
plan). NEW `app/reporting_engine.py`: deliberately NOT a generic SQL query
builder -- a curated registry of 5 facility-local datasets (`encounters`,
`admissions`, `ancillary_results`, `conditions`, `bills`), each with typed,
named `Field`s (a label + explicit getter + groupable/filterable flags +
enum options where relevant). The "field picker across modules" the clause
asks for is generic OVER this registry (`GET /reports/datasets` hands the
frontend the catalogue), never over raw column names -- so no client-
supplied field name ever reaches a query. Filter/group-by/sort all run in
Python over a capped fetch (`_MAX_ROWS = 5000`, documented ceiling, not
SQL-side pagination) -- fine at clinic scale. Group-by produces one row per
group with a `count` plus an `avg_<field>` for every selected numeric field
(e.g. group `ancillary_results` by `module`, select `tat_minutes`, to get
per-module average lab/imaging turnaround -- the clause's explicit TAT ask).
The `bills` dataset also closes a forward reference left in
`schemas.BillingStatsOut`'s docstring from P3.3 ("the full 'Financial
performance reports' the tender is P3.6's job").

NEW `app/report_export.py`: PDF via reportlab's `platypus` Table/
SimpleDocTemplate (arbitrary-length tabular report -- unlike
`document_generation.py`'s raw Canvas, which suits a fixed one-page form,
not a table; same reportlab dependency, no new one) and Excel via NEW
dependency `openpyxl` (pure-Python .xlsx writer, same on-prem/offline-CI
reasoning as reportlab). `POST /reports/export` streams either back as an
attachment.

NEW `models.ReportTemplate` (migration `01a1fbea35ef`): a saved report
selection (dataset/fields/filters/group_by/sort as JSON, never a raw query
string) for the clause's "save & share templates" -- `is_shared=False`
(default) is visible only to its creator, `is_shared=True` to everyone at
the facility; either way only the creator or an admin may edit/delete it
(404, not 403, for a private template someone else can't even see exists --
same shape as every other cross-scope lookup in this codebase). NEW page
`PAGE_REPORTING` (`app/permissions.py` + `add_reporting_to_legacy_role_pages`
backfill, same pattern as billing/dental/ancillary before it) -- granted to
clinician/records_officer by default, NOT receptionist/pharmacist (a
management/clinical tool, not a frontdesk task -- same split dental made).
`REPORTING_ROLES = (admin, records_officer, clinician)` gates every endpoint
in `routers/reporting.py`, matching dental's `CHART_ROLES` exactly.

Frontend: NEW `web/src/pages/Reporting.jsx` -- dataset picker, generic
field-picker/filter/group-by/sort UI rendered entirely off
`GET /reports/datasets` (no hardcoded field list on the client either),
results table, PDF/Excel export buttons, saved-template list with
save/load/delete. Wired into `access.js`/`App.jsx`/`Layout.jsx`/
`AccessControlTab.jsx` the same way billing was (also fixed in passing:
`AccessControlTab.jsx`'s `PAGE_LABELS` was missing "billing" since P3.3,
left the matrix column blank -- one-line fix while already touching that
line for reporting).

12 new tests (`test_reporting.py`): dataset catalogue shape, page-gate RBAC
(receptionist 403), facility scoping, unknown-field/unfilterable-field/
non-groupable-group-by all 422, an enum filter, group-by average-TAT
correctness (2 lab requests averaging to 20min + 1 xray at 60min, asserted
exactly), PDF/Excel export (magic-byte checks: `%PDF` / `PK` zip header),
template private-by-default + cross-user invisibility (404) + owner
visibility, shared-template visible-but-not-editable-by-non-owner (403 on
delete) + admin-can-delete, and template save rejects an invalid field
selection. Full suite 335 → 348 passed, `check_schema.py` PASS (upgrade /
autogenerate-empty / downgrade round-trip), `ruff check --config
ci/ruff.toml` clean on every file touched, `oxlint` + `npm run build` clean
(oxlint caught 2 real issues in the new page -- a ternary used as a
statement instead of if/else, and a `useMemo` reading a fresh `{}` literal
every render -- both fixed).

### 2026-09-13 — P3.4/P3.5 review pass

Requested review gauntlet hit a session rate limit mid-flight (7 of the 9
`/code-review` agents + the voltagent security-auditor pass failed before
producing output; only the Performance pass completed — no concerns beyond
a minor note, actioned below). Fell back to a direct manual review rather
than retry the swarm. Found and fixed 2 real bugs plus 2 hardening items:

- **[Medium, security]** Adding `"consultation_note"` to `_ANNOTATION_MODEL`
  (this session's earlier P3.4 fix) had no facility check, unlike its
  siblings. Every other `_ANNOTATION_MODEL` target (condition/medication/
  allergy/encounter) is already universally cross-facility readable
  elsewhere in this router, so no write-side check was ever needed for
  them — but `ConsultationNote` is the one target with genuinely NO
  cross-facility read anywhere (`consultation.py::get_consultation_note`:
  "no broader read mode"). Unfixed, any facility could attach a signed
  "correction" annotation to another facility's private SOAP note despite
  never being able to read it through its own endpoint. Fixed with a
  same-facility check in `add_record_annotation` (404, not 403 -- same
  non-leaking shape as the note's own endpoint) + a regression test
  (`test_annotation_on_consultation_note_rejects_cross_facility`).
- **[Low, correctness]** Timeslip times rendered as `09:00:00` instead of
  `09:00` on the actual certificate -- `datetime.time`'s default `str()`
  includes seconds, and `fields['time_in']`/`['time_out']` are real `time`
  objects (schema-typed, not strings). Fixed with explicit `.strftime`;
  also tightened the test that should have caught it (`"09:00" in text`
  passed either way -- it's a substring of `"09:00:00"` too).
- **[Hardening]** A whitespace-only required field (e.g. `diagnosis: "   "`)
  passed the "is it missing" check as truthy, so a blank line could land on
  an official document. Added `str_strip_whitespace = True` to
  `GenerateDocumentRequest`'s Config + a regression test.
- **[Minor]** The referral dropdown in `PatientList.jsx` fetched with no
  explicit `limit`, relying on the ancillary endpoint's default of 50 --
  fine for correctness (bounded, not unbounded) but oversized for a
  dropdown. Capped to 20.

Also ran the project's actual CI lint gate (`ruff check --config
ci/ruff.toml`, not ruff's defaults) for the first time on this diff --
clean on everything touched this session; it surfaced one pre-existing,
unrelated `F401` in `a7c3f92e0b4d_fk_ondelete_cascade_patient_linked.py`
(prior session's commit) left alone as out of scope.

2 new regression tests added, full suite re-run clean after every fix
(335 passed), `check_schema.py` PASS, `oxlint` + `npm run build` clean.

### 2026-09-13 — P3.5 Document generation

Digital Medical Certificate / Referral Letter / Timeslip. New:
`app/document_generation.py` (reportlab, one fixed-layout A4 page per
kind -- deliberately not a template engine or HTML-to-PDF stack) +
`POST /patients/{id}/documents/generate` (`routers/patients.py`). No new
table: a generated document IS a `ClinicalDocument` row (doc_type
`medical_certificate`/`referral_letter`/`timeslip`), reusing the existing
WORM `clarion-documents` bucket and the existing GET .../file /.../
thumbnail serving + cross-facility visibility rule unchanged -- 3 new
nullable columns (`signed_by`/`signed_by_name`/`signed_at`, migration
`b8f527490604`) are the only schema change. The signer's saved signature
PNG is composited directly onto the PDF page raster rather than kept as a
separate per-record snapshot object (Encounter/ConsultationNote/
ClinicalRecordAnnotation's pattern) -- unnecessary here since the whole
PDF is already the one immutable WORM artifact.

Dependency choice: `reportlab` (pure-Python PDF writer, no host libs to
provision) over `weasyprint` (present in this dev environment's site-
packages but NOT a declared dependency -- confirmed non-functional here,
fails to load its Pango/Cairo/GObject native libs; wrong shape anyway for
an on-prem/offline-CI deployment target) or a wkhtmltopdf/headless-
Chromium binary.

`schemas.GenerateDocumentRequest`: one flat, all-Optional field set across
all 3 doc_types (same style as `ConsultationCompleteRequest`'s SOAP
fields) with a `model_validator` enforcing which fields are required per
doc_type, plus a same-facility `rest_to >= rest_from` / `time_out >
time_in` sanity check. RBAC matches every other clinical-document write
in this router: admin/records_officer/clinician, receptionist excluded.
Frontend: `PatientDetail.jsx`'s existing Documents tab gained a
"Generate MC / Referral / Timeslip" form (same saved-signature-or-draw-one
convention as the consultation/annotation sign-off modals); generated
documents show up in the same list a scanned upload would, with a
"Signed by ... at ..." line the OCR path doesn't have.

7 new tests (`test_document_generation.py`): one happy-path per doc_type
(asserting the served file is actually a PDF), the 409-no-signature case,
a missing-required-field 422, the rest_to-before-rest_from 422, and the
receptionist-403 RBAC case. Full suite 327 → 334, `check_schema.py` PASS
(upgrade / autogenerate-empty / downgrade round-trip), `oxlint` +
`npm run build` clean.

### 2026-09-13 — P3.3 Billing module

The third P3 tender module (+ per-module billing:
frontdesk billing, consultation fees, pharmacy
billing, admin billing). New engine: `ChargeMasterItem` /
`Bill` / `BillItem` / `Payment` / `Claim` (`routers/billing.py`, migration
`190811a20bb0`). Design surfaced to and confirmed with the user before
building (see the P3.3 plan): **facility-local only** (no cross-facility
read mode at all, unlike Ancillary/Dental — removes that entire bug class
by construction), every `BillItem` price **server-derived** from exactly
one of a `ChargeMasterItem` / a signed-off `ServiceRequest` /
`MedicineInventoryItem.unit_cost` (never client-supplied), and insurance/
panel claims use a **copay/split model** — a claim can cover part or all
of a bill, and `BillOut` exposes `patient_due_cents` (what front-desk
collects now) separately from `amount_due_cents` (the true outstanding
total) so a pending claim doesn't force collecting the insurer's share
from the patient.

Delegated the mechanical pieces to **antigravity/agy** per this session's
routing policy: `test_billing.py` scaffolding succeeded (30 tests,
independently verified against the router's actual behavior, not
agy's self-report); the `Billing.jsx` frontend delegation was blocked by
agy's own write-permission wall (no `write_file` grant for this repo path)
and, per the standing "no `--yolo` on auth/money-shaped work" rule, was
built directly instead. Went through the same review gauntlet as P3.1/
P3.2 — a voltagent security audit, this session's own `/code-review`-style
multi-pass, and a direct `agy-delegate --tier pro` diff cross-check
(the latter also permission-blocked, produced no findings) — retried once
after the session hit its own rate limit mid-review, same "wait rather
than commit on partial verification" call as P3.2. Found and fixed:

- **[High]** The claim-amount cap (`create_claim`/`update_claim`) compared
  against raw `amount_due_cents` instead of `patient_due_cents` (net of
  every OTHER submitted/approved claim) — let the SAME bill be claimed in
  full against two different insurers simultaneously (e.g. a $50 bill
  claimed in full to both AIA and Prudential). A real double-claim/
  insurance-fraud-liability gap, not a display glitch. Fixed + extracted
  into a shared `_check_claim_amount_cap` helper (was duplicated at both
  call sites, which is exactly how the bug could get fixed in one place
  and missed in the other) + regression test.
- **[High]** `mark_claim_paid` was a bare status flip with no money
  attached — a claim could become `"paid"` with nothing in `paid_cents`,
  so `patient_due_cents` would silently snap back up on the next read.
  **Removed the standalone endpoint entirely**: "paid" is now reachable
  ONLY via `record_payment`'s `claim_id` linkage, so the status and the
  money always move together. (Frontend/tests/client.js updated to match.)
- **[Low]** N+1 in `GET /billing/stats` — reused `_serialize_bill` (which
  touches `bill.patient`) without the `joinedload(patient)` every other
  bill-fetch site has, and never even used the resulting name. Fixed by
  removing the unnecessary full serialization from that loop's hot path.
- **[Low]** No upper bound (`le=`) on `BillItemCreate.quantity`,
  `PaymentCreate.amount_cents`, `ClaimCreate.claim_amount_cents`, and
  `ChargeMasterItemCreate/Update.unit_price_cents` — a fat-fingered value
  could overflow the plain `Integer` money columns. All four now capped
  (RM 1,000,000 / 100,000 units).
- **[Low-Med]** Pharmacy price conversion used plain `round(unit_cost *
  100)` on a `Float` column — binary-float multiplication can misconvert
  a specific decimal price by a cent, and the snapshot is immutable once
  written. Switched to `Decimal(str(unit_cost))` before scaling.
- **[Low]** `update_claim` didn't block editing a draft claim on an
  already-voided bill (self-caught before the external review passes).

**Investigated, accepted, not fixed:** voiding a `BillItem` doesn't
re-validate already-submitted/approved claims against the bill's new
(lower) total — `patient_due_cents` still floors correctly at 0 (no
crash/negative value), but an existing claim can end up sized against a
total that's since shrunk; front-desk would need to manually void/adjust
the claim. Narrow edge case, not a security issue, deferred rather than
adding cross-checking logic for it this pass.

**Test-quality follow-ups identified, not done this pass** (flagged by
the test-quality review; the module's core arithmetic/RBAC/facility-
scoping/lifecycle paths are solidly covered, this is incremental):
extract the repeated 5-6 line "facility → charge-master item → bill →
item" setup (appears ~15× across `test_billing.py`) into a shared helper;
add tests for `void_bill_item`'s three untested guard branches (already-
voided item, voided bill, item-not-found), the `service_request`-belongs-
to-a-different-patient 400, payment double-void, and overpayment
clamping; RBAC-denial coverage on the charge-master PATCH and the claim
status-transition endpoints is asserted only indirectly (same role tuples
already independently confirmed correct by the security audit) rather
than with dedicated tests per endpoint.

30 tests (`test_billing.py`), full suite 290 → 320. `check_schema.py`
PASS (upgrade/downgrade round-trip, zero autogenerate drift), `ruff`
hard gate + `oxlint` clean, `npm run build` clean. Also folded in the
`_facility`/`_make_patient`/`_TEST_SIGNATURE_B64` extraction from
`test_ancillary.py`/`test_dental.py` into `conftest.py` that both files'
own comments had flagged as due once a third P3.x test file needed them
— this is that third file.

### 2026-09-13 — P3.4 Consultation notes (separate session, reviewed here)

A concurrent session built structured SOAP consultation notes
(`ConsultationNote`, `routers/consultation.py::complete_consultation_ticket`
extended to accept `subjective`/`objective`/`assessment`/`plan`/
`treatment_plan`/`follow_up_at`/an optional same-facility ancillary
`referral_service_request_id`, migration `2c4e6a8b0d12`, a new `GET
/consultation/encounters/{id}/note`, `PatientList.jsx`'s consultation
modal) while this session was independently working on P3.3 in the same
working tree. Reviewed at the user's request once the mixed diff surfaced
mid-review. Found and fixed one real bug: the migration created a
`UniqueConstraint` on `encounter_id` where the model declares `Column(...,
unique=True, index=True)` -- SQLAlchemy's canonical form for that is a
unique **index**, not a separate constraint, so `check_schema.py`'s
autogenerate diff saw permanent drift. Fixed (index instead of
constraint, `downgrade()` updated to match); `check_schema.py` now PASS.
Router logic (facility-scoped referral ownership check, facility-only
note read, no-SOAP-fields-means-no-row) read correctly on inspection; its
2 tests pass. Not fixed (left for that session, since the feature is
still in progress there): `ClinicalRecordAnnotation`'s `target_type`
allow-list (`schemas.ANNOTATION_TARGET_TYPES`) doesn't include
`"consultation_note"` yet, so the module docstring's claim that
corrections go through that mechanism isn't wired up yet (a client
request with that `target_type` is cleanly 422'd by Pydantic, not a
crash — just an unimplemented, currently-aspirational doc claim); the
frontend has no field for `follow_up_at`/`referral_service_request_id`
yet, only the five text fields; test coverage is thin (2 tests, no RBAC/
referral-guard/empty-fields-means-no-row cases).

### 2026-09-13 — P3.4 loose ends closed

Closed the three gaps the review above left open. `"consultation_note"`
added to both `schemas.ANNOTATION_TARGET_TYPES` and
`routers/patients.py::_ANNOTATION_MODEL` (one line each) — corrections now
actually go through `ClinicalRecordAnnotation` the way the model's
docstring always claimed; deliberately NOT added to
`_ANNOTATION_FACILITY_SCOPED_TARGETS` (kept consistent with its sibling
1:1-with-Encounter target — Encounter isn't in that map either, and the
note's own dedicated read endpoint already has no cross-facility mode at
all). `PatientList.jsx`'s consultation modal gained a `follow_up_at`
datetime-local field and a referral `<select>`, populated via the
existing `listAncillaryRequests({patientId, status: "signed_off"})` call
filtered client-side to the signing clinician's own facility (mirrors the
same-facility check `complete_consultation_ticket` enforces server-side,
so nothing offered in the dropdown can 404 on submit). 3 new tests in
`test_consultation_notes.py`: follow_up_at/referral persist correctly,
a cross-facility referral is rejected (the 404 branch had no coverage),
and the new annotation wiring round-trips through both the write and list
endpoints. Full suite 324 → 327, `check_schema.py` PASS, `oxlint` +
`npm run build` clean. P3.4 is now fully done.

### 2026-09-13 — P3.2 Dental module

The second P3 tender module, deliberately built THIN: only the
tooth chart is genuinely new. Everything else the clause asks for reuses an
existing engine unchanged (see `routers/dental.py`'s module docstring and
`models.py`'s "Dental engine" section comment for the full clause-by-clause
mapping):

- **New**: `DentalChartEntry` (FDI notation `11`-`48`, create-with-signature
  = the sign-off, append-only -- correction is a new
  `ClinicalRecordAnnotation` with `target_type='dental_chart_entry'`, same
  discipline as P3.1's `ServiceResult`). `routers/dental.py`: 3 endpoints
  (`GET /chart-options`, `GET /chart/{patient_id}`, `POST /chart`), gated to
  `CHART_ROLES` (admin/records_officer/clinician -- no receptionist/
  pharmacist). Migration `1ea025093037`.
- **Reused, no code change**: queue/appointments -- Reception's
  existing department-tagged rooms/tickets; visit-level "sign-off"
 -- `consultation.py::complete_consultation_ticket`; X-ray
  references -- `ancillary.py`'s `ServiceRequest(module="xray",
  source_encounter_id=...)`; medication --
  `patients.py::add_medication`/`update_medication`; diagnosis reporting
 -- the existing `Condition` CRUD.
- **Deferred, documented**: DMC / Referral Letter / Timeslip document
  generation -- no document-generation engine exists yet,
  that's P3.5's job.

Went through the same review gauntlet as P3.1's follow-up wave (voltagent
security audit + 9-agent `/code-review` + antigravity/Gemini cross-check,
run twice after the first pass hit a session rate limit mid-review).
**Verdict: clean** -- unlike P3.1, no RBAC/cross-facility bug was found this
time; the module correctly reused the hardened P3.1 patterns (hidden-
facility filter applied in SQL before pagination, create-with-signature
atomicity, 404-not-403 leak avoidance, `extra="forbid"` + enum validation)
rather than re-deriving them, and it was independently confirmed the
pagination-before-filter fix generalizes correctly to a second annotation
target type (`dental_chart_entry` alongside `service_result` in
`patients.py::_exclude_hidden_facility_scoped_annotations`). Fixed from
review:

- A test-quality finding: no test exercised pagination + hidden-facility
  filtering together for the dental chart (only unpaginated hide/show was
  covered) -- added `test_chart_pagination_boundary_respects_records_shared_publicly`,
  which would have failed under a naive post-pagination filter. Also added
  the missing `encounter_id` happy-path test.
- agy/Gemini: `_exclude_hidden_facility_scoped_annotations`'s `.notin_()`
  call passed a dict directly (works today via Python's implicit
  key-iteration, but fragile/non-obvious) -- made explicit with
  `.keys()`.
- A simplification-review finding: `DentalChartEntry.encounter_id` (meant to
  let an X-ray referral share `source_encounter_id` with the chart entry for
  the same visit) was modeled but never actually wired into
  `Dental.jsx` -- the UI had no encounter picker at all, so the field was
  dead. Added an "Encounter ID (Optional)" input to the entry form
  (matching `Ancillary.jsx`'s existing raw-text-input pattern) and surfaced
  it on chart history rows.
- A code-quality finding: `hasSignature` was derived once from a
  `getCurrentUser()` snapshot and never refreshed, so after a clinician
  drew their first signature on-the-spot, every SUBSEQUENT tooth entry in
  the same visit forced another redraw instead of showing the now-saved
  signature -- a real papercut given dental charting is naturally a
  multi-entry-per-visit workflow (unlike `PatientDetail.jsx`'s one-shot
  annotation modal). Fixed: `user` is now `useState`, refreshed via the
  existing `refreshCurrentUser()` immediately after a save-on-the-spot
  signature.

**Investigated, declined as out of scope for this pass** (pre-existing
patterns shared with `ancillary.py`, not P3.2-specific regressions):
`create_dental_chart_entry`'s `encounter_id` ownership check verifies the
encounter belongs to the patient but not that its authoring facility isn't
hidden from the caller (identical, unflagged-in-two-review-rounds property
of `ancillary.py::create_service_request`'s `source_encounter_id` check);
and a caller-supplied `signature_b64` is silently ignored when a saved
signature already exists (copy-pasted verbatim from
`sign_off_service_request`/`add_record_annotation`, not new here). Both
would need a cross-cutting fix touching multiple already-reviewed modules,
not a dental.py-only patch.

**Follow-up work identified, not done this pass** (flagged by the
simplification and quality reviewers as genuine "rule of three"
duplication, but out of scope -- touches `consultation.py`/`ancillary.py`/
`profile.py`/`PatientDetail.jsx`, all already shipped and reviewed):
1. The ~10-line "check signature, save-on-the-spot, snapshot" sequence is
   now copy-pasted in THREE routers (`consultation.py::complete_ticket`,
   `ancillary.py::sign_off_service_request`, `dental.py::create_dental_chart_entry`)
   -- worth extracting to a shared `profile.py` helper before a fourth P3.x
   module copies it again.
2. The frontend signature-capture widget (`savedSigUrl`/`sigUrlRef`/the two
   `useEffect`s/the saved-vs-draw JSX branch) is duplicated between
   `PatientDetail.jsx`'s `SignOffModal` and `Dental.jsx`'s `EntryForm` --
   worth extracting to a shared component/hook.
3. `DentalChartEntry`'s signature snapshot has no viewer endpoint (unlike
   annotations' `GET .../annotations/{id}/signature` +
   `SignatureLink`) -- true of `ServiceResult` too (P3.1), so this is now a
   two-module gap, not a one-off.
4. No cross-table "patient visit timeline" -- a dental visit's data is now
   spread across `Encounter`/`DentalChartEntry`/`ServiceRequest`/
   `MedicationStatement`/`Condition` with no single view correlating them.
   Real, but a `patients.py`-level concern spanning P3.1+P3.2 output, not
   this module's job alone.
5. `test_dental.py`'s `_facility()`/`_make_patient()`/`_TEST_SIGNATURE_B64`
   helpers are byte-for-byte copies of `test_ancillary.py`'s -- worth
   extracting to `conftest.py` before a third P3.x test file repeats them.

13 new tests (`test_dental.py`), full suite 277 -> 290. `check_schema.py`
PASS (upgrade/downgrade round-trip + zero autogenerate drift, verified on a
real migration chain run, not just inspection). `ruff` hard gate + `oxlint`
clean, web `npm run build` succeeds.

**Process note:** the review pass hit the session's rate limit mid-way
(most of the 9 code-review agents and the security auditor got cut off);
retried after the limit cleared rather than committing on partial
verification -- the user explicitly chose to wait rather than proceed on
what was verified so far, even though direct verification (tests/lint/
build/schema) was already solid at that point.

### 2026-09-12 — P3.1 second review + fix wave

A second, independent review pass on the P3.1 diff (`35cf91f..HEAD`): a
voltagent security audit, all 9 `/code-review` agents, and an antigravity/
Gemini cross-check, run in parallel and reconciled. Confirmed the previous
wave's two fixes (admin cross-facility override, receptionist clinical-read
leak) hold correctly. Found and fixed 7 new issues, all in
`routers/ancillary.py` unless noted:

- **[Med]** `list_service_requests`' cross-facility (`patient_id`) branch
  applied SQL `LIMIT`/`OFFSET` before filtering out
  `records_shared_publicly`-opted-out facilities in Python -- a page could
  come back under-filled, and successive offset-based pages could
  skip/misalign rows. Moved the exclusion into the SQL `WHERE` (before
  limit/offset) via `or_(ordering_facility_name.is_(None),
  ordering_facility_name.notin_(hidden))`. Caught independently by the
  code-review performance + quality agents and by agy/Gemini (3-way
  corroboration).
- **[Low-Med]** `upload_result_document` had no guard against a second
  upload, which silently replaced the object-store pointer -- overwriting
  an already-attached document's metadata on an immutable, signed-off
  result and orphaning the original object in MinIO. Now 409s if
  `req.result.file_object_key` is already set.
- **[Low]** `get_result_document` recovered the download filename via
  `file_object_key.rsplit("_", 1)[-1]`, which corrupted any original
  filename containing an underscore (`blood_test_results.pdf` →
  `results.pdf`). Changed the object key's id/filename separator from `_`
  to `/` (`storage.validate_key` already supports multi-segment keys) and
  recover via `rsplit("/", 1)[-1]`.
- **[Low]** `db.refresh(req)` after commit in create/cancel/sign-off/upload
  expired the joinedloaded `catalog_item`/`result`/`patient` relationships,
  so `_serialize_request` triggered extra lazy-load queries on every write.
  New `_load_request_with_relations()` helper (joinedload on all three)
  used both in `_request_or_404` and after every commit instead of
  `db.refresh(req)`.
- **[Low-Med]** `_request_or_404`'s `require_same_facility` guard used a
  bare `!=`, so a NULL `ordering_facility_name` row compared against a
  facility-less caller (`None != None`) would silently bypass the guard the
  docstring claims ("immutable to everyone by design"). Not reachable via
  the live API today (`create_service_request` always sets a facility), but
  fixed preemptively to match `patients.py::_record_editable`'s
  `not owner or owner != caller` idiom, ahead of any future data import.
- **[Low]** (`routers/patients.py`) `service_result`-targeted
  `ClinicalRecordAnnotation`s were reachable via `list_record_annotations`
  regardless of the underlying result's facility opt-out -- a 'correction'
  annotation could leak a hidden facility's result content that the
  ancillary endpoints themselves correctly hide. New
  `_exclude_hidden_service_result_annotations()`, applied to the query
  BEFORE `offset`/`limit` via a correlated subquery -- deliberately scoped
  to `target_type == 'service_result'` only (the type this wave touches);
  the same gap for condition/medication/allergy/encounter annotations is a
  wider pre-existing issue, tracked but not fixed here. (First draft of
  this fix filtered in Python after pagination -- caught by voltagent's
  review, since that's the exact anti-pattern the first finding above was
  fixing; corrected to filter in SQL before pagination.)
- **[Info]** `create_catalog_item`/`update_catalog_item` had no audit
  logging, unlike every other write in the router, despite being
  billing-relevant (`unit_price_cents` feeds P3.3). Added
  `ancillary_catalog_item_created`/`_updated` `log_access` calls.
- **Investigated, not fixed:** a separate "roster forgery" concern --
  `create_service_request` has no presence check, so any `ORDER_ROLES` user
  (receptionist included) can establish a permanent facility↔patient
  relationship (via `_FACILITY_RELATIONSHIP_SOURCES`) with one order.
  Verified this is consistent with, not a regression against, the existing
  `_FACILITY_RELATIONSHIP_SOURCES` design ("deliberately broad/inclusive --
  any one source counts") -- `Appointment`/`QueueTicket`/`Admission`
  creation have the exact same lack of a presence check. Left as-is;
  revisit only if the broader design changes.
- **Documented, not code:** `docs/deployment.md` -- an already-live
  facility's `RolePagePermission` row is never automatically backfilled
  with a newly-added `DEFAULT_ROLE_PAGES` entry (e.g. this wave's own
  `ancillary` page); only a `seed.py`-style backfill call does that, and
  `seed.py` is first-run-only. Added a "Role permissions on upgrade" note
  to the upgrade runbook.

6 new tests added (`test_ancillary.py`: 22 → 28), including one
(`test_cross_facility_pagination_boundary`) that would have failed under
the pre-fix pagination bug. Full suite 277/277, `ruff` hard gate clean.
Delegation: voltagent (security audit of the original diff, then a second
pass reviewing this fix diff -- caught the annotation-pagination
regression above) + antigravity/Gemini (independent diff review; drafted
the 6 tests + the deployment.md text, but could not get a write grant in
this sandbox, so both were hand-verified against the actual model/schema
field names before being applied).

### 2026-09-12 — P3.1 code-review follow-up

9-agent `/code-review` (test/lint/reviewer/security/quality/test-quality/perf/
deps/simplification, run in parallel) plus a direct security audit of
`routers/ancillary.py` against `patients.py`'s established cross-facility
invariants, on the P3.1 diff. Verdict was Needs Attention, not Needs Work --
tests, lint, schema check, and build were all clean; the real findings were
concentrated in RBAC edge cases the initial implementation missed. Fixed:

- **[High]** `_request_or_404`'s write-path guard (`cancel`/`sign_off`/
  `upload_result_document`) used to exempt `role == "admin"` from the
  facility match -- any facility's admin could cancel or forge a signed
  result at ANY other facility. Removed the exemption entirely, matching
  `patients.py::_guard_cross_facility_amend`'s documented "deliberately NO
  global admin override" invariant. Same bug existed in `create_catalog_item`
  (an admin's `facility_name` was trusted verbatim -- could plant an item
  under an arbitrary facility's name) and `update_catalog_item` (admin could
  edit any facility's private item); both now confine an admin to their own
  facility or a global/null item, mirroring `admin.py::_check_mapping_authz`.
- **[High]** A receptionist's own-facility default worklist and single-request
  view leaked full clinical result content (`result_text`, critical/abnormal
  flags, attachment availability) despite the module's own docstring stating
  "receptionist orders but never clinically signs" -- no endpoint was
  actually stripping it. `_serialize_request` now omits `result` entirely for
  a receptionist caller; `GET .../result/document` moved from `ORDER_ROLES`
  to `SIGNOFF_ROLES` so a receptionist can't fetch the raw attachment either
  even by guessing a request_id.
- **[Med]** Cross-facility ancillary reads (`patient_id`-scoped list, single
  GET, result-document GET) didn't respect
  `HospitalSetting.records_shared_publicly`, unlike every other cross-facility
  clinical read in `patients.py`. Now filtered through the same
  `_hidden_author_facilities` helper.
- **[Med]** No `IntegrityError` handling around `ServiceResult`'s
  UNIQUE(service_request_id) insert at sign-off -- a genuine double sign-off
  race would have surfaced as an unhandled 500 instead of a clean 409, unlike
  `consultation.py::start_session`'s equivalent claim-race handling. Fixed.
- **[Perf]** N+1 queries in `list_service_requests` (up to ~400 queries for a
  200-row worklist against MariaDB) -- fixed with `joinedload` on
  `catalog_item`/`result`/`patient`. `upload_result_document` (an `async def`
  endpoint) called the object store's blocking `.put()` directly, stalling
  the event loop for the write -- wrapped in `run_in_threadpool`, matching
  `ai_router.py::digitise_document`'s existing pattern for the identical call.
- **[Bug]** The web order form called `listPatients()` unconditionally, which
  403s for a receptionist (no `patients` page access by design) -- the
  "New order" patient search silently never worked for the one role every
  module clause explicitly names as a Frontdesk-direct-registration actor.
  Receptionist now gets a plain patient-ID input (from Reception check-in)
  instead of the searchable list.
- Minor: deduped `ANCILLARY_MODULES`/`SERVICE_REQUEST_SOURCES`/
  `SERVICE_REQUEST_PRIORITIES` (were briefly literal sets in both `models.py`
  and `schemas.py`) to `models.py` as the single source, matching
  `SERVICE_REQUEST_STATUSES`'s already-correct pattern; joined
  `patient_full_name` into `ServiceRequestOut` (was a raw UUID in the UI);
  removed a dead `const canOrder = true` in `Ancillary.jsx`.

6 new tests added (`test_ancillary.py`: 16 → 22) covering every fix above.
Full suite 271/271, `check_schema` PASS, web lint/build clean.

### 2026-09-11 — P3.1 Ancillary engine

- **P3.1** — the first P3 tender module, and the reference implementation the
  [[Compliance Matrix]] called for behind Procedure/Laboratory/X-ray/
  Physiotherapy's near-identical clause text (–10). One shared engine,
  not four schemas: `ServiceCatalogItem` (the "Parameter Management" surface
  each module's clause repeats), `ServiceRequest` (the order — Frontdesk-direct
  or physician-order, both explicitly allowed by every module clause), and
  `ServiceResult` (perform + sign-off in one atomic action, same shape as
  `consultation.py::complete_ticket`, plus an optional softcopy attachment).
  `module` is just a value on these three tables, not a separate implementation
  per module.
- New page permission `ancillary` (`app/permissions.py`), wired through
  `main.py`'s `require_page_access`, the web nav/routing (`App.jsx`,
  `Layout.jsx`, `lib/access.js`), and the admin Access Control matrix. Default
  access: clinician/records_officer/receptionist (every module clause allows
  Frontdesk-direct registration); pharmacist excluded. Only
  admin/records_officer/clinician may perform+sign a result or manage the
  catalog — receptionist orders/cancels only, mirroring the existing
  Reception-vs-Consultation role split. A legacy-row migration helper
  (`add_ancillary_to_legacy_role_pages`, same discipline as the earlier
  `rewrite_legacy_clinician_pages`) tops up already-seeded facilities.
- Cross-facility scoping reuses the existing immutability pattern verbatim:
  `ServiceRequest.ordering_facility_name` is the authoring facility (added to
  `patients.py::_FACILITY_RELATIONSHIP_SOURCES`, so a patient known only via
  an ancillary order still surfaces in that facility's patient list); a signed
  `ServiceResult` is immutable, and a correction is a new
  `ClinicalRecordAnnotation` with `target_type="service_result"` — registered
  into the EXISTING annotation endpoint/mechanism rather than a new one.
  Perform/sign-off/cancel confined to the request's own ordering facility for
  this pass; cross-facility referral routing (e.g. to an external reference
  lab) is explicitly out of scope, noted in the router's module docstring.
- Migration `cd1edecdbb37` (autogenerated, hand-reviewed, 0 diff against
  `create_all()`, downgrade round-trip verified). Web UI `web/src/pages/
  Ancillary.jsx` — module-tabbed (Procedure/Laboratory/X-ray/Physiotherapy),
  worklist + new-order form + sign-off form + catalog admin + a minimal
  per-module stats panel (open orders / signed-off-last-30d) covering each
  module's "Reporting Management: data & statistics" clause line at the
  minimum-viable level; a fuller Custom Report Builder is P3.6.
- Demo data: 8 starter catalog items (2 per module, global) + one already
  signed-off Full Blood Count result for the demo patient, seeded idempotently
  in `seed.py`.
- Delegation: Claude designed + implemented the schema/router/RBAC/
  immutability wiring directly (security-sensitive, same discipline as
  P1.10's LDAP work — see [[agy-delegation-flakiness]]); the web page and the
  pytest suite were delegated to agy (`antigravity:antigravity-delegate`,
  tier pro) as tightly-scoped single-new-file tasks, then Claude verified both
  in a clean state (`npm run lint` / `npm run build` zero warnings after two
  small fixes — a shared-state clobber between the order form's catalog
  fetch and the catalog-management list, and an unsuppressed exhaustive-deps
  lint warning; full pytest run) before merging.

### 2026-09-08 — P2.10 PDPA

- **P2.10** — consent + data-subject requests + DPO register + retention,
  decisions confirmed with the user after the [[Malaysia Health Regulation]]
  research pass (**no right to erasure** in Malaysian PDPA; clinical records
  run on the s.40 medical-purposes basis, kept per Act 586; retention = flag
  only). Migration `d4a9c1e6f2b8` (5 tables, additive).
  - `app/routers/pdpa.py` (NEW): `GET/POST /pdpa/consent` (append-only
    ledger, newest-wins), `POST/GET /pdpa/requests` + `/{id}` +
    `/assign|complete|reject|export`. `export` = the patient's own record as
    `clarion-patient-record/v1` JSON (s.30 / s.43A portability). DSR `kind`
    excludes "erasure" (400). 21-day SLA. Portal-filed (no-facility) requests
    visible to every RO until assigned. Facility-scoped list + break-glass.
  - `admin.py`: `GET/PUT /admin/dpo-register` (per-facility, create-on-read),
    `GET/PUT /admin/retention-policies` (seeded Malaysian defaults),
    `POST /admin/retention/scan` + `GET /admin/retention/review` +
    `POST .../{id}/disposition`.
  - `app/retention.py` + `db/retention_scan.py` (cron): flags encounters /
    documents / patients past their category's `retain_years` into
    `retention_review_items` (UPSERT, disposition-aware). **Never deletes.**
  - `seed.py`: seeds the retention schedule + a DPO-register placeholder +
    the demo patient's `pdpa_notice` acknowledgement.
  - `test_pdpa.py`. `docs/deployment.md` "PDPA" + Compliance Matrix.
  - **voltagent security review actioned:** DSR *detail* / *export* / staff
    *consent* read+write were platform-wide for any RO/admin (the *list* was
    already facility-scoped) — now all facility-scoped via the P2.2
    `_patient_known_to_facility` + a `break_glass_reason`; `get_request` /
    `view_consent_ledger` now `log_access`-ed (M2/M3). Staff `/export` needs
    the request assigned-to-self + `in_progress` (H1); `bypass_sharing_filter`
    kept for the subject's own data only. Retention schedule + scan +
    disposition → **platform-admin-only** (M4, matching the LDAP-mapping
    precedent). Portal-filed orphan DSRs no longer broadcast (M5). Added the
    s.30 `+14` extension endpoint (L8); `retain_years` min 1 (L10);
    leap-adjusted year math (L11). Legal correctness confirmed SOUND.
  - Verified: full `ci/run.sh` green, `db.check_schema` PASS.
    **P2 is now complete** (P2.1–P2.12 all ✅; MariaDB migration runs owed).

### 2026-09-08 — P2.8 backup / DR

- **P2.8** — `backend/backup/` script bundle + a compose `backup` service
  (profile `backup`), decision confirmed with the user (research validated
  the vault design: `mariadb-backup` (renamed from `mariabackup`) + `mydumper`
  + `restic` to an append-only/Object-Lock repo is current best practice).
  - `backup.sh {full|incremental|logical|binlog|objectstore|prune|daily|weekly}`
    — mariadb-backup full/incr + mydumper logical + 15-min binlog ship + MinIO
    `mc mirror`, every stream `age`-encrypted into a `restic` repo, retention
    `--keep-daily 30 --keep-weekly 12 --keep-monthly 84 --keep-yearly 7` +
    `restic check`. One JSON status line per run.
  - `restore-test.sh` — restores latest into a throwaway `mariadbd`,
    reconciles the Alembic head + every table's row count against prod,
    emits a signed report (quarterly test).
  - `pre-update-snapshot.sh` — the hard deploy gate: fresh
    full+logical backup, records the Alembic downgrade target + running image
    digests + prompts for the hypervisor snapshot id.
  - `backend/backup/Dockerfile` (mariadb:11.4 + restic/age/rsync/mydumper/mc);
    `backend/backup/README.md` = the DR runbook (RPO ≤1h / RTO ≤4h, restore
    steps, 3-2-1, contacts placeholder). compose `mariadb` already emits
    `--log-bin` ROW (added in P2.7).
  - shellcheck added to `ci/run.sh` (all `*.sh` now lint-gated);
    `shellcheck-py` pinned in requirements-dev.
  - `.env.docker.example` (RESTIC_* / AGE), `docs/deployment.md` "Backup / DR",
    Compliance Matrix updated. **Not container-run this session** (no Docker) —
    scripts are `bash -n` + shellcheck clean, compose YAML validates.

### 2026-09-08 — P2.11 offline CI

- **P2.11** — one portable CI gate (decision confirmed with the user):
  `ci/run.sh` runs ruff (F/E9/B006 hard; style advisory) → bandit `-ll` →
  semgrep with `ci/semgrep/clarion.yml` (local rules: SQL-string-interp,
  `jwt.decode` alg pin, `shell=True`, `yaml.load`, hardcoded-secret,
  requests-no-timeout) → osv-scanner → trivy (advisory) →
  `python -m db.check_schema` (the alembic up/down + drift gate, finally
  wired into CI) → pytest. `--fast` / `--no-sca` flags. All hard gates green
  on the current tree.
- `.woodpecker.yml` (recommended engine for an air-gapped forge — no
  marketplace-action dependency) + repo-root `Makefile` (`make ci` etc.),
  both just call `ci/run.sh`. Forge-agnostic; Gitea/Forgejo Actions notes in
  `ci/README.md`.
- **osv-scanner, not pip-audit** — pip-audit has no offline mode (live
  OSV/PyPI); osv-scanner runs air-gapped from a pre-downloaded OSV DB.
  `ci/README.md` covers feeding osv-scanner / trivy / semgrep their data
  offline.
- `ruff` replaces the ad-hoc `python -m pyflakes` (honours `# noqa: F401`
  on the two side-effect model imports pyflakes couldn't). Fixed 7
  pre-existing lint issues (unused imports/var) to get F/E9 green.
  `backend/requirements-dev.txt` pins ruff/bandit/semgrep.
- `docs/deployment.md` "CI gate" section; Compliance Matrix
 updated.

### 2026-09-08 — P2.7 encryption at rest

- **P2.7** — MariaDB data-at-rest encryption wired into the compose stack
  (decision confirmed with the user after an agy research pass — see
  [[Malaysia Health Regulation]] / [[On-Prem Architecture]]).
  - `backend/db/mariadb/encryption.cnf` (mounted to
    `/etc/mysql/mariadb.conf.d/`): `innodb_encrypt_tables=FORCE`,
    `innodb_encryption_threads`, `aria_encrypt_tables`, `innodb_encrypt_log`,
    `innodb_encrypt_temporary_tables`, `encrypt_tmp_files`, `encrypt_binlog`,
    `innodb_encryption_rotate_key_age`.
  - Keys via the **Community** `file_key_management` plugin — a `0400` keyfile
    (`1;<64 hex>`) generated by `backend/db/mariadb/generate-encryption-key.sh`
    into a git-ignored `encryption/` dir, mounted read-only. Empty dir ⇒
    server won't start (the "provision the key first" gate).
  - compose `mariadb`: added `--log-bin=clarion-bin --binlog-format=ROW
    --expire-logs-days=7` (PITR, feeds P2.8) + the two encryption mounts.
  - Research findings (multi-source): LUKS FDE alone is **not** sufficient for
    healthcare/ISO-27001 — DB-level TDE expected as the logical-access layer;
    ~3–10% overhead; HashiCorp Vault / KMIP key management is **MariaDB
    Enterprise only** (Community = keyfile or compiled plugin); `mariadb-backup`
    has no `--encrypt` (P2.8 pipes `--stream` through `age`).
  - `docs/deployment.md` "Encryption at rest" section (LUKS + TDE + key mgmt +
    rotation + Enterprise upgrade path); `.env.docker.example`, Compliance
    Matrix, On-Prem Architecture updated.
  - **Not container-tested** this session (no Docker daemon) — the keyfile
    format is verified, the compose YAML validates; a real `docker compose up`
    of `mariadb` with the key provisioned is owed.

### 2026-09-08 — P2.12 data-quality monitoring

- **P2.12** — `app/data_quality.py`: a registry of 13 independent batch rules
  (missing patient/condition/medication/encounter fields; out-of-range coding
  for gender / blood_type / condition status / allergy severity / encounter
  type; unparseable ISO-date strings; probable-duplicate patients — same
  name+DOB where one has no NRIC; duplicate active conditions; future/pre-birth
  date anomalies). `run_scan()` UPSERTs into the NEW `data_quality_alerts`
  table (migration `c3e8f1a4d5b7`) keyed `(rule, entity_type, entity_id)` —
  repeat sighting bumps `last_seen_at`/`times_seen`, a finding that stops
  firing auto-resolves (`resolved_by='system'`, reopens if it recurs), a
  manual admin resolve does not reopen. `detail` names the field + bad-value
  shape, never a clinical string (M8 discipline).
- `db/data_quality_scan.py` (cron CLI, `--json` / `--list-rules`).
  `DATA_QUALITY_DISABLED_RULES` env = the clause's "configurable".
- Admin API: `GET /admin/data-quality` (status/category/severity/patient
  filters, paginated), `GET .../summary`, `POST .../scan`,
  `POST .../{id}/acknowledge`, `POST .../{id}/resolve` — admin-role,
  **facility-scoped** (P2.2 `_facility_known_patient_ids_select` + a
  `break_glass_reason` escape hatch + `patient_probable_duplicate` always
  cross-facility), every read `log_access`-ed. No web UI yet.
- Test suite drafted by agy (caught a real config-key vs finding-rule
  namespace bug → fixed via `Rule.emits`), Claude-verified + expanded.
- **voltagent code-review + 3-agent `/code-review` actioned:** `detail`
  strings no longer embed raw dates (DOB / event dates are PDPA/M8 — now
  describe the shape); the platform-global endpoints are now facility-scoped
  + audited (the "GET /patients/{id} is open" premise was stale post-P2.2);
  per-rule `try/except` so one bad rule can't lose the whole scan
  (`ScanResult.rules_failed`); `run_scan` preloads existing alerts (kills an
  N+1) + catches the concurrent-scan `IntegrityError` (cron vs the button);
  dropped dead `Rule.category`/`severity`/`RULE_KEYS`; whitespace-only blank
  check made consistent; `acknowledged_by` FK → `ON DELETE SET NULL`.
- `docs/deployment.md` + Compliance Matrix (Gap→Have) updated.

### 2026-09-08 — P2.9 audit hash chain

- **P2.9** — `audit_logs` is now tamper-evident and physically append-only.
  - Migration `b2d7e4a9c1f6` adds `seq` / `prev_hash` / `row_hash`, back-fills
    the chain over every existing row (ordered `(timestamp, id)`), creates the
    `audit_chain_state` tip singleton + `audit_seals` table, and installs
    `BEFORE UPDATE` / `BEFORE DELETE` triggers (`SIGNAL` on MariaDB,
    `RAISE(ABORT)` on SQLite) — the append-only guarantee `10-accounts.sh`
    noted it couldn't express as a `REVOKE`.
  - `app/audit.py::log_access` (the single audit-write chokepoint) advances
    the chain tip in-transaction under a lock (`SELECT ... FOR UPDATE` /
    process lock). `row_hash` = HMAC-SHA256(SECRET_KEY, domain-separated).
  - `verify_chain()` + `db/verify_audit_chain.py` (CLI, exit 1 on a break) +
    `GET /admin/audit/chain-status` (admin). `seal_day()` +
    `db/seal_audit_day.py` (cron) write the daily WORM anchor, best-effort
    mirrored to the `clarion-reports-archive` bucket.
  - `docs/deployment.md` gets an "Audit hash chain" section (verify cadence,
    seal cron, and why retention is a partition-drop DDL job now, not a DELETE).
  - `test_audit_hash_chain.py` (18): intact/gap-free/linked chain, trigger
    blocks UPDATE+DELETE, verify detects altered row / deleted-middle gap /
    deleted tail / mid-chain forge, seal idempotency + tamper-raise, WORM
    readback, concurrent-append tolerance, **migration back-fill over real
    pre-P2.9 rows + restartability**, both CLIs (exit codes).
  - **voltagent security review + 5-agent `/code-review` actioned:**
    WORM seal is now re-read on verify (`verify_chain(check_worm=True)`,
    `--worm` cron flag) — it was written but never checked (tail-truncation
    hole); `verify_chain` reads the chain tip *first* to stop false alarms
    from concurrent writers; `log_access` gets a cross-process `flock` on the
    SQLite path (the demo runs 4 gunicorn workers on one file, where the
    `FOR UPDATE` is a no-op); the migration is now restartable (inspector
    guards + trigger-drop-during-backfill + skip-if-already-filled) and
    streamed/batched for a large table; hash construction extracted to
    stdlib-only `app/audit_hash.py` shared by app + migration (kills the
    copy-paste drift hazard); `ChainReport` → dataclass; failed WORM mirror
    retried on the next seal; CLI flag conflicts rejected; `audit.py` fails
    closed on an empty `SECRET_KEY`. Residuals documented in
    `docs/deployment.md` (INSERT-wedge DoS by a privileged account; the
    `log_access` "log last" contract; `SECRET_KEY` rotation = chain re-baseline).
  - Verified: 206/206 pytest, `db.check_schema` PASS (SQLite), real-data
    back-fill on `clarion.db` (14 rows → chain intact + `--worm` OK), runtime
    append + trigger enforcement + seal + both CLIs. **MariaDB run still
    owed** (no local creds this session).
  - Still open in P2: P2.7 encryption-at-rest, P2.8 backup/DR, P2.10 PDPA,
    P2.11 offline CI, P2.12 data-quality alerts.

### 2026-09-07 — P2 security wave + refactors
- **P0.2** — `git rm -r mobile/` (legacy RN app), deleted stray `comiin.db` + stale
  Flutter build cache; renamed the Flutter root widget `MediBridgeApp` → `ClarionApp`.
- **P1.10** — LDAP/AD as an opt-in second auth provider (`LDAP_ENABLED`): service-bind →
  search → user-rebind, JIT provision, admin-editable `LdapRoleMapping`. Empty-password
  pre-bind rejection, filter-injection escaping, directory-outage reads as "wrong
  password", denies rather than defaulting a role. Then **voltagent security review
  actioned** — C1 identity keyed on the wrong field (`email` vs the raw login string) →
  new `User.ldap_username`; unthrottled LDAP DoS → concurrency semaphore; facility priv-esc
  in the admin CRUD; **no TLS cert validation** (`ldap3` default is `CERT_NONE`) → explicit
  `Tls(CERT_REQUIRED)` + `LDAP_CA_CERT_FILE`; plaintext-LDAP silent default → refuses to
  bind without TLS unless `LDAP_ALLOW_INSECURE_BIND=true`; JIT-provision race guards.
  Fixed a repo-wide bug: `alembic/env.py` `fileConfig()` was disabling every `app.*`
  logger. `test_ldap_auth.py` (23) + `test_admin_ldap_role_mappings.py` (10).
- **P1.12** — `backend/tests/conftest.py` shared TestClient + throwaway-SQLite scaffold;
  `test_auth_rbac_immutability.py` (7 — RBAC, page-access gating, cross-hospital
  immutability).
- **P1.13** — Flutter release signing wired (`android/key.properties`, git-ignored,
  debug-key fallback with a loud warning). Real keystore generation is the team's step.
- **P2.1–P2.5** — [[Security Audit]] H1, H2, H3, M1/M2, M4 fixed (P2.2 + P2.5 designs
  confirmed with the user first). See the Security Audit for the per-finding summary.
- **P2.6** — M5 (image-upload magic-byte validation; AV hook re-scoped to PTM per the
  tender), M6 (emergency-scan audit binds the real staff identity when a token is
  present), M7 (HMAC the NFC UID at rest + `nfc_uid_last4` + revoke-by-id + scan-anomaly
  logging + age-not-DOB scan payload), M8 (log the row id, not the clinical value).
  **P2.6 fully closes the P2 High/Medium security wave.**
- **Post-P2 code-review passes** (parallel-agent `/code-review`, 5 passes):
  1. Found CR1 (MyKad photos staged for commit), CR2 (`/patients/{id}/appointments`
     under-authorized — same shape as H1/H2), CR3/CR4 (event-loop-blocking OCR /
     external-API fan-out), CR5 (irreversible migration, no enforced prerequisite),
     CR6 (missing indexes + N+1), CR7 (500 handler + correlation id), CR8 (dep hygiene).
  2. CR9 (refresh cookie `Path=/auth` never sent on `/api/auth/refresh` → silent-refresh
     dead), CR10 (concurrent-tab refresh nuked every session; + a pre-existing
     double-issue orphaned-token bug), CR11 (duplication → `app/directory.py`,
     `web/src/lib/*`), CR12 (auth test-coverage gaps).
  3. LDAP facility-admin → admin-role escalation decided + fixed; `PatientDetail.jsx`
     `exhaustive-deps` fixed properly; refresh-token `client_fingerprint` device binding
     (migration `e7c1a9b3f2d4`); lower-sev N+1 + pagination; `consultation.py` stopped
     calling `reception.py` route handlers as functions (`_*_impl` helpers).
  4. **Delegated god-file splits** (voltagent + Claude-verified): `AdminConsole.jsx`
     2447→42 lines into `web/src/pages/admin/*`; `admin.py` medicine-inventory helpers →
     `app/inventory.py` (kills the `pharmacy.py → admin.py` service import).
  5. Verified those two splits with a full parallel-agent review — clean.
- **`reception.py` (1456 lines) → `app/routers/reception/` package** (voltagent +
  Claude-verified + reviewed) — `checkin` / `queue` / `stations` / `rooms` /
  `admissions` sub-routers combined in `__init__.py` (re-exports the helpers
  `consultation.py` / `admin.py` / `display.py` / `patients.py` import). First HTTP
  coverage of `/reception/*` (`test_reception_smoke.py`, 5).

### 2026-08-30 — P0.4 + P1 foundations + first Security Audit
- **P1.1–P1.5** — Alembic + reviewed baseline; `models.py` portability sweep; MariaDB
  11.4 container + env-driven `DATABASE_URL` + pool + 3 least-priv accounts;
  `DATETIME(6)` precision variant (P1.2b, from the DBA review); SQLite→MariaDB data
  migrator with type coercion + orphan check + reconciliation report;
  `_migrate_lightweight()` + `create_all()` deleted, `db/check_schema.py` CI gate.
  Bugs fixed along the way: `SessionLocal` dropped, `5e6a60dfe274` FK-unsafe downgrade,
  `10-accounts.sh` `REVOKE` on a table (MariaDB error 1147).
- **P1.6** — `ObjectStore` ABC + `LocalObjectStore` + `MinioObjectStore` + env factory;
  the 5 `*_path` columns → `*_object_key` + `*_sha256` + `*_bytes` + `*_mime`; two
  Alembic revs (add, then drop) + `migrate_uploads_to_objectstore.py`. **Lesson:** the
  first attempt was a `--yolo` delegation to agy that ran detached and raced the cleanup.
  Lesson: no `--yolo` for cross-cutting refactors; verify everything. Redone in
  Claude-owned staged passes.
  voltagent security review: WORM buckets weren't actually created with `object_lock`;
  DoS cap checked after full `.read()`; MinIO conn leak; sha256 never verified on read.
- **P1.7** — `app/imaging.py` (Pillow bytes→bytes: EXIF/GPS strip, resize, thumbnail,
  pixel-bomb + frame guards, format allowlist) + `app/derived.py` (`clarion-derived`
  bucket). voltagent arch + security reviews actioned (~15 fixes + 1 bug: stale
  medicine thumbnail on same-name re-upload → derived key now folds the source sha).
  Async worker deferred to **P1.7b**.
- **P1.8** — env-driven config: wired the web SPA to consume `/config.js` → `VITE_API_BASE`
  → localhost; `entrypoint.sh` `$API_BASE` injection-hardened; removed
  `--forwarded-allow-ips "*"` (XFF spoof → forged rate-limit key). CORS fail-closed
  (see [[Security Audit#M3]]).
- **P1.9** — `proxy/Caddyfile` (Caddy 2.8): the single TLS-terminating entry point, HSTS
  + strict CSP + security headers, `/api`→backend routing; the only service publishing
  host ports; pinned `172.28.0.2` = the `FORWARDED_ALLOW_IPS` trust anchor. voltagent
  infra-security review: dropped HSTS `preload`, added edge timeouts + header cap, split
  into `edge` + `internal` compose networks. Bug fixed: 4 gunicorn workers raced
  `alembic upgrade` on one SQLite file → POSIX file lock.
- **P1.11** — full-stack compose (backend, web, mariadb, minio, redis, orthanc) +
  Dockerfiles + `docs/deployment.md`. Offline image bundle + Docker secrets still TODO.
- **P0.4** — `_cloud_guard.py`; `summarize.py` + `nric_ocr.py` gate the Anthropic path
  on `cloud_ai_enabled()` (needs `ANTHROPIC_API_KEY` AND `CLARION_ALLOW_CLOUD_AI=1`).

---

## P0 — Hygiene
| # | Task | Size | Why | Status |
|---|---|---|---|---|
| P0.1 | Commit the untracked backend routers + working tree in reviewable chunks | S | — | user handles commits |
| P0.2 | Delete legacy `mobile/` (RN app) + stale `comiin.db`; reconcile MediBridge/comiin/CLARION naming | S | Cruft | ✅ 2026-09-07 |
| P0.3 | `AGENTS.md` at repo root pointing agents at this vault | S | Cheap context load | ✅ 2026-08-30 |
| P0.4 | Guard the Anthropic cloud path — off unless an explicit dev override is set | S | [[Security Audit#C1]] | ✅ 2026-08-30 |

## P1 — Foundations (language-independent; survives the CI4 port)
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P1.1 | `MetaData` naming convention + Alembic + reviewed baseline + `stamp head` | M | | ✅ 2026-08-30 |
| P1.2 | Portability sweep of `models.py` — the SQLite-isms in [[On-Prem Architecture]] | M | | ✅ 2026-08-30 |
| P1.3 | MariaDB 11.4 container + env-driven DB URL + pool + 3 least-priv grants + RoomClaim active-unique | S | | ✅ 2026-08-30 |
| P1.2b | MariaDB precision: `DateTime`→`DATETIME(6)` variant + audit `id`-tiebreak *(FK `ondelete` deferred — no delete path exists)* | S | | ✅ 2026-08-30 |
| P1.4 | SQLite→MariaDB data migration w/ type coercion + orphan check + reconciliation report | M | | ✅ 2026-08-30 |
| P1.5 | Delete `_migrate_lightweight` + `create_all`; `db/check_schema.py` CI gate | S | / [[Security Audit#M9]] | ✅ 2026-08-30 |
| P1.6 | `ObjectStore` abstraction + MinIO + `*_object_key` columns + move `uploads/` | M | | ✅ 2026-08-30 |
| P1.7 | Image-normalisation pipeline (Pillow: EXIF/GPS strip, resize, thumbnail) | S | | ✅ 2026-08-30 (sync-at-upload; async worker → P1.7b) |
| P1.7b | Imaging follow-ups: PDF first-page preview (`pypdfium2`, not AGPL PyMuPDF); ~1400px web-preview variant (cuts the 15MB original off the Branch WAN, metadata-stripped by default); HEIC input; async job seam = MariaDB `jobs` table + `FOR UPDATE SKIP LOCKED` (not rq/Celery — survives the CI4 port); consolidate the 3 magic-byte sniff copies; ETag on derived responses; bump `clarion-derived` ILM 30→180d | M | | — |
| P1.8 | Env-driven config — kill hardcoded `localhost`, CORS allowlist, runtime `config.js` | S | / [[Security Audit#M3]] | ✅ 2026-08-30 |
| P1.9 | Reverse proxy (Caddy) + CAMPUS-CA TLS + CSP + HSTS | S | | ✅ 2026-08-30 (prod TODO: drop the CAMPUS-CA cert in `proxy/certs/`, flip `CLARION_TLS_DIRECTIVE`; tighten `style-src`) |
| P1.10 | **LDAP/AD** provider — service bind → search → user bind, JIT provision, `ldap_role_map` | M | **** | ✅ 2026-09-07 (backend + admin CRUD; no web UI yet) |
| P1.11 | Containerise full stack + offline image bundle/registry + Docker secrets | M | | ✅ 2026-08-30 (offline bundle + secrets still TODO) |
| P1.12 | Backend `pytest` suite scaffold (auth, RBAC, cross-facility immutability first) | M | 10.1.5 | ✅ 2026-09-07 |
| P1.13 | Flutter release signing (real keystore + `key.properties`) | S | — | ✅ 2026-09-07 (wiring + docs; real keystore is the team's step) |

## P2 — Security & compliance
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P2.1 | Fix [[Security Audit]] H1 — gate emergency endpoints + facility scoping | M | | ✅ 2026-09-07 |
| P2.2 | Fix H2 — default-deny cross-facility, reason-logged break-glass, scope + paginate `list_patients` | M | | ✅ 2026-09-07 |
| P2.3 | Fix H3 — random seed passwords + `must_change_password`; staff password policy | S | | ✅ 2026-09-07 |
| P2.4 | Fix M1/M2 — per-IP login + OTP throttle; indexed normalized-NRIC column | S | | ✅ 2026-09-07 |
| P2.5 | Fix M4 — short access-token TTL + refresh token (HttpOnly cookie / secure storage) + real logout | M | | ✅ 2026-09-07 (app-level CSP residual) |
| P2.6 | Fix M5/M6/M7/M8 — upload validation; verified scan audit identity; HMAC card key + minimise payload; stop logging clinical values | M | | ✅ 2026-09-07 (residuals: M7 physical-clone, 1yr expiry by choice — see Security Audit) |
| P2.7 | Encryption at rest — MariaDB encrypted tablespaces + on-prem key management | M | | ✅ 2026-09-08 (Community file_key_management path wired into compose; LUKS + Enterprise/Vault documented; not container-tested) |
| P2.8 | **Backup / DR regime** — daily incr + weekly full + binlog shipping, encrypted, 30-day, pre-update image, quarterly restore test, documented RPO/RTO | L | **** | ✅ 2026-09-08 (`backend/backup/` scripts + compose `backup` service + DR runbook; offsite target = config; not container-run) |
| P2.9 | Audit **hash-chain** + daily WORM seal + retention/partition policy | M | | ✅ 2026-09-08 (SQLite-verified; MariaDB migration written, pending a run with creds) |
| P2.10 | PDPA — consent model + data-subject-request flow + DPO register + retention config | M | | ✅ 2026-09-08 (backend + API; no erasure flow — Malaysian PDPA has none; retention = flag-only; no web UI) |
| P2.11 | Offline CI: Gitea + ruff/pytest/bandit/semgrep/pip-audit/trivy + alembic up/down check | M | | ✅ 2026-09-08 (portable `ci/run.sh` + Woodpecker YAML + Makefile; osv-scanner not pip-audit; forge-agnostic) |
| P2.12 | `data_quality_alerts` — batch validators (missing values, dup patients, bad coding) | S | | ✅ 2026-09-08 (backend + admin API; no web UI yet) |

## P3 — Tender modules
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P3.1 | **Ancillary engine** — `service_catalog_items`/`service_requests`/`service_results`: order → result → sign-off → document, shared across Procedure, Laboratory, X-ray, Physiotherapy | L | –10 | ✅ 2026-09-11 |
| P3.2 | **Dental module** + tooth-chart UI (FDI notation) | M | | ✅ 2026-09-13 |
| P3.3 | **Billing module** — charge master, `bills`, `bill_items`, `payments`, `claims`; wire consultation / pharmacy / ancillary fees | L | + per-module billing | ✅ 2026-09-13 |
| P3.4 | Consultation: structured **SOAP** notes, treatment plan, follow-up scheduling, referral UI | M | –4 | ✅ 2026-09-13 |
| P3.5 | Document generation — Digital Medical Certificate, Referral Letter, Timeslip (PDF) | M | | ✅ 2026-09-13 |
| P3.6 | **Reporting engine** + **Custom Report Builder** (field picker across modules, filter/group, template store) | L | | ✅ 2026-09-13 |
| P3.7 | **MOH / statutory reporting** — notifiable disease (e-Notifikasi format), HMIS returns, anonymization | M | | ✅ 2026-09-13 |
| P3.8 | **Management Dashboard** — KPI view + patient-flow prediction (EWMA/GBM) + operational health score | M | | ✅ 2026-09-13 |
| P3.9 | Calling-system hardware — ticket printer (ESC/POS), TV display **audio** + branding | S | –3 | ✅ 2026-09-14 (reviewed, fixes landed) |
| P3.10 | Mobile: slot booking by dept/doctor, vitals view, PDF visit summary, server push, announcements | M | –5 | ✅ 2026-09-14 (reviewed, fixes landed) |

## P4 — Interoperability, AI & imaging
| # | Task | Size | Clause | Status |
|---|---|---|---|---|
| P4.1 | **FHIR-readiness migrations** — coding triples, `resource_identifiers`, resource tables, terminology seeds, backfill queue | L | **** → [[FHIR Schema Readiness]] | ✅ 2026-09-14 (coding triples + `resource_identifiers`; no seed terminology/backfill queue — see changelog) |
| P4.2 | Thin **read-only FHIR façade** + CapabilityStatement | L | | ✅ 2026-09-14 |
| P4.3 | **On-prem AI engine, core** — replace ALL Claude-API calls with a local Ollama client (`ai/local_llm.py`); handover summary + MyKad OCR rewired, deterministic/Tesseract fallback preserved | L | **–17** → [[On-Prem Clinical AI]] | ✅ 2026-09-13 |
| P4.3b | **CDS hint** — differential-dx/contraindication reference note mid-consult (`/consultation/tickets/{id}/cds-hint`) + deterministic allergy-vs-active-medication conflict flag, on top of P4.3's local-LLM plumbing | M | → [[On-Prem Clinical AI]] | ✅ 2026-09-13 |
| P4.3c | **Voice→SOAP** — `faster-whisper` dictation transcribed + segmented into SOAP fields (`/consultation/tickets/{id}/voice-to-soap`) + **NL report narrative** — local-LLM prose summary over the Reporting engine's structured output (`/reports/narrative`) | M |, → [[On-Prem Clinical AI]] | ✅ 2026-09-14 |
| P4.4 | Medication-safety = rule engine + licensed drug DB (MIMS) integration | M | | 🟡 2026-09-14 (ATC drug-class layer + real-time pre-save alert done; MIMS itself out of reach — no public API; diagnosis-based screening not attempted) |
| P4.5 | AI audit-trail intelligence + access anomaly detection over the hash-chain | M | –7 | ✅ 2026-09-14 |
| P4.6 | Predictive analytics + population-health stratification in Reporting | M | | — |
| P4.7 | **PACS** — Orthanc + PG index + S3 plugin + Modality Worklist + OHIF viewer + auto-link | L | **** → [[PACS and DICOM]] | 🟡 2026-09-14 (core + PG index/S3/auth all done; real Modality Worklist — needs hardware — still open) |
| P4.8 | Integration layer — SMP / SMS / e-klinik / Registrar (read-only) + lab-analyser HL7 v2 service + label printers | L | → [[Integration Engine and LDAP]] | — |

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
