---
title: Compliance Matrix
type: assessment
updated: 2026-08-30
tags: [compliance, tender, clarion, matrix]
---

# Compliance Matrix — CLARION vs

Status: **Have** (works today) · **Partial** · **Gap** (new build) · **Port** (exists,
PHP rewrite must redo) · **N/A** (contractual / process). *Demo?* = worth showing on
stage. Judged on functional behaviour in the codebase, not polish.

Rough totals across Section 10: **~18 Have · ~21 Partial · ~44 Gap · ~17 N/A.**

> [!warning] Scored 2026-08-30, **not re-scored after P1/P2**. Since then: MariaDB path,
> ObjectStore/MinIO, edge proxy + TLS, LDAP/AD, containerisation, and the whole P2
> security wave landed — several rows have moved Gap/Partial → Have. Treat
> [[Implementation Roadmap]] as the current-status source; re-score this matrix as its
> own task before any formal compliance submission.

## Modules

| Clause        | Requirement                                                                    | Status  | Work                                                                                                     | Demo?                  |
| ------------- | ------------------------------------------------------------------------------ | ------- | -------------------------------------------------------------------------------------------------------- | ---------------------- |
| | Dashboard: queue/attended/availability/wait KPIs | Partial | Build a management dashboard over `queue_tickets`, `staff_clock_events`, `room_claims` | Yes |
| | Patient-flow **prediction** engine | Gap | EWMA / gradient-boosted over historical queue + appointments | Yes (flagship) |
| | Real-time **operational health score** | Gap | Composite index; cheap once referrals exist | Yes |
| | Frontdesk ↔ SMP/SMS/e-klinik; Registrar eligibility | Gap | Mock adapter + documented integration layer | Mock |
| | Pre-registration (self-register before visit) | Have | `self_registration.py` + Flutter self_register | Yes |
| | Patient mgmt: CRUD, assign physician, payment method | Partial | CRUD + room/queue assign present; payment-method setting = Gap | Yes |
| | Appointments: manage, reminders, history, reschedule | Have | `appointments.py` + reschedule requests; reminder *delivery* job = Gap | Yes |
| | Staff mgmt: available physician & room, logged-in users | Have | `reception.py` Rooms + `staff.py` + `consultation.py` my-room | Yes |
| | Frontdesk **Billing**: invoice, receipt, payment tracking | Gap | Billing module | Yes |
| | Report & Analysis: demography + charges | Partial | Some admin reporting; demography + charges = Gap | — |
| | Consultation **sign** feature | Have | Signed Encounter + `ClinicalRecordAnnotation` + signature pad | Yes |
| | Physician views queues, sets appointments | Have | `consultation.py` my-room worklist | Yes |
| | Progress notes, diagnosis, treatment plan, follow-up | Partial | Encounters + conditions exist; structured treatment plan / SOAP / follow-up = Gap | Yes |
| | **References** — refer to physio/X-ray/lab/outsource, review results | Gap | No referral entity; `service_requests` table + the ancillary modules | Yes |
| | Medication: prescribe/edit/delete/update | Partial | `medication_statements` + dispense; prescribing UI in consultation = Gap; immutability model vs "delete" | Yes |
| | Reporting: lab/X-ray/physio reports, Digital MC, Referral Letter, Timeslip | Gap | PDF document generation | Yes (Digital MC) |
| | Consultation fees | Gap | Billing module | — |
| | **Clinical decision support layer** | Partial | `ai/summarize.py` + `ai/interactions.py` exist but cloud + rule table → [[On-Prem Clinical AI]] | Yes (flagship) |
| | **Medication safety engine** (allergy/med/dx screening) | Partial | `ai/interactions.py` + RxNorm/RxClass (P4.4: ATC drug-class layer, wired as a real-time pre-save alert, `GET /ai/prescription-screen`); no licensed formulary (MIMS has no public API) and no diagnosis-based screening | Yes (flagship) |
| | **Voice → SOAP** transcription | Gap | `faster-whisper` + SOAP segmentation | Yes (flagship) |
| | Pharmacy: view queue & appointments | Have | `pharmacy.py` + role-page access | Yes |
| | Dispensing: dispense, history, update, **print label** | Partial | Dispense + history Have; label printing = Gap | Yes |
| | Stock mgmt: Stock Master + Unit, expiry, vendor, purchasing, reorder | Have | `medicine_inventory` + `medicine_purchase_proposals` + budgets + low-stock | Yes |
| | Medication records: view/add/update/delete | Partial | Records exist; delete constrained by immutability | — |
| | Pharmacy billing | Gap | Billing module | — |
| | Admin: user/role mgmt, password reset, access monitoring, change notify | Have | `admin.py` roster + `permissions.py` matrix + Access Control tab; change-notification = Gap | Yes |
| | Admin: patient mgmt, history/appointments | Have | `admin.py` + `patients.py` | — |
| | Admin: appointment slots, reminders | Partial | Dashboard exists; reminder-delivery job = Gap | — |
| | Admin billing + SMP/SMS/e-klinik | Gap | Billing + integrations | — |
| | Patient medical-info reports, data export | Partial | Some export; comprehensive reporting = Gap | — |
| | System Configuration: notifications, content/text/appearance | Partial | `hospital_settings` + admin config; content/appearance CMS = Gap | — |
| | Security Management: data recovery/backup, security protocol | Have | `backend/backup/` + DR runbook (P2.8); security protocol via [[Security Audit]] | — |
| | **Billing Module** | Gap | New module: `bills`, `bill_items`, `payments`, `claims`, charge master | Yes |
| | **Procedure Module** | Partial | P3.1 ✅ 2026-09-11: shared order→result→sign-off→document engine + catalog. No procedure-specific UI polish yet | Yes |
| | **Laboratory Module** (+ direct reg, result-interpretation AI, trend analysis) | Partial | P3.1 ✅ shared engine covers order/result/sign-off/document; analyser HL7 (P4.8), AI interpretation + trend analysis (P4.5/8.4-8.5) still Gap | Yes |
| | **X-ray Module** (+ direct reg) | Partial | P3.1 ✅ shared engine covers order/result/sign-off/document; PACS/DICOM tie-in (P4.7 🟡) now core-done, see below | Yes |
| | **Physiotherapy Module** (+ direct reg) | Partial | P3.1 ✅ fully covered by the shared engine — no external integration needed for this module | Yes |
| | **Dental Module** (sign-off, dental chart, references, medication, reporting) | Gap | New module; dental chart = bespoke UI | Partial |
| | Reporting: admission/discharge summaries, disease-specific, TAT, PDF+Excel | Partial | AI handover ≈ discharge summary; rest = Gap | Yes |
| | Operational performance reports; auto daily/weekly/monthly | Gap | Reporting engine + scheduled jobs | — |
| | **MOH reporting standards** + notifiable disease + anonymization | Gap | [[Malaysia Health Regulation]]; e-Notifikasi formats | Yes (compliance story) |
| | Financial performance reports | Gap | Billing module | — |
| | **Custom Report Builder** (no-IT, save/share templates) | Gap | Field picker across modules, filter/group, template store | Yes |
| | Real-time interactive dashboards & analytics | Partial | Overlaps; trend/comparative stats = Gap | Yes |
| | **Predictive analytics** (visits, disease burden, stock depletion) | Gap | Same engine family as | Yes |
| | **Automated clinical insight engine** (NL summary reports) | Partial | `ai/summarize.py` pattern; local model + report framing | Yes (flagship) |
| | **Population health stratification** (risk clustering) | Gap | Analytics over conditions/encounters | Yes |
| –2 | Mobile via secure API; full API support | Have | FastAPI is API-first; Flutter consumes it | Yes |
| | Mobile pre-registration (location/dept/doctor, slot, confirm, reschedule) | Have | P3.10 (2026-09-14): `GET /patients/booking-options` + `/appointment-slots` + `POST.../self-book`; Flutter `book_appointment_screen.dart`. Reschedule/cancel already existed (P2-era). Facility picker sourced from the patient's own encounter history (no facility directory table exists) — documented limitation, not a gap in the booking mechanics themselves | Yes |
| | Mobile: view visits, vitals, notes, prescriptions, PDF summary | Have | P3.10: `ConsultationNote.bp_systolic/diastolic/temperature_c/pulse_bpm` captured at sign-off, surfaced on the patient's own record read; `GET /patients/{id}/encounters/{id}/visit-summary.pdf` rendered on the fly (reportlab, reuses the P3.5 signed-document pattern); Flutter home_screen.dart encounter card + share button. Prescriptions were already Have via `activeMedications` | Yes |
| | Mobile real-time alerts (reminders, test results, announcements) | Have | P3.10: `Announcement` model + admin CRUD + `GET /patients/announcements`, polled the same way server-published appointments already were (`RemindersProvider.syncAnnouncements`) — deliberately polling, not FCM/push, to avoid a third-party cloud dependency (no Firebase project available, and it keeps the on-prem posture the rest of this project has held). "Test-result availability" alerts specifically are still not a distinct notification — ancillary results are visible on next app open/poll but don't yet trigger their own push-style alert | Partial |
| | Calling System: queue numbers by type, auto-assign | Have | `reception.py` `queue_tickets` + per-section | Yes |
| | Ticket **printer** | Demo | P3.9 (2026-09-14): `backend/app/printing.py` builds real ESC/POS ticket bytes, `GET /reception/queue/{id}/ticket.escpos` + a web "Print ticket" button. No physical thermal printer attached in this environment to test against — wiring the bytes to real hardware (a local print-spooler/kiosk config) is a documented deploy-time step, same as the TLS cert pair at P1.9 | Demo |
| | Central **TV display** of queue + counters/rooms | Have | `display.py` `/display/{token}` full-screen auto-refresh | Yes |
| | Role-based call next / hold / skip; monitor per type | Have | `reception.py` call/complete/cancel/no-show | Yes |
| –5 | **PACS / DICOM** | Partial | P4.7 🟡 2026-09-14: Orthanc + upload + embedded dwv zoom/pan/window-level/measure viewer done; PG index/S3 plugins, Orthanc auth, real Modality Worklist auto-link still Gap → [[PACS and DICOM]] | Yes (impressive) |

## System Technology

| Clause | Requirement | Status | Note |
|---|---|---|---|
| | PHP CodeIgniter 4 | Port | Demo FastAPI → [[Designing for the PHP Port]] |
| | Linux OS | Have | uvicorn on Linux |
| | Web responsive | Partial | React + Tailwind; audit responsiveness |
| –6,.9–10 | The University provides hosting/network/AV; security via PTM | N/A | Contractual |
| | Integrate label printer, blood-test machine, X-ray viewer | Partial | Label printer = Demo (P3.9, see the tender); blood-test machine / X-ray viewer integration itself still Gap → |
| | Integrate SMP / SMS / e-klinik | Gap | Mock adapters + integration layer |
| –13 | DB/hosting compatibility, secure/scalable config | Partial | [[On-Prem Architecture]] |
| | Resize uploaded images | Gap | Pillow resize on upload (easy) |
| | **Embedded AI, NO cloud APIs**, offline | Gap (conflict) | [[On-Prem Clinical AI]] — biggest bet |
| | Federated model updating | Gap | = periodic local LoRA fine-tune |
| | Demonstrate proprietary/licensed AI engine (ALi.ai or equiv) | Gap | ALi.ai = MAIA; partnership vs OSS |

## Development Guidelines

| Clause | Requirement | Status | Note |
|---|---|---|---|
| | OWASP | Partial | [[Security Audit]] drives this; CI enforces (ruff/bandit/semgrep, P2.11) |
| –6 | Structured normalized scalable DB; tables/indexes/procs/views; schema docs | Partial | 30 tables; no stored procs/views (fine); schema docs = Gap |
| –8 | The University hosts DB; vendor supplies no DB server | N/A | App connects to University MariaDB |
| | AI-assisted code quality / OWASP review in pipeline | Partial | `ci/run.sh` = ruff + bandit + semgrep(local rules) + osv-scanner + check_schema + pytest (P2.11, 2026-09-08); LLM-review step still to add |
| | **FHIR-compatible schema**, MySejahtera/PADU interop | Have | [[FHIR Schema Readiness]] — coding triples + `resource_identifiers` + read-only façade landed 2026-09-14 (P4.1/P4.2) |
| | Automated data-quality monitoring | Have | `app/data_quality.py` (13 batch rules: missing / duplicate / coding / anomaly) → `data_quality_alerts` (UPSERT + auto-resolve); `db/data_quality_scan.py` cron; admin list/summary/acknowledge/resolve; `DATA_QUALITY_DISABLED_RULES` config (P2.12, 2026-09-08) |

## Integration, Migration, Auth

| Clause | Requirement | Status | Note |
|---|---|---|---|
| –2 | Integrate university DBs (student/staff); fully integrable | Gap | Read-only connector to the University identity source; mock for demo |
| –5 | External hardware/device via REST/JSON; middleware service layer | Gap | Integration engine → [[Integration Engine and LDAP]] |
| | Import from existing clinical system | Gap | ETL; depends on legacy format |
| –9 | Secure, read-only, real-time/scheduled sync | Gap | Design in architecture |
| | Integrate lab machines, X-ray viewers, label printers | Gap | |

## Security

| Clause | Requirement | Status | Note |
|---|---|---|---|
| | PDPA: encryption at rest+transit, RBAC, audit, retention | Partial | RBAC + append-only `audit_logs` Have; **encryption at rest** = MariaDB TDE (`file_key_management`) + `encrypt_binlog`/`_log`/`_tmp` wired into compose + LUKS documented (P2.7, 2026-09-08); in transit = Caddy TLS (P1.9), MariaDB `REQUIRE SSL` still owed; consent ledger + data-subject-request workflow + DPO register + flag-only retention schedule = `routers/pdpa.py` + `app/retention.py` (P2.10, 2026-09-08 -- no erasure flow: Malaysian PDPA has none) |
| | Security control module: access by role | Have | `permissions.py` + Access Control tab |
| | Credentials + **LDAP** | Gap | [[Integration Engine and LDAP]] |
| | Intelligent anomaly detection | Partial | P4.5: `app/security_analytics.py` -- 2 hardcoded-threshold rules (patient fan-out, off-hours access) over `audit_logs`, no manual rule config as asked; periodic scan (cron + on-demand), not literally synchronous real-time; no admin web tab (API only, same as data-quality alerts) |
| | AI-driven audit-trail intelligence | Partial | P4.5: `ai/audit_intelligence.py` local-LLM narrative over an already-flagged alert (`POST /admin/security-alerts/{id}/explain`) -- context/prioritisation only, the LLM never decides what counts as an anomaly |
| | Continuous automated vuln assessment of own code + APIs | Partial | SAST (bandit/semgrep) + SCA (osv-scanner) + trivy in `ci/run.sh` (P2.11); DAST still a gap |

##

| Clause | Requirement | Status | Note |
|---|---|---|---|
| | System Admin controls access via Module facility | Have | Access Control tab |
| | Dedicated DB server, on-prem, enterprise RDBMS | Gap | SQLite → MariaDB → [[On-Prem Architecture]] |
| | Automated encrypted backups, 30-day, image snapshot, quarterly restore, RPO/RTO | Have | `backend/backup/` (backup.sh + restore-test.sh + pre-update-snapshot.sh) + compose `backup` service + DR runbook (P2.8, 2026-09-08); offsite target = deploy config |
| | Integrate with the University hosting, collaborate with infra team | N/A | Contractual |
| | ≥2 onsite support staff, 2 years | N/A | Contractual / bid |
| | Lab machine API integration (bidirectional, standards, test env) | Gap | HL7 v2 / ASTM → [[Integration Engine and LDAP]] |
| | Label printer + calling-system printer (templates: name, IC, barcode) | Demo | P3.9: `printing.py::build_sample_label_png` (patient name/IC/item + QR, `GET /ancillary/requests/{id}/label`) + `build_ticket_escpos` (`GET /reception/queue/{id}/ticket.escpos`). QR used in place of Code128 (this codebase already depends on `qrcode`, not a barcode symbology lib, and has no Code128 reader anywhere to justify adding one). No physical printer attached to test against — real hardware wiring is a deploy-time step |
| | Calling-system TV: queue, counters, names/initials, visual + **audio** | Have | P3.9: `display.py` visual (pre-existing) + Web Audio chime/SpeechSynthesis call-out + branding (logo/accent color from `HospitalSetting`) in `WaitingRoomDisplay.jsx` |

## 10.1 / 10.3 (process / personnel)

| Clause | Requirement | Status | Note |
|---|---|---|---|
| 10.1.1–1.3, 1.9 | URS sessions, work schedule, SRS report | N/A | Bid deliverables |
| 10.1.4 | UAT | N/A | Process |
| 10.1.5 | Security Acceptance Testing (campus-run) | Gap | Feeds P2 security work |
| 10.1.6 | Source code owned by the University; disclose OSS vs proprietary | N/A | License inventory needed (esp. AI model licences) |
| 10.1.7 | Linux compatible | Have | |
| 10.1.8 | 2-yr warranty, 24h response | N/A | Contractual |
| 10.3.2 | MBOT-registered Technologist | N/A | Risk register — does the team have one? |
| 10.3.3 | MMC-registered Clinical Advisor | N/A | Risk register |
| 10.3.4 | HIMSS/HL7 health-informatics competency | N/A | Risk register |

---

Feeds [[Implementation Roadmap]]. Big-ticket gaps ranked in [[Module Coverage]].
