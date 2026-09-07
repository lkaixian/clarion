---
title: PACS and DICOM
type: research
updated: 2026-08-30
tags: [research, pacs, dicom, orthanc, imaging]
---

# PACS and DICOM

Tender clause ****: integrated PACS — DICOM ingest from modalities, secure
zoom/rotate/measure viewer, secure sharing, archiving + DR.

## Components (all mature open source)
| Part | Pick | Licence | Note |
|---|---|---|---|
| DICOM server | **Orthanc 1.12** | GPLv3 core / AGPLv3 plugins | C++, very light, edge-ready. DICOMweb (WADO-RS/QIDO-RS/STOW-RS) via plugin. PostgreSQL index plugin. **S3 plugin** → pixel data into the same MinIO store. |
| — alternative | dcm4chee-arc-light | MPL 2.0 | Java/WildFly, heavy, needs own RDBMS + Keycloak. **Wrong-sized for a university clinic.** |
| Web viewer (standalone) | **OHIF Viewer** | MIT | Deployable app; zoom/pan/rotate/window-level/measure client-side in WebGL |
| Web viewer (embedded panel) | **Cornerstone3D** | MIT | JS rendering library, embed directly in the consultation screen |

Both viewers stream frames on demand over WADO-RS — no multi-gigabyte downloads.
They need a DICOMweb-capable PACS + CORS.

## EMR ↔ PACS wiring (IHE Scheduled Workflow)
1. The **X-ray module** places an order carrying an **Accession Number**.
2. The order appears in a **DICOM Modality Worklist**; the modality picks it up.
3. The modality embeds the Accession Number in the study and sends to Orthanc (C-STORE).
4. Orthanc's `OnStoredInstance` hook calls the app → match Accession Number to the
   `service_requests` row → auto-link study to patient/encounter.
5. The viewer launches against `/studies/{StudyInstanceUID}` via WADO-RS.

Modalities sit on an **isolated device VLAN**; Orthanc is never directly exposed —
access is proxied and audit-logged. External sharing = time-boxed WADO-RS token URL or
a de-identified ZIP/PDF.

## Storage for a small clinic
~5–20 GB/month. SSD cache for recent studies + a large HDD tier for older, lifecycle
transitions between them. Bucket `clarion-dicom` gets an object-lock/WORM retention
(7 years). **No HSM / tape / erasure-coding** — that is nationwide scale, not this.

Detail: `scratchpad/agy-research-full.md` Part 2 Topic E. Architecture placement in
[[On-Prem Architecture]]. See [[Sources]].
