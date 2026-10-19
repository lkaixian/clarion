---
title: Nationwide Health Information Exchange
type: research
updated: 2026-08-30
tags: [research, hie, national, fhir, dicom, architecture, vision]
---

# Nationwide Health Information Exchange

The bigger-vision design — a national-scale Malaysian health data exchange that CLARION
could grow into. **Out of scope for the University competition build**; captured here as
direction. Source: the Gemini thread (`docs/source/gemin-text.txt`); precedents
validated in [[Nationwide HIE Precedents]].

## The core argument
**Base64 is not an interoperability solution.** It is a transport encoding — a
Base64-wrapped DICOM image, HL7 message and proprietary ECG waveform are still three
unparseable blobs. Real interoperability uses semantic standards:

| Data type | Standard |
|---|---|
| Clinical records / EHR | **HL7 FHIR** (JSON / REST) |
| Medical imaging | **DICOM / DICOMweb** (PACS, WADO-RS) |
| Bedside devices | **IEEE 11073** |
| Legacy lab feeds | **HL7 v2.x / ASTM** |

## The middleware pattern
Diverse device/lab protocols are normalised by an **integration engine** (Mirth /
OpenIntegrationEngine — see [[Integration Engine and LDAP]]), never by one server doing
translation + storage + streaming. Three decoupled layers:
1. **Edge device gateways** — connect to RS-232 / USB / LAN modality interfaces; convert
   proprietary packets to standard payloads.
2. **Integration engine** — CPU/memory-bound string parsing; translates HL7 v2 / ASTM →
   FHIR; routes metadata to the EHR; stores only short-term transactional queues.
3. **PACS / VNA + object storage** — disk-I/O / bandwidth-bound; stores DICOM, PDFs,
   pathology slides; exposes DICOMweb (WADO-RS) for browser streaming.

## Imaging: stream, don't download
**DICOMweb / WADO-RS** frame-level retrieval — the browser requests specific frames on
demand (`GET /studies/{s}/series/{s}/instances/{i}/frames/{n}`), decodes HTJ2K in
WebAssembly, renders window/level in WebGL. Two models:
- **Client-side progressive streaming** (the "Google Maps" model) — for 2D CT/MRI
  navigation and gigapixel pathology; only the visible tiles/frames travel.
- **Server-side rendering** (the "cloud gaming" model) — a GPU node renders 3D volumes
  and streams H.265/AV1 over WebRTC to a `<canvas>`; for heavy 3D on low-powered clients.
Open stack: **Orthanc** / dcm4chee back end + **Cornerstone3D** / **OHIF** front end.

## Storage tiering (on-prem, clinical-aware HSM)
| Tier | Data | Media | Latency | Retention |
|---|---|---|---|---|
| Hot | active cases, current inpatient scans, ICU telemetry | NVMe / SSD, Redis | < 50 ms | 0–30 days |
| Warm | recent outpatient, prior studies, audit logs | local SAN/NAS RAID 6, MinIO/Ceph | 100 ms – 1 s | 1 mo – 2 yr |
| Cold | inactive histories, statutory archives | S3 Glacier / **LTO tape / WORM** | minutes – hours | 2 – 21+ yr |

**Event-driven + predictive tiering:** discharge (`Encounter.status=finished` / ADT^A03)
→ demote hot→warm; upcoming appointment (`Appointment.status=booked` / SIU^S12) →
prefetch cold→hot overnight; report finalised (ORU^R01) → apply WORM lock; ICU admit
(ADT^A01) → pin to NVMe. Predictive scoring by ICD-10 / modality / department:
oncology & chronic disease → extended warm; clear outpatient screening → fast-track cold.

## Nationwide: federated hub-and-spoke
Not a monolith. Aligned with **IHE XDS.b** (heavy SOAP document sharing) or **IHE MHD**
(FHIR REST façade). Central hub stores only **pointers + the emergency core**; heavy
imaging stays at the originating region and streams on demand.

```
        [ Citizen & clinician apps / ED tablets / hospital EHRs ]
                          |
              (NGINX / Envoy gateway · Keycloak OAuth2/OIDC · mTLS)
                          |
        +-----------------+------------------+
        |                                    |
  CENTRAL NATIONAL HUB                 REGIONAL / EDGE (hospitals, clinics)
  · Master Patient Index (MyKad↔MRN)   · Local edge EMR + hot PACS
  · National Record Locator (pointers) · Local integration engine
  · Redis (auth + fast index)          · Edge cache (offline resilience)
  · Kafka (nationwide events)          · DICOM streamer (WADO-RS)
  · Distributed FHIR core repository   · Local MinIO warm storage
```

- **Master Patient Index** — one MyKad ↔ many facility MRNs. Redis hot cache
  (`National_ID → internal UUID`) over a distributed SQL store.
- **Record Locator Service** — "index centrally, stream locally". The hub resolves a
  pointer, authenticates the requester, and the viewer streams directly from the source
  region's PACS.
- **Event bus** — Kafka / Redpanda for millions of daily clinical events, audit logs,
  prefetch commands.
- **Edge survivability / island mode** — a rural clinic keeps operating during a WAN
  cut on its local cache; delta changes reconcile via Kafka when connectivity returns.

## The emergency / transfer payload: FHIR IPS
**FHIR International Patient Summary** (ISO 27269 + HL7 FHIR IPS IG) — a lightweight
bundle, not a full history:
- **Mandatory emergency core:** Patient, AllergyIntolerance, Condition (active),
  MedicationStatement.
- **Optional transfer data:** Immunization, DiagnosticReport, Device (implants /
  pacemakers), CarePlan / advance directives.

**First-responder access:** scan MyKad / medical-alert NFC/QR → a cached sub-50 KB
emergency card (blood group, critical allergies, vital meds, resuscitation status, next
of kin). **Break-glass** override bypasses 2FA consent but writes an immutable
cryptographic audit entry (responder ID, GPS, timestamp, incident number) — the audit
standard is **IHE ATNA**.

## Hospital-to-hospital transpose
Standard FHIR Encounter workflows: referring hospital emits
`Encounter (status=transferred)` + `ServiceRequest`; the National Record Locator emits
an event; the receiving hospital ingests the inbound IPS bundle and reconciles
medications against its formulary before arrival. In-transit telemetry streams as
`Observation` resources. Imaging continuity via a WADO-RS study link — no CD-ROMs, no
repeat scans.

## The cross-region stress test ("Penang today, Johor Bahru tomorrow")
Decouple **instant text/metadata sync** from **on-demand heavy imaging**:
- Day 1, discharge in Penang: full record + 500 MB CT saved locally; a < 50 KB IPS
  bundle pushed to the KL hub via Kafka; the CT **stays in Penang**.
- Day 2, JB triage scans MyKad: hub returns the IPS summary in < 200 ms.
- Day 2, JB doctor opens the Penang CT: WADO-RS streams only the viewed frames over the
  government WAN; a regional edge proxy in JB caches them for the next viewer.
- Scheduled referrals trigger an overnight off-peak full-imaging prefetch.

## Availability vs durability
Separate the two, and tier the SLA — **five-nines only for the emergency/identity tier**:

| Tier | Target | Strategy |
|---|---|---|
| Emergency & identity (MPI, allergies, blood type, break-glass) | 99.999% | active-active multi-region, edge caching, in-memory stores |
| Active clinical EMR & PACS streaming | 99.95–99.99% | geo-distributed k8s, local NVMe edge buffers |
| Historical deep archive | 99.9% | async prefetch queues; downtime doesn't halt acute care |

Data **durability** (11 nines) via **erasure coding** (Reed-Solomon 8+4 / 12+4 in Ceph
or MinIO) rather than three full copies. Physical: Tier III/IV data centres, dual power
feeds, 2(N+1) UPS, carrier-neutral dual-homed transit.

## Malaysia framing
KKM "One Individual, One Record"; public (THIS / CCMS / PhIS) + private (KPJ, IHH,
Pantai, Sunway); MyDigital ID for citizen auth; all central data within Malaysian
sovereign boundaries (MyGovCloud / local Tier-IV) per PDPA. The real programme today is
**MHNexus + MY Core** — see [[National Interoperability]].
