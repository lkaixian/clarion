---
title: Report 1 - UTHM HealthCare
type: report
updated: 2026-08-30
tags: [report, synthesis, uthm, clarion]
---

# Report 1 — Productionizing CLARION for UTHM HealthCare

Executive synthesis. Detail is in the linked notes.

## The situation
CLARION is a working outpatient system — [[Module Coverage|reception, queueing,
consultation with signed sign-off, pharmacy with purchase approval, appointments, a
public waiting-room display, role-based access, emergency QR/NFC scan]]. It runs on
FastAPI + React + Flutter over SQLite.

[[UTHM HealthCare Tender]] asks for a two-campus system with 15 modules, an embedded
non-cloud AI engine, an integrated PACS, FHIR-ready data, LDAP, MariaDB and a full
backup/DR regime — on **PHP CodeIgniter 4**. The plan: win the competition on the
current stack, then port.

## Where CLARION stands
Against Section 10: **~18 clauses met, ~21 partial, ~44 gaps** ([[Compliance Matrix]]).
None of the four platform pillars (on-prem AI, PACS, FHIR, MariaDB) exist yet. But
almost nothing is throwaway — the reusable core ports cleanly and the architecture work
is language-independent ([[On-Prem Architecture]]).

## The bottom line
**Build the demo now; make three bets early.**
1. **Move every AI feature off the Anthropic cloud** before anyone shows it. The spec
   forbids third-party AI clouds (10.2.2.15–17) and the current code leaks PHI —
   [[Security Audit#C1]]. Local model stack in [[On-Prem Clinical AI]].
2. **Add FHIR code columns + Alembic migrations this month.** Cheap now, a rewrite
   later — [[FHIR Schema Readiness]].
3. **Stand up Orthanc + a web DICOM viewer** as a self-contained module — the single
   most visual "we built a real hospital system" moment — [[PACS and DICOM]].

## The one urgent conflict
> [!danger]
> With `ANTHROPIC_API_KEY` set, CLARION posts the full patient record and the
> photographed MyKad to US clouds — the MyKad path from an **unauthenticated**
> endpoint. Breaks 10.2.2.15–17 outright and is a PDPA cross-border transfer. One env
> var from live, no guard. Fix first (P0.4 → P4.3 in [[Implementation Roadmap]]).

## Key research conclusions
- **PHP port** ≈ 2–4 person-months *if* the demo is disciplined about layering from day
  one — [[Designing for the PHP Port]].
- **No public MySejahtera/PADU API.** Malaysia's national FHIR HIE (**MHNexus + MY
  Core**) is real and funded but partner-gated. Clause 10.2.3.10 is satisfiable only as
  schema readiness — [[National Interoperability]].
- **"ALi.ai" is MAIA Sdn Bhd**, a workflow-AI company, not an LLM. Run open-weight
  models locally; a MAIA partnership is optional — [[On-Prem Clinical AI]].
- **"Federated model updating" for one site** = periodic local LoRA fine-tuning. Say so.
- **PDPA 2024**: mandatory DPO, breach notification, biometric data now sensitive,
  RM 1m penalties — [[Malaysia Health Regulation]].
- **CDS / result-interpretation AI = regulated SaMD** for a real deployment (Medical
  Device Act 2012). Frame all AI as clinician reference aids.
- **Security:** 1 critical + 4 high + 9 medium findings; the isolation gaps are confined
  to the `patients` and `emergency` routers; the OTP flow and file handling are clean —
  [[Security Audit]].

## What to put on stage
1. Offline AI with the network cable visibly unplugged.
2. Voice → SOAP.
3. The DICOM viewer inside a patient record.
4. Patient-flow prediction + operational health score on the dashboard.
5. The emergency scan (already built — lead with it).

Full plan: [[Implementation Roadmap]].
