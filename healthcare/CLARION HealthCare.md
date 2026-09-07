---
title: CLARION HealthCare
type: moc
updated: 2026-09-07
tags: [clarion, campus, moc]
---

# CLARION HealthCare — project knowledge base

CLARION is an emergency-first, interoperable clinic system (FastAPI + React + Flutter;
SQLite for the demo, MariaDB-ready). It is being built as a **competition demo** but is
deliberately aligned with a live Malaysian government tender. The team's plan: win on
the current stack, then **port to PHP CodeIgniter 4** for the tender.

This vault is the persistent reference for that effort. Start here.

> [!info] Status (2026-09-07): P1 foundations (Alembic, MariaDB path, ObjectStore,
> imaging, edge proxy, LDAP, containers) and the P2 security wave (every Security Audit
> High/Medium finding) are **done**. Next: the P2.7–P2.12 infra items (encryption at
> rest, backup/DR, audit hash-chain, PDPA, CI) then the P3/P4/P5 tender modules.

## The tender
- — what it is, buyer, scale, the hard constraints
- — full verbatim clause list (the compliance backbone)

## Where we stand
- [[Compliance Matrix]] — every clause → Have / Partial / Gap / Port / N-A *(scored
  2026-08-30, pre-P1/P2 — see [[Implementation Roadmap]] for current status)*
- [[Module Coverage]] — the 15 mandated modules vs what CLARION has
- [[Security Audit]] — OWASP + PDPA findings; **all Critical/High/Medium resolved or
  interim-mitigated** as of 2026-09-07

## How to build it
- [[Implementation Roadmap]] — phased plan P0–P5, effort-sized, dependency-ordered
- [[Designing for the PHP Port]] — what to do now so the CI4 rewrite is cheap
- [[On-Prem Architecture]] — MariaDB, MinIO, Orthanc, backup/DR, deployment topology
- [[FHIR Schema Readiness]] — how to satisfy the tender without a rewrite

## Research (grounded, cited)
- [[Malaysia Health Regulation]] — PDPA 2024, MOH reporting, MDA / SaMD
- [[National Interoperability]] — MHNexus, MY Core FHIR, no public API
- [[On-Prem Clinical AI]] — local LLM stack, "ALi.ai", the AI clauses
- [[PACS and DICOM]] — Orthanc + OHIF, EMR↔PACS wiring
- [[Integration Engine and LDAP]] — Mirth/OIE, HL7 v2, Active Directory
- [[Nationwide HIE Precedents]] — Estonia, Denmark, Singapore, India, Australia

## The bigger vision (out of build scope)
- [[Nationwide Health Information Exchange]] — the national HIE design from the Gemini thread

## Deliverables
- — the operational briefing (synthesis)
- [[Report 2 - Nationwide HIE]] — the strategic briefing (synthesis)
- [[Sources]] — every external reference, checked

---

## The one thing to fix first

> [!danger] CLARION can send PHI to a US cloud
> `ai/summarize.py` posts the full patient record to Anthropic and `ai/nric_ocr.py`
> posts the MyKad image to Claude vision. **Interim guard (P0.4):** both paths are now
> disabled unless `ANTHROPIC_API_KEY` **and** `CLARION_ALLOW_CLOUD_AI=1` are set — the
> app runs offline by default. The **real fix is P4.3** (on-prem AI engine, replace
> every Claude-API call). Still the #1 tender blocker. See [[Security Audit#C1]] and
> [[On-Prem Clinical AI]].
