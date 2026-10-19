---
title: UTHM HealthCare Tender
type: reference
updated: 2026-08-30
tags: [tender, uthm, requirements]
---

# UTHM HealthCare Tender

**Reference:** `UTHM/13(PKU)/P/05/001/2026`
**Title:** Supply, Delivery, Installation, Testing, Commissioning Software for the
Development of Patient Information Management System (UTHM HealthCare) for Pusat
Kesihatan Universiti, Universiti Tun Hussein Onn Malaysia, Parit Raja and Kampus
Cawangan Pagoh.
**Document:** Jadual Ketiga — Jadual Teknikal Tender (Perkhidmatan). Source file:
`docs/source/062026JadualTeknikalHealthcare.xlsm` (sheet `ben-up-003H`).

## Buyer & scale
- **Buyer:** Pusat Kesihatan Universiti (PKU), UTHM — a university health centre.
- **Two branches:** PKU Parit Raja and PKU Kampus Pagoh.
- **Scale:** ~20,000 students + 3,000 staff (~23k users).
- Hosting, virtual server, firewall, VPN, antivirus and DB hosting are **provided by
  the University** (PTM). Source code is **owned by UTHM**.

## How to respond
- Every clause needs a substantive written response in the *SPESIFIKASI YANG
  DITAWARKAN* column — **not** "Comply" / "Noted" / "Agreed" (clause 1.1).
- The tenderer may not write their name or price in the spec document.
- Spec is the **minimum requirement**; "additional or more comprehensive
  specification by the vendor is most welcomed" (clause 1.8).

## The hard platform constraints
| Clause | Constraint | Our position |
|---|---|---|
| 10.2.2.1 | **MUST use PHP CodeIgniter 4** | Demo in FastAPI; **port later**. See [[Designing for the PHP Port]] |
| 10.2.2.2 / 10.1.7 | Linux OS | Fine (uvicorn/Linux) |
| 10.2.7.1.3 | Enterprise RDBMS — Oracle / MSSQL / **MariaDB / MySQL** | SQLite → MariaDB 11.4. See [[On-Prem Architecture]] |
| 10.2.5.3 | **LDAP** authentication | New auth provider. See [[Integration Engine and LDAP]] |
| 10.2.2.15–17 | **Embedded AI, NO cloud APIs**, offline, federated updating, "ALi.ai or equivalent" | Local model stack. See [[On-Prem Clinical AI]] |
| 10.2.3.10 | Schema **FHIR-compatible**, MySejahtera/PADU-ready, no restructuring | Code columns + façade now. See [[FHIR Schema Readiness]] |
| 10.2.1.15 | Integrated **PACS with DICOM** | Orthanc + OHIF. See [[PACS and DICOM]] |
| 10.2.3.1 / 10.2.5.x | **OWASP** + **PDPA** (encryption, RBAC, audit, retention) | See [[Security Audit]], [[Malaysia Health Regulation]] |
| 10.2.7.2 | Automated encrypted backups, 30-day retention, quarterly restore tests, RPO/RTO | See [[On-Prem Architecture#Backup and DR]] |

## The 15 mandated modules (clause 10.2.1)
Dashboard · Frontdesk · Consultation · Pharmacy & Inventory · Admin · Billing ·
Procedure · Laboratory · X-ray · Physiotherapy · Dental · Reporting · Mobile Apps ·
Calling System · PACS. Detail and coverage in [[Module Coverage]].

## Integrations required
- UTHM internal: **SMP, SMS, e-klinik panel**; Registrar's system for patient eligibility.
- Hardware: label printer, blood-test machine, X-ray image viewer — REST/JSON.
- Lab analysers (Pagoh): bidirectional API, patient demographics + orders out, results in.

## Roles (clause 10.2)
Super Admin · Management Admin · Health/Dental Officer · Medical Assistant · Nurses ·
Support (Lab/X-ray/Physio) · Clinic Panel · PPO · Registrar Officer.

## Contractual (not software — bid deliverables)
- 2-year warranty (24h response after FAT), 2-year support, ≥2 onsite staff.
- Training ≥20 people, ≥5 days; Transfer-of-Technology session on source code + APIs.
- 3 sets of manuals (Operations, Programming, Maintenance) in BM or English.
- URS sessions, SRS report, Work Implementation Schedule, UAT, Security Acceptance Testing.
- **Personnel (10.3):** MBOT-registered Technologist (TS/TSr), MMC-registered Clinical
  Advisor, HIMSS/HL7 health-informatics competency. → [[Implementation Roadmap#Risk register]]

## Full clause list
→ [[Tender Clauses Section 10]]
