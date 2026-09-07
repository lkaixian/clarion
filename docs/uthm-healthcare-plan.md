# UTHM HealthCare — Implementation Plan

> Canonical version lives in the Obsidian vault at `healthcare/Implementation Roadmap.md` with cross-links. This is the repo mirror. Companion: `docs/tender-clauses.md`.


## P0 — Hygiene (do now, ~1 week)
| # | Task | Size | Why |
|---|---|---|---|
| P0.1 | Commit the ~7 untracked backend routers + working tree in reviewable chunks | S | Half the codebase is uncommitted incl. `reception`, `pharmacy`, `consultation`, `display`, `profile`, `self_registration`, `permissions.py` |
| P0.2 | Delete legacy `mobile/` (RN app) + stale `comiin.db`; reconcile MediBridge/comiin/CLARION naming | S | Cruft |
| P0.3 | Add `AGENTS.md` at repo root pointing agents at this vault | S | So future sessions load context cheaply |
| P0.4 | **Guard against `ANTHROPIC_API_KEY`** — refuse to start unless an explicit dev override is set | S | [[Security Audit#C1]] interim mitigation before any demo |

## P1 — Foundations (language-independent; survives the CI4 port)
| # | Task | Size | Clause |
|---|---|---|---|
| P1.1 | `MetaData` naming convention + Alembic + reviewed baseline + `stamp head` | M | 10.2.3.4/3.6 |
| P1.2 | Portability sweep of `models.py` — the 12 SQLite-isms in [[On-Prem Architecture]] | M | 10.2.7.1.3 |
| P1.3 | MariaDB 11.4 container + env-driven DB URL + pool + 3 least-priv grants | S | 10.2.7.1.3 / 5.1 |
| P1.4 | SQLite→MariaDB data migration w/ type coercion + orphan check + reconciliation report | M | 10.2.4.6 |
| P1.5 | Delete `_migrate_lightweight()` + `create_all()`; CI asserts `upgrade head` == metadata | S | 10.2.3.2 / [[Security Audit#M9]] |
| P1.6 | `ObjectStore` abstraction + MinIO + `*_object_key` columns + move `uploads/` | M | 10.2.2.14 / 10.2.1.15.5 |
| P1.7 | Image-normalisation worker pipeline (Pillow: EXIF strip, resize, thumbnail) | S | 10.2.2.14 |
| P1.8 | Env-driven config — kill hardcoded `localhost`, CORS allowlist, runtime `config.js` via proxy | S | 10.2.2.3 / [[Security Audit#M3]] |
| P1.9 | Reverse proxy (Caddy/nginx) + UTHM-CA TLS + CSP + HSTS | S | 10.2.5.1 |
| P1.10 | **LDAP/AD** provider — service bind → search → user bind, JIT provision, `ldap_role_map` | M | **10.2.5.3** |
| P1.11 | Containerise full stack + offline image bundle/registry + Docker secrets | M | 10.2.2.2/2.4/2.9/2.13 |
| P1.12 | Backend `pytest` suite scaffold (auth, RBAC, cross-facility immutability first) | M | 10.1.5 |
| P1.13 | Flutter release signing (real keystore + `key.properties`) | S | — |

## P2 — Security & compliance
| # | Task | Size | Clause |
|---|---|---|---|
| P2.1 | Fix [[Security Audit]] H1 — gate emergency endpoints behind `require_page_access` + facility scoping | M | 10.2.5.1/2 |
| P2.2 | Fix H2 — default-deny cross-facility, reason-logged break-glass, scope + paginate `list_patients` | M | 10.2.5.1/5.6 |
| P2.3 | Fix H3 — random seed passwords + `must_change_password`; real staff password policy | S | 10.2.5.1/5.3 |
| P2.4 | Fix M1/M2 — per-IP login + OTP throttle; indexed normalized-NRIC column | S | 10.2.5.6 |
| P2.5 | Fix M4 — short access-token TTL + refresh in `HttpOnly` cookie + `jti` deny-list; strict CSP | M | 10.2.5.1 |
| P2.6 | Fix M5/M6/M7/M8 — upload magic-byte + AV hook; verified responder credential; HMAC card key + PIN; stop logging clinical values into `audit_logs.detail` | M | 10.2.2.9 / 10.2.5.1/5.7 |
| P2.7 | Encryption at rest — MariaDB encrypted tablespaces + on-prem key management | M | 10.2.5.1 |
| P2.8 | **Backup / DR regime** — daily incr + weekly full + binlog shipping, encrypted, 30-day, pre-update image, quarterly restore test, documented RPO/RTO | L | **10.2.7.2** |
| P2.9 | Audit **hash-chain** + daily WORM seal + retention/partition policy | M | 10.2.5.1/5.7/3.11 |
| P2.10 | PDPA — consent model + data-subject-request flow + DPO register + retention config | M | 10.2.5.1 |
| P2.11 | Offline CI: Gitea + ruff/pytest/bandit/semgrep/pip-audit/trivy + alembic up/down check | M | 10.2.3.1/3.9/5.8 |
| P2.12 | `data_quality_alerts` — batch validators (missing values, dup patients, bad coding) | S | 10.2.3.11 |

## P3 — Tender modules
| # | Task | Size | Clause |
|---|---|---|---|
| P3.1 | **Ancillary engine** — `service_requests` + order → encounter → result → sign-off → document; then Procedure, Laboratory, X-ray, Physiotherapy faces | L | 10.2.1.7–10 |
| P3.2 | **Dental module** + tooth-chart UI (FDI notation) | M | 10.2.1.11 |
| P3.3 | **Billing module** — charge master, `bills`, `bill_items`, `payments`, `claims`; wire consultation / pharmacy / ancillary fees | L | 10.2.1.6 + per-module billing |
| P3.4 | Consultation: structured **SOAP** notes, treatment plan, follow-up scheduling, referral UI | M | 10.2.1.3.3–4 |
| P3.5 | Document generation — Digital Medical Certificate, Referral Letter, Timeslip (PDF) | M | 10.2.1.3.6 |
| P3.6 | **Reporting engine** + **Custom Report Builder** (field picker across modules, filter/group, template store) | L | 10.2.1.12.1/5 |
| P3.7 | **MOH / statutory reporting** — notifiable disease (e-Notifikasi format), HMIS returns, anonymization | M | 10.2.1.12.3 |
| P3.8 | **Management Dashboard** — KPI view + patient-flow prediction (EWMA/GBM) + operational health score | M | 10.2.1.1 |
| P3.9 | Calling-system hardware — ticket printer (ESC/POS), TV display **audio** + branding | S | 10.2.1.14.2 / 10.2.8.2–3 |
| P3.10 | Mobile: slot booking by dept/doctor, vitals view, PDF visit summary, server push, announcements | M | 10.2.1.13.3–5 |

## P4 — Interoperability, AI & imaging
| # | Task | Size | Clause |
|---|---|---|---|
| P4.1 | **FHIR-readiness migrations** — coding triples, `resource_identifiers`, resource tables, terminology seeds, backfill queue | L | **10.2.3.10** → [[FHIR Schema Readiness]] |
| P4.2 | Thin **read-only FHIR façade** + CapabilityStatement | L | 10.2.3.10 |
| P4.3 | **On-prem AI engine** — replace ALL Claude-API calls; local LLM (Ollama/vLLM) + `faster-whisper`; CDS hint, medication-safety alert, voice→SOAP, NL reports | L | **10.2.2.15–17** → [[On-Prem Clinical AI]] |
| P4.4 | Medication-safety = rule engine + licensed drug DB (MIMS) integration | M | 10.2.1.3.9 |
| P4.5 | AI audit-trail intelligence + access anomaly detection over the hash-chain | M | 10.2.5.6–7 |
| P4.6 | Predictive analytics + population-health stratification in Reporting | M | 10.2.1.12.7/12.9 |
| P4.7 | **PACS** — Orthanc + PG index + S3 plugin + Modality Worklist + OHIF viewer + auto-link | L | **10.2.1.15** → [[PACS and DICOM]] |
| P4.8 | Integration layer — SMP / SMS / e-klinik / Registrar (read-only) + lab-analyser HL7 v2 service + label printers | L | 10.2.2.8 / 10.2.4 / 10.2.8.1 → [[Integration Engine and LDAP]] |

## P5 — Ops & handover
| # | Task | Size | Clause |
|---|---|---|---|
| P5.1 | Observability — structured logging, Loki, Prometheus, Grafana, Alertmanager (email + WhatsApp) | M | 10.2.5.5 |
| P5.2 | Load testing to 23k users; tune pools + workers | M | 10.2.2.13 |
| P5.3 | Two-campus rollout — WAN validation + Pagoh edge + offline emergency-export appliance | M | — |
| P5.4 | Docs & handover — auto-generated ERD / data dictionary, Operations / Programming / Maintenance manuals, DR runbook, Transfer-of-Technology package | M | 7.1 / 3.2.5 / 10.2.3.6 |

---

## Risk register
| Risk | Severity | Mitigation |
|---|---|---|
| **PHP port underestimated** — 2–4 PM assumes disciplined layering from day one | High | Apply the [[Designing for the PHP Port]] checklist continuously, not retroactively |
| **On-prem AI on venue hardware** — no capable GPU on the demo laptop | High | Confirm hardware early; keep a small quantised model that runs on CPU as a floor |
| **SaMD regulation** — CDS + result-interpretation are regulated medical devices for a real deployment | Medium | Out of scope for the competition; named workstream for the tender; frame all AI as clinician reference aids |
| **Personnel (clause 10.3)** — need MBOT technologist + MMC clinical advisor + HIMSS/HL7 credential | Medium | **Open question — does the team have these lined up?** Bid blocker, not a demo blocker |
| **No MHNexus public API** — clause 10.2.3.10 can only be met as schema-readiness | Medium | [[FHIR Schema Readiness]]; direct enquiry to MHNexus / MOH Digital Health Division about partner onboarding |
| **PDPA 2024 exact dates** still settling | Low | Re-check before any formal compliance submission — [[Malaysia Health Regulation]] |

## Demo priorities (for the competition, not the full build)
Ranked by impact per unit of effort:
1. **Offline AI, cable unplugged** — 8B model doing a live CDS hint + medication-safety alert, network visibly disconnected. The clause-10.2.2.15 differentiator.
2. **Voice → SOAP** — dictate, watch it land in the right fields.
3. **DICOM viewer** — open a chest X-ray inside a record, zoom & measure.
4. **Patient-flow prediction + operational health score** on the dashboard.
5. **The emergency scan** — already built; lead the deck with it (most human moment).

Deprioritise for the demo: billing, custom report builder, ancillary modules beyond
one worked example, anything needing UTHM's internal systems (mock with a labelled adapter).
