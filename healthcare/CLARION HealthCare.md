---
title: CLARION HealthCare
type: moc
updated: 2026-08-30
tags: [clarion, campus, moc]
---

# CLARION HealthCare — project knowledge base

CLARION is an emergency-first, interoperable clinic system (FastAPI + React + Flutter,
SQLite today). It is being built as a **competition demo** but is deliberately aligned
with a live Malaysian government tender. The team's plan: win on the current stack,
then **port to PHP CodeIgniter 4** for the tender.

This vault is the persistent reference for that effort. Start here.

## The tender
- — what it is, buyer, scale, the hard constraints
- — full verbatim clause list (the compliance backbone)

## Where we stand
- [[Compliance Matrix]] — every clause → Have / Partial / Gap / Port / N-A
- [[Module Coverage]] — the 15 mandated modules vs what CLARION has
- [[Security Audit]] — 1 critical, 4 high, 9 medium findings against OWASP + PDPA

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

> [!danger] CLARION sends PHI to a US cloud
> With `ANTHROPIC_API_KEY` set, `ai/summarize.py` posts the full patient record to
> Anthropic and `ai/nric_ocr.py` posts the MyKad image to Claude vision — the latter
> from an **unauthenticated** endpoint. Breaks the tender–17 outright
> and is a PDPA cross-border transfer. See [[Security Audit#C1]] and [[On-Prem Clinical AI]].
