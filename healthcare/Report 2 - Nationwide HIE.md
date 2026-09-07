---
title: Report 2 - Nationwide HIE
type: report
updated: 2026-08-30
tags: [report, synthesis, hie, national, vision]
---

# Report 2 — Nationwide Malaysian Health Information Exchange

Framing note. The full design is in [[Nationwide Health Information Exchange]];
precedents in [[Nationwide HIE Precedents]].

## What this is
The bigger vision from the Gemini research thread — a national-scale health data
exchange. **Explicitly out of scope for the University competition build.** Captured as the
programme CLARION could grow into, and because the architecture choices at the University scale
should not foreclose it.

## The thesis
A nationwide exchange is a **federated hub-and-spoke**, not a central monolith. The hub
holds **pointers + the emergency core**; heavy data (imaging) stays at the originating
region and streams on demand. If a rural clinic loses its WAN link, it keeps running on
a local cache and reconciles later.

Key pieces: **Master Patient Index** (MyKad ↔ MRN), **Record Locator Service**
("index centrally, stream locally"), **Kafka** event bus, **Redis** hot index,
**Keycloak** OAuth2/OIDC + mTLS, **FHIR IPS** (ISO 27269) as the emergency/transfer
payload, **break-glass** with an **IHE ATNA** immutable audit, **DICOMweb/WADO-RS**
frame streaming, **clinical-aware storage tiering** (hot NVMe → warm MinIO → cold LTO,
driven by discharge / appointment / report events), **erasure coding** for durability,
**five-nines only for the emergency/identity tier**.

## Real precedents
Estonia (X-Road, decentralised, KSI blockchain integrity) · Denmark (sundhed.dk
federates 120+ sources) · Austria ELGA (holds document references) · Australia My
Health Record (CDA → FHIR) · India ABDM (federated, consent-based, FHIR R4) · Singapore
NEHR (centralised summary + break-the-glass). Malaysia's own: **MyHDW** (analytics
warehouse) and the operational **MHNexus** HIE. See [[Nationwide HIE Precedents]].

## What this means for the University build
Nothing needs building now — but a few campus-scale choices keep the door open:
- FHIR-shaped schema + `resource_identifiers` ([[FHIR Schema Readiness]]) — the same
  work that satisfies the tender.
- Orthanc + DICOMweb ([[PACS and DICOM]]) — already the right imaging choice.
- An append-only, hash-chained audit ([[On-Prem Architecture]]) — the substrate a
  break-glass model needs.
- The existing emergency QR/NFC scan is a working IPS-style emergency-core access
  pattern in miniature.
