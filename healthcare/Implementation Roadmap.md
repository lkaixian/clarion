---
title: Implementation Roadmap
type: plan
updated: 2026-09-13
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
| P3.4 | Consultation: structured **SOAP** notes, treatment plan, follow-up scheduling, referral UI | M | –4 | 🔶 in progress (separate session, 2026-09-13) — schema-drift bug fixed on review; annotation-correction wiring + follow_up_at/referral UI + fuller test coverage still open |
| P3.5 | Document generation — Digital Medical Certificate, Referral Letter, Timeslip (PDF) | M | | |
| P3.6 | **Reporting engine** + **Custom Report Builder** (field picker across modules, filter/group, template store) | L | | |
| P3.7 | **MOH / statutory reporting** — notifiable disease (e-Notifikasi format), HMIS returns, anonymization | M | | |
| P3.8 | **Management Dashboard** — KPI view + patient-flow prediction (EWMA/GBM) + operational health score | M | | |
| P3.9 | Calling-system hardware — ticket printer (ESC/POS), TV display **audio** + branding | S | –3 | |
| P3.10 | Mobile: slot booking by dept/doctor, vitals view, PDF visit summary, server push, announcements | M | –5 | |

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
