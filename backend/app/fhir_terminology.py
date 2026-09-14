"""P4.1/P4.2: the FHIR coding-system allowlist.

No terminology DB table (see healthcare/FHIR Schema Readiness.md -- "store
the triple inline, no terminology server"). This is the one place that
decides which `code_system` values the coding-triple columns (Condition/
MedicationStatement/AllergyIntolerance/ServiceCatalogItem/ResourceIdentifier)
and the FHIR façade (routers/fhir.py) accept -- adding a system later (a real
ICD-10/MyDrug/LOINC feed, MHNexus) is a one-line addition here, no migration.

Deliberately ships with NO seed code lists (no fabricated ICD-10/MyDrug/LOINC
subset): those are licensed/MOH-provided reference data, not something to
hand-roll for a demo. Clinicians type a code + display today; wiring a real
terminology feed behind the same columns is a content task, not a schema one.
"""

CODE_SYSTEMS = {
    # Conditions
    "icd10cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "snomed": "http://snomed.info/sct",
    # Medications
    "mydrug": "https://fhir.moh.gov.my/CodeSystem/mydrug",
    "atc": "http://www.whocc.no/atc",
    # Allergies
    "mdc": "https://fhir.moh.gov.my/CodeSystem/mdc",
    # Ancillary services (labs/procedures/imaging)
    "loinc": "http://loinc.org",
    "icd9cm-procedure": "http://hl7.org/fhir/sid/icd-9-cm/procedure",
    # Identifiers
    "mykad": "https://fhir.moh.gov.my/NamingSystem/mykad",
    "mrn": "https://fhir.moh.gov.my/NamingSystem/mrn",
    "mhnexus": "https://fhir.moh.gov.my/NamingSystem/mhnexus",
}


def is_known_code_system(system: str | None) -> bool:
    """True for None (uncoded is valid FHIR) or any allowlisted URI."""
    return system is None or system in CODE_SYSTEMS.values()
