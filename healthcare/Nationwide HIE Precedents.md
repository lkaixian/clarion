---
title: Nationwide HIE Precedents
type: research
updated: 2026-08-30
tags: [research, hie, fhir, ihe, national]
---

# Nationwide HIE Precedents

Supporting research for [[Nationwide Health Information Exchange]] (the bigger-vision
design). Validates the architecture claims from the Gemini thread against real systems.

## Standards
- **IPS (International Patient Summary):** **ISO 27269** = the conceptual content model
  / data blocks; **HL7 FHIR IPS Implementation Guide** = the technical spec.
  ([international-patient-summary.net](https://international-patient-summary.net/))
- **IHE XDS.b** = heavyweight SOAP/ebXML cross-enterprise document sharing.
  **IHE MHD** = lightweight RESTful FHIR façade, often layered on XDS.b.
- **Record Locator Service** = index/pointer service; decouples data *location* from
  data *storage*. Depends on a robust **Master Patient Index** (National ID ↔ facility
  MRNs). "Index centrally, stream locally."
- **Break-glass** → immutable audit; the audit standard is **IHE ATNA**.
- **Erasure coding** (Reed-Solomon) in **Ceph / MinIO** for geo-distributed durability
  vs full mirroring. Active-active geo-distribution and five-nines SLA tiering are
  standard enterprise patterns (not single-source-citable).

## Real national / regional exchanges
| Country | Model | Notes |
|---|---|---|
| **Estonia** | Decentralised — X-Road data-exchange layer with Security Servers | KSI blockchain for data integrity / tamper-evidence. [e-estonia.com](https://e-estonia.com/) |
| **Denmark** | Federated — sundhed.dk integrates 120+ local sources in real time | MedCom runs national messaging (SDN → EHMI). [medcom.dk](https://www.medcom.dk/) |
| **Austria (ELGA)** | Decentralised — holds *references* to documents | HL7 CDA + IHE profiles; the e-card is the key. [elga.gv.at](https://www.elga.gv.at/) |
| **Australia** | My Health Record — migrating CDA central repo → FHIR APIs | B2B Gateway (NASH certs) / FHIR Gateway |
| **India (ABDM)** | Federated, consent-based | ABHA health ID + HIE-CM on FHIR R4; data stays at source. [abdm.gov.in](https://abdm.gov.in/) |
| **Singapore (NEHR)** | Centralised Summary Care Record | Synapxe; system-to-system integration + break-the-glass. [synapxe.sg](https://www.synapxe.sg/) |
| **Malaysia (MyHDW)** | Hybrid RDBMS + Hadoop/HDFS analytics warehouse | MIMOS-built, DIGC governance. Not an open hub. See [[National Interoperability]] |

## Storage tiering / HSM
Hot (NVMe) → warm (MinIO/Ceph) → cold (LTO tape / WORM). Clinical-event-driven
tiering: discharge → demote; upcoming appointment (HL7 SIU) → overnight prefetch
cold→hot; chronic/oncology → keep warm. DICOM prefetching driven by scheduling events.

Detail: `scratchpad/agy-research-full.md` Part 2 Topic G + the Gemini thread
(`gemin-text.txt` in the repo root). See [[Sources]].
