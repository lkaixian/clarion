---
title: FHIR Schema Readiness
type: architecture
updated: 2026-08-30
tags: [architecture, fhir, schema, interoperability]
---

# FHIR Schema Readiness

How to satisfy tender clause **** — schema natively supports HL7 FHIR-compatible
modelling, "future interoperability with MySejahtera / PADU without schema
restructuring". Context: [[National Interoperability]] (there is no public API today, so
this is purely about *readiness*).

## Recommended approach
**Annotate the existing tables + add a thin read-only FHIR façade.**
Do **not** restructure around FHIR resources. Do **not** make a full FHIR server the
system of record. CLARION's ~30 tables are already close (Encounter, Condition,
MedicationStatement, AllergyIntolerance naming; several are append-only).

## Cross-cutting columns (on clinical tables)
- Reuse `id` as the FHIR logical id.
- `identifier_system` / `identifier_value` — plus a repeatable **`resource_identifiers`**
  side table (MyKad, MRN, later an MHNexus id).
- `fhir_version_id` + `last_updated` (meta / ETag), `fhir_status`.
- Provenance via the existing `*_facility` columns.

## Coding triples
`{concept}_system` / `{concept}_code` / `{concept}_display` — nullable, keep the
free-text label alongside.

| Table | Code system | Extras |
|---|---|---|
| `conditions` | **ICD-10-CM** (+ optional SNOMED) | clinical / verification / category status |
| `medication_statements` | **Malaysian Drug Code / MyDrug** (fallback ATC / SNOMED) | route, dose, **UCUM** unit |
| `allergy_intolerances` | SNOMED / MDC | type, category, criticality, reaction |
| `encounters` | v3 class code | type, period, practitioner |
| `patients` | MyKad identifier | FHIR administrative-gender; race / marital / language codes |

## New tables the modules need anyway (design to map from day one)
| Table | FHIR resource | Backs |
|---|---|---|
| `observations` | Observation (**LOINC** + UCUM) | vitals + labs; the tender trend/critical AI |
| `diagnostic_reports` | DiagnosticReport (LOINC panels) | Lab / X-ray reporting |
| `service_requests` | ServiceRequest | the /.11.4 referrals + lab/imaging orders |
| `procedures` | Procedure (ICD-9-CM / SNOMED; **FDI tooth notation** for dental) | Procedure + Dental modules |
| `immunizations` | Immunization (MOH vaccine code) | MySejahtera exchange point |
| `imaging_studies` | ImagingStudy (DICOM StudyInstanceUID + accession + WADO-RS endpoint) | ↔ Orthanc, [[PACS and DICOM]] |
| `document_references` | DocumentReference (LOINC document type) | over `clinical_documents` |

## Terminology, right-sized
- Store the triple **inline** — no terminology server.
- Ship **small seed lookup tables** (an ICD-10 subset, ~100 common LOINC, the
  formulary / MyDrug) behind UI type-ahead pickers so codes actually get captured.
- A `code_system` registry validates every `system` URI.

## Provenance / AuditEvent
The façade emits these from the existing `signed_by_*` snapshots + `audit_logs` — no
new columns.

## Rollout
2–3 Alembic revisions. Existing rows get NULL codes (valid — `code` is `[0..1]`);
best-effort backfill with a clinician-review queue. **MySejahtera / PADU later = a
façade profile + a `resource_identifiers` row, zero table changes** — that is the
demonstrable "no restructuring" guarantee for the tender response.

Source: `scratchpad/architecture.md` §3.
