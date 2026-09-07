---
title: Module Coverage
type: assessment
updated: 2026-08-30
tags: [compliance, modules, clarion]
---

# Module Coverage — the 15 mandated modules

the tender enumerates 15 modules. Coverage judged on functional behaviour in the
codebase today. Full clause-level detail in [[Compliance Matrix]].

| Module | Clause | Coverage | Missing |
|---|---|---|---|
| **Calling System** | | ~80% | ticket printer, audio call-out |
| **Pharmacy & Inventory** | | ~75% | label printing, per-patient billing |
| **Admin** | | ~70% | real backup, content CMS, change notifications |
| **Frontdesk** | | ~65% | billing, SMP/SMS/e-klinik, Registrar eligibility |
| **Consultation** | | ~55% | references, structured SOAP, CDS, med-safety wiring, voice |
| **Mobile Apps** | | ~55% | slot booking, vitals view, server push, announcements |
| **Dashboard** | | ~30% | management KPI view, flow prediction, health score |
| **Reporting** | | ~20% | MOH reporting, report builder, analytics, predictive, NL insight, stratification |
| **Billing** | | ~5% | entire module — invoices, charges, payments, claims |
| **Procedure** | | ~5% | entire module |
| **Laboratory** | | ~5% | entire module + analyser integration + result-interpretation AI |
| **X-ray** | | ~5% | entire module + PACS coupling |
| **Physiotherapy** | | ~5% | entire module |
| **Dental** | | ~5% | entire module + dental-chart UI |
| **PACS / DICOM** | | ~5% | entire subsystem — [[PACS and DICOM]] |

## The ancillary pattern
Laboratory, X-ray, Physiotherapy, Dental and Procedure are **structurally identical**:
receive a patient (by order or walk-in) → record a clinical indication → sign off →
produce a report. **Build one engine — order, encounter, result, sign-off, document —
and give it five faces.** Dental adds a tooth-chart UI; Lab and X-ray add the analyser
and PACS couplings.

## Big-ticket gaps, ranked by leverage
1. **On-prem AI engine** ([[On-Prem Clinical AI]]) — one bet unlocks ~8 clauses (CDS,
   med-safety, voice-SOAP, NL reports, anomaly detection, audit intelligence).
2. **PACS/DICOM** ([[PACS and DICOM]]) — Orthanc + web viewer; highest visual payoff.
3. **The ancillary engine** — Lab / X-ray / Physio / Dental / Procedure, one build.
4. **Billing module** — invoice, charge master, payment, claims.
5. **Reporting engine** + Custom Report Builder + MOH reporting.
6. **Predictive analytics / management dashboard** — flow prediction, ops health score.
7. **FHIR-compatible schema** ([[FHIR Schema Readiness]]) — cheap now, expensive later.
8. **LDAP**, **integration layer** (SMP/SMS/e-klinik, lab analysers).
9. **Backup/DR**, **MariaDB migration**.

## What CLARION already does well (reuse, don't rebuild)
Reception + queueing + per-section scoping · signed record sign-off + signature pad +
append-only annotations · pharmacy purchase-approval workflow · role → page permission
matrix · public waiting-room TV display · emergency QR/NFC scan with immutable audit ·
appointments with reschedule requests · cross-facility record immutability model.
