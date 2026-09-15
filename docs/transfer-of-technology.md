# CLARION — Transfer of Technology Package

Tender clause **3.2.5**: "Conduct a Transfer of Technology session on the
source code and integration (hardware + software APIs)." This document is
the package that session runs from — agenda, materials, and the checklist
The University's PTM/IT team signs off against at handover.

## 1. Session agenda (proposed, ~1 day)

| Time | Topic | Materials |
|---|---|---|
| 0:00–0:30 | System overview, tender-clause coverage | `healthcare/Compliance Matrix.md` |
| 0:30–1:30 | Architecture walkthrough — backend/web/mobile, data flow, on-prem topology | `healthcare/On-Prem Architecture.md`, [Programming Manual](programming-manual.md) §1–2 |
| 1:30–2:30 | Database schema & relationships | [Data Dictionary & ERD](data-dictionary.md) (auto-generated, the tender) |
| 2:30–3:30 | Source code walkthrough — router-by-router tour | [Programming Manual](programming-manual.md) §3, live code |
| 3:30–4:30 | Software API integration points | §3 of this document (below) |
| 4:30–5:00 | Hardware integration points | §4 of this document (below) |
| 5:00–6:00 | Day-2 operations live demo — start/stop, monitoring, backup/restore drill | [Operations Manual](operations-manual.md), [Backup & DR runbook](../backend/backup/README.md) |
| 6:00–6:30 | Maintenance schedule & security posture | [Maintenance Manual](maintenance-manual.md), `healthcare/Security Audit.md` |
| 6:30–7:00 | Q&A, sign-off checklist (§5) | — |

## 2. What's being transferred

- Full source: `backend/`, `web/`, `mobile_flutter/`, `proxy/`, deployment
  config (`docker-compose.yml`, `.env.docker.example`), CI (`ci/`,
  `.woodpecker.yml`).
- Full documentation set: this file, [Operations](operations-manual.md) /
  [Programming](programming-manual.md) / [Maintenance](maintenance-manual.md)
  manuals, `docs/deployment.md`, [Data Dictionary](data-dictionary.md),
  the `healthcare/` Obsidian vault (research, compliance matrix, security
  audit, architecture decisions — the *why* behind every design choice).
- Test suites: `backend/tests/` (pytest), `backend/loadtest/` (Locust),
  web/mobile test suites.
- No proprietary third-party licenses to transfer — every dependency is
  open-source (see `backend/requirements.txt`, `web/package.json`,
  `mobile_flutter/pubspec.yaml`); AI inference is local (Ollama, no vendor
  API key/contract, the tender).

## 3. Software API integration points

| Integration | Where | Notes |
|---|---|---|
| FHIR façade (future MySejahtera/PADU interop, the tender) | `backend/app/routers/fhir.py`, read-only, 8 resource types | No write path built — a real interop deployment needs auth/consent design first, deliberately out of scope for the demo |
| Lab analyser (HL7 v2 / MLLP) | `backend/app/hl7v2.py`, `hl7_client.py` (outbound ORM^O01), `hl7_listener.py` (inbound ORU^R01, its own process, port 2575) | Hand-rolled encoder/decoder, no analyser-specific config beyond MLLP host/port; results always land in a review queue, never auto-sign |
| LDAP/Active Directory | `backend/app/ldap_auth.py`, env-driven (`docs/deployment.md` § LDAP) | Bind + group→role mapping; falls back to local accounts if unset |
| PACS/DICOM (Orthanc) | `backend/app/pacs.py`, `routers/pacs.py` | REST client + facility-scoping in front of Orthanc; manual upload today, real Modality Worklist needs analyser/modality hardware (§4) |
| Object storage (S3-compatible) | `backend/app/storage.py`, `ObjectStore` ABC | `LocalObjectStore` (dev) / `MinioObjectStore` (prod) — swappable backend, any S3-compatible target works |
| SMTP (alerting) | `.env.docker` SMTP vars, Alertmanager config (`observability/`) | Only channel wired; WhatsApp/Meta/Twilio deliberately not built (no real account for this demo) |
| SMP / SMS / e-klinik / university Registrar DB | **Not built** | Needs real campus specs/credentials this environment doesn't have — see `healthcare/Implementation Roadmap.md`'s P4.8 entry. This is the one integration item the receiving team must scope with the University's own IT before it can be built |

## 4. Hardware integration points

| Hardware | Status | Notes |
|---|---|---|
| Lab analysers | Software-ready (HL7 v2/MLLP), untested against real equipment | Verified with hand-crafted HL7 messages + a real socket round-trip only — needs a live analyser test during commissioning |
| Label/receipt printers | Built (P3.9) | ESC/POS over the calling-system ticket/label flow |
| Waiting-room display (calling-system TV) | Built (P3.9) | `routers/display.py`, no auth, read-only |
| DICOM modalities (X-ray etc.) | **Manual upload only** | Real Modality Worklist integration needs physical modality hardware not present in this environment — see `healthcare/PACS and DICOM.md` |
| Server hardware / GPU for local AI | Sized per `healthcare/On-Prem Clinical AI.md`'s risk note — no confirmed GPU on target hardware yet | A CPU-only quantised model is the floor if no GPU is available |

## 5. Handover sign-off checklist

- [ ] Source code repository access transferred (or full export handed over)
- [ ] All 4 manuals (this file + Operations/Programming/Maintenance)
      reviewed with receiving team, 3 sets each per clause 7.1 (1 original +
      2 duplicates — print/bind from these Markdown sources)
- [ ] Data dictionary/ERD reviewed against the live schema
- [ ] Backup/DR runbook walked through live (a real restore drill run
      together, not just discussed)
- [ ] Contacts table in `backend/backup/README.md` filled in with real names
- [ ] Secrets (SECRET_KEY, OTP_HMAC_KEY, DB/MinIO/LDAP credentials, TLS
      certs) rotated to values only the receiving team holds — nothing from
      the demo/dev environment carries over
- [ ] Open backlog items acknowledged (see `healthcare/Implementation
      Roadmap.md` "Next up" section — RustFS migration, SMP/SMS/e-klinik
      integration, real Modality Worklist, P5.3 two-campus rollout)
- [ ] Warranty terms confirmed (clause 4.2 — 2 years from this handover)
- [ ] Receiving team's own MBOT technologist / MMC clinical advisor /
      HIMSS-HL7 credential holder identified (clause 10.3 — flagged as an
      open question in `healthcare/Implementation Roadmap.md`'s risk
      register, not something this session can resolve)
