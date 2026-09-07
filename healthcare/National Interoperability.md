---
title: National Interoperability
type: research
updated: 2026-08-30
tags: [research, fhir, mhnexus, mysejahtera, interoperability, malaysia]
---

# National Interoperability

How to satisfy clause **** — schema natively
supports HL7 FHIR-compatible modelling, "future interoperability with MySejahtera or
PADU without schema restructuring".

## Malaysia has a real national exchange
- **MHNexus** was mandated by the MOH in **2022** to design, build and operate a
  FHIR-based **Health Information Exchange** for public hospitals and clinics. Began in
  **Negeri Sembilan**, linked **156 public facilities in 2 years**, nationwide rollout
  planned (peninsula + east Malaysia), collaborators include PHCorp, MySejahtera, PERKESO.
- Runs on the **Smile CDR** FHIR engine (HAPI-based), **HL7 FHIR R4**.
- Publishes **MY Core** — the national FHIR base profile — on
  [simplifier.net/guide/mycore](https://simplifier.net/guide/mycore) (also
  [my-core.ig.mhnexus.com](https://my-core.ig.mhnexus.com/), v2.0.1). Organisations
  build *derivative profiles* that retain the base features.
- Wider programme: Health White Paper 2023 (15-year roadmap); "One Individual, One
  Record" / Electronic Lifetime Health Record under the new Digital Health Division;
  **CCMS** cloud clinic system to ~3,000 primary facilities by 2028; hospital HIS
  digitisation by 2029. **MyHDW** is an analytics/big-data warehouse (RDBMS + Hadoop),
  not an open hub.

## But there is NO public API
**High confidence.** No developer portal, no SMART-on-FHIR sandbox, no documented route
for an independent university clinic to push or pull records today. Integration is
government-to-government (via MyGDX) or named-partner-gated. Some commercial EMR vendors
advertise "MySejahtera-ready" modules but through partner arrangements, not an open API.

**PADU** ([padu.gov.my](https://padu.gov.my)) is a socioeconomic database for subsidy
targeting — **not a clinical integration target**. Treat that half of the tender
as MySejahtera / MHNexus.

## So the only real move: FHIR-readiness of the schema
Connecting later becomes a **serialiser, not a migration**. Concretely (detail in
[[FHIR Schema Readiness]]):
- Coding triples `{concept}_system` / `_code` / `_display` on every clinical table.
- A `resource_identifiers` side table (MyKad, MRN, later an MHNexus id).
- A thin **read-only FHIR façade** over existing tables — not a FHIR server as system
  of record.
- New module tables (`observations`, `diagnostic_reports`, `service_requests`,
  `procedures`, `imaging_studies`) designed to map to their FHIR resources from day one.

## Terminology
| Domain | Standard | Note |
|---|---|---|
| Diagnoses / morbidity | **ICD-10** | Dominant; drives Casemix/DRG funding |
| Medications | **Malaysian Drug Code (MDC)** | NPRA/MOH; mandatory for *Formulari Ubat KKM*; **not RxNorm-compatible** — needs a cross-map |
| Clinical findings / allergies | **SNOMED CT** | Malaysia member since 2012 (HIC-managed); growing in CCMS |
| Lab observations | **LOINC** | Standard for lab/observation coding |

Detail: `scratchpad/agy-research-full.md` Part 1 Topic C + Part 2 "MySejahtera / Malaysia
HIE FHIR integration status". See [[Sources]].
