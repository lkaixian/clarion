"""
Medication Reconciliation and Interaction Support.

MediBridge uses this module for two related, but distinct, purposes:

1. A small, rule-based pairwise drug-drug interaction (DDI) demo
   (``KNOWN_INTERACTIONS`` / ``check_interactions``). A real product would
   call a licensed drug-interaction database (e.g. First Databank,
   Micromedex) or a dedicated interaction API. Those need commercial/API
   accounts, so this ships a small, clearly labelled reference table
   covering common, high-teaching-value interactions -- enough to demo the
   *mechanism* (cross-facility prescriptions colliding) convincingly. Swap
   ``KNOWN_INTERACTIONS`` for a real API call when time allows; the
   function signature is intentionally kept stable so the frontend does not
   need to change.

2. Medication identity/labeling support backed by NIH/NLM RxNorm and
   DailyMed (``MedicationProvider`` / ``get_medication_support`` /
   ``normalize_medications``). RxNorm is used for medication
   normalization/identity so that brand names and generics that resolve to
   the same concept are recognized as the same medication -- both for the
   rule-based interaction check above (matching against
   ``KNOWN_INTERACTIONS``) and for cross-facility duplicate-prescription
   detection. DailyMed supplies official FDA Structured Product Labeling.

Important:
- RxNorm/DailyMed support does NOT constitute a complete drug-drug
  interaction (DDI) engine. Absence of a warning or label match must NOT be
  interpreted as proof that no interaction exists.
- For production clinical DDI screening, replace/extend
  ``KNOWN_INTERACTIONS`` with a validated clinical drug-interaction
  database/service.

The public function signatures are intentionally simple so the backend API
and frontend do not need to change when a production DDI provider is added.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Rule-based interaction table (demo scope)
# ---------------------------------------------------------------------------

# (drug_a, drug_b) -> (severity, explanation) -- case-insensitive,
# order-independent. Keys are matched against a medication's RxNorm
# normalized name when available, falling back to the raw, lowercased
# input name otherwise (see `_canonical_key`).
KNOWN_INTERACTIONS: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"warfarin", "aspirin"}): (
        "high",
        "Increased bleeding risk when anticoagulants are combined.",
    ),
    frozenset({"warfarin", "ibuprofen"}): (
        "high",
        "NSAIDs increase bleeding risk with anticoagulants.",
    ),
    frozenset({"metformin", "contrast dye"}): (
        "moderate",
        "Risk of lactic acidosis; often held around imaging procedures.",
    ),
    frozenset({"simvastatin", "clarithromycin"}): (
        "high",
        "Increased risk of statin-induced muscle toxicity.",
    ),
    frozenset({"lisinopril", "spironolactone"}): (
        "moderate",
        "Combined use raises risk of hyperkalaemia.",
    ),
    frozenset({"sildenafil", "nitroglycerin"}): (
        "high",
        "Severe, potentially fatal hypotension when combined.",
    ),
    frozenset({"digoxin", "amiodarone"}): (
        "high",
        "Amiodarone increases digoxin plasma levels, raising toxicity risk.",
    ),
    frozenset({"methotrexate", "trimethoprim"}): (
        "high",
        "Combined use increases risk of severe methotrexate toxicity and "
        "bone marrow suppression.",
    ),
    frozenset({"clopidogrel", "omeprazole"}): (
        "moderate",
        "Omeprazole may reduce clopidogrel's antiplatelet effectiveness "
        "via CYP2C19 inhibition.",
    ),
    frozenset({"fluoxetine", "tramadol"}): (
        "high",
        "Combined use increases risk of serotonin syndrome.",
    ),
}


# ---------------------------------------------------------------------------
# External service configuration
# ---------------------------------------------------------------------------

RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
DAILYMED_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services"

DEFAULT_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MedicationServiceError(Exception):
    """Base exception for medication-service failures."""


class MedicationLookupError(MedicationServiceError):
    """Raised when a medication cannot be resolved or queried."""


class MedicationProviderError(MedicationServiceError):
    """Raised when an external provider request fails."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizedMedication:
    """
    Canonical medication identity returned by RxNorm.

    `rxcui` is the RxNorm concept identifier used as the canonical key
    throughout MediBridge.
    """

    original_name: str
    rxcui: str | None
    normalized_name: str | None
    status: str


@dataclass(frozen=True)
class MedicationLabel:
    """
    Official labeling result from DailyMed.
    """

    set_id: str | None
    title: str | None
    published_date: str | None
    url: str | None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class MedicationProvider:
    """
    Client for NIH/NLM medication services.

    RxNorm:
        - Medication normalization
        - RxCUI resolution
        - Canonical medication identity

    DailyMed:
        - Official product-label retrieval
        - FDA Structured Product Labeling source
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.timeout = timeout

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Perform a GET request against an external provider.
        """

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "MediBridge/1.0",
                    },
                )

                response.raise_for_status()

                return response.json()

        except httpx.HTTPStatusError as exc:
            raise MedicationProviderError(
                f"Provider returned HTTP {exc.response.status_code}: "
                f"{exc.request.url}"
            ) from exc

        except httpx.RequestError as exc:
            raise MedicationProviderError(
                f"Unable to contact medication provider: {exc}"
            ) from exc

        except ValueError as exc:
            raise MedicationProviderError(
                "Medication provider returned invalid JSON."
            ) from exc

    # -----------------------------------------------------------------------
    # RxNorm
    # -----------------------------------------------------------------------

    async def resolve_rxcui(
        self,
        medication_name: str,
    ) -> str | None:
        """
        Resolve a medication name to an RxNorm RxCUI.

        Returns None when RxNorm cannot identify the medication.
        """

        name = medication_name.strip()

        if not name:
            return None

        url = f"{RXNORM_BASE_URL}/rxcui.json"

        data = await self._get(
            url,
            params={
                "name": name,
                "search": 1,
            },
        )

        id_group = data.get("idGroup", {})
        rxnorm_ids = id_group.get("rxnormId", [])

        if not rxnorm_ids:
            return None

        return str(rxnorm_ids[0])

    async def get_rxcui_properties(
        self,
        rxcui: str,
    ) -> dict[str, Any]:
        """
        Retrieve RxNorm properties for an RxCUI.
        """

        if not rxcui.strip():
            raise MedicationLookupError("RxCUI cannot be empty.")

        url = f"{RXNORM_BASE_URL}/rxcui/{rxcui}/allProperties.json"

        return await self._get(
            url,
            params={
                "prop": "all",
            },
        )

    async def get_rxcui_name(
        self,
        rxcui: str,
    ) -> str | None:
        """
        Resolve an RxCUI back to a preferred RxNorm name.
        """

        if not rxcui.strip():
            return None

        url = f"{RXNORM_BASE_URL}/rxcui/{rxcui}/properties.json"

        data = await self._get(url)

        properties = data.get("properties", {})

        name = properties.get("name")

        return name.strip() if isinstance(name, str) else None

    async def normalize_medication(
        self,
        medication_name: str,
    ) -> NormalizedMedication:
        """
        Convert an arbitrary medication name into an RxNorm identity.
        """

        original = medication_name.strip()

        if not original:
            return NormalizedMedication(
                original_name=medication_name,
                rxcui=None,
                normalized_name=None,
                status="invalid",
            )

        rxcui = await self.resolve_rxcui(original)

        if not rxcui:
            return NormalizedMedication(
                original_name=original,
                rxcui=None,
                normalized_name=None,
                status="unrecognized",
            )

        normalized_name = await self.get_rxcui_name(rxcui)

        return NormalizedMedication(
            original_name=original,
            rxcui=rxcui,
            normalized_name=normalized_name,
            status="resolved",
        )

    # -----------------------------------------------------------------------
    # DailyMed
    # -----------------------------------------------------------------------

    async def search_dailymed(
        self,
        medication_name: str,
        *,
        limit: int = 10,
    ) -> list[MedicationLabel]:
        """
        Search DailyMed for official product labels.

        DailyMed is used here as the source of official labeling rather than
        pretending that it is a complete DDI database.
        """

        name = medication_name.strip()

        if not name:
            return []

        url = f"{DAILYMED_BASE_URL}/v2/spls.json"

        data = await self._get(
            url,
            params={
                "drug_name": name,
                "page": 1,
                "pagesize": limit,
            },
        )

        results: list[MedicationLabel] = []

        for item in data.get("data", []):
            set_id = item.get("setid")
            title = item.get("title")
            published_date = item.get("publishedDate")

            results.append(
                MedicationLabel(
                    set_id=str(set_id) if set_id else None,
                    title=title.strip() if isinstance(title, str) else None,
                    published_date=(
                        str(published_date)
                        if published_date
                        else None
                    ),
                    url=(
                        f"https://dailymed.nlm.nih.gov/"
                        f"dailymed/drugInfo.cfm?setid={set_id}"
                        if set_id
                        else None
                    ),
                )
            )

        return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _normalize_many(
    names: list[str],
    provider: MedicationProvider,
) -> dict[str, NormalizedMedication]:
    """
    Normalize a set of medication names concurrently through RxNorm.

    Names are looked up in parallel via `asyncio.gather` (rather than one
    sequential `await` per medication) so an N-medication interaction check
    costs roughly one round-trip's worth of wall time instead of N.

    Returns a mapping keyed by the casefolded, stripped medication name to
    its `NormalizedMedication` result. A single medication's lookup failure
    (network error, bad response, timeout, etc.) is isolated to that
    medication -- it degrades to a "lookup_failed" status instead of
    aborting every other medication's lookup or raising out of this
    function.
    """

    unique_names: list[str] = []
    seen: set[str] = set()

    for name in names:
        cleaned = name.strip()

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key in seen:
            continue

        seen.add(key)
        unique_names.append(cleaned)

    if not unique_names:
        return {}

    raw_results = await asyncio.gather(
        *(provider.normalize_medication(name) for name in unique_names),
        return_exceptions=True,
    )

    normalized: dict[str, NormalizedMedication] = {}

    for name, result in zip(unique_names, raw_results):
        if isinstance(result, BaseException):
            normalized[name.casefold()] = NormalizedMedication(
                original_name=name,
                rxcui=None,
                normalized_name=None,
                status="lookup_failed",
            )
        else:
            normalized[name.casefold()] = result

    return normalized


def _canonical_key(
    name: str,
    normalized: NormalizedMedication | None,
) -> str:
    """
    Build the key used to match a medication against `KNOWN_INTERACTIONS`
    and to group medications for duplicate-prescription detection.

    Prefers the RxNorm-normalized name so that brand names and generics
    resolving to the same RxNorm concept are treated as the same
    medication. Falls back to the raw, lowercased/stripped input name when
    RxNorm did not resolve the medication (unrecognized, invalid, or the
    lookup failed -- e.g. no network access) so matching still works
    offline, exactly like the original plain rule-based implementation.
    """

    if (
        normalized is not None
        and normalized.rxcui
        and normalized.normalized_name
    ):
        return normalized.normalized_name.strip().casefold()

    return name.strip().casefold()


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

async def normalize_medications(
    drug_names: list[str],
    *,
    provider: MedicationProvider | None = None,
) -> list[NormalizedMedication]:
    """
    Normalize a collection of medication names through RxNorm.

    Duplicate input strings are removed while preserving order. Lookups run
    concurrently; a single medication's lookup failure does not affect the
    others (see `_normalize_many`).
    """

    provider = provider or MedicationProvider()

    unique_names: list[str] = []
    seen: set[str] = set()

    for name in drug_names:
        cleaned = name.strip()

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key in seen:
            continue

        seen.add(key)
        unique_names.append(cleaned)

    normalized_map = await _normalize_many(unique_names, provider)

    return [normalized_map[name.casefold()] for name in unique_names]


# ---------------------------------------------------------------------------
# Rule-based pairwise interaction check
# ---------------------------------------------------------------------------

async def check_interactions(
    drug_names: list[str],
    *,
    provider: MedicationProvider | None = None,
) -> list[dict[str, Any]]:
    """
    Check a list of medications against the `KNOWN_INTERACTIONS` reference
    table and return one entry per interacting *pair*.

    Medication identity is resolved through RxNorm (when reachable) before
    matching against the table, so brand names and generics that resolve to
    the same RxNorm concept are still recognized -- e.g. a brand name that
    RxNorm normalizes to "warfarin" will match a `KNOWN_INTERACTIONS` entry
    keyed on "warfarin" even if the input string was different. When RxNorm
    cannot resolve a medication (unrecognized, or the lookup fails/times
    out), matching falls back to the raw, lowercased input name so this
    still works offline.

    This is a demo-scope reference table, not a validated clinical DDI
    engine -- see the module docstring.

    Returns:
        A list of dicts shaped
        `{"drug_a": str, "drug_b": str, "severity": str, "explanation": str}`,
        one per matched pair.
    """

    provider = provider or MedicationProvider()

    cleaned = [d.strip() for d in drug_names if d.strip()]

    if len(cleaned) < 2:
        return []

    normalized_map = await _normalize_many(cleaned, provider)

    canonical_keys = [
        _canonical_key(name, normalized_map.get(name.casefold()))
        for name in cleaned
    ]

    findings: list[dict[str, Any]] = []

    for i, j in combinations(range(len(cleaned)), 2):
        key = frozenset({canonical_keys[i], canonical_keys[j]})

        match = KNOWN_INTERACTIONS.get(key)

        if match is None:
            continue

        severity, explanation = match

        findings.append(
            {
                "drug_a": cleaned[i].lower(),
                "drug_b": cleaned[j].lower(),
                "severity": severity,
                "explanation": explanation,
            }
        )

    return findings


# ---------------------------------------------------------------------------
# RxNorm/DailyMed medication support (identity + official labeling)
# ---------------------------------------------------------------------------

async def get_medication_support(
    drug_names: list[str],
    *,
    provider: MedicationProvider | None = None,
) -> list[dict[str, Any]]:
    """
    Resolve medications through RxNorm and retrieve official DailyMed label
    availability, one entry per medication.

    IMPORTANT:
    This function intentionally does not return a pairwise interaction
    result or a false "no interaction" result -- for that, see
    `check_interactions`. RxNorm identifies medications, while DailyMed
    supplies official labeling. A true pairwise DDI result requires a
    validated DDI source.

    Result statuses:

        resolved
            Medication successfully identified by RxNorm.

        unrecognized
            Medication could not be identified by RxNorm.

        lookup_failed
            The RxNorm lookup itself failed (network/provider error,
            timeout, etc.) rather than RxNorm cleanly reporting "not
            found".

        label_available
            Official DailyMed labeling was found.

        label_unavailable
            No DailyMed label was found for the queried medication, or the
            DailyMed lookup failed.

    Medication lookups (RxNorm and DailyMed) run concurrently across all
    input medications; a single medication's failure is isolated and
    degrades only that entry.
    """

    provider = provider or MedicationProvider()

    normalized = await normalize_medications(drug_names, provider=provider)

    resolved = [medication for medication in normalized if medication.rxcui]

    label_results: dict[str, list[MedicationLabel] | BaseException] = {}

    if resolved:
        raw_labels = await asyncio.gather(
            *(
                provider.search_dailymed(medication.original_name)
                for medication in resolved
            ),
            return_exceptions=True,
        )

        for medication, labels in zip(resolved, raw_labels):
            label_results[medication.original_name] = labels

    findings: list[dict[str, Any]] = []

    for medication in normalized:

        result: dict[str, Any] = {
            "drug": medication.original_name,
            "normalized_name": medication.normalized_name,
            "rxcui": medication.rxcui,
            "status": medication.status,
            "source": "NIH/NLM RxNorm",
        }

        if medication.rxcui is None:
            message = (
                "RxNorm lookup failed (network/provider error). Clinical "
                "interaction screening was not performed."
                if medication.status == "lookup_failed"
                else (
                    "Medication could not be resolved through RxNorm. "
                    "Clinical interaction screening was not performed."
                )
            )

            result.update(
                {
                    "label_status": "unavailable",
                    "message": message,
                }
            )

            findings.append(result)
            continue

        labels = label_results.get(medication.original_name)

        if isinstance(labels, BaseException):
            result.update(
                {
                    "label_status": "unavailable",
                    "label_source": "NLM DailyMed / FDA labeling",
                    "labels": [],
                    "message": (
                        "Medication was identified by RxNorm, but the "
                        "DailyMed label lookup failed (network/provider "
                        "error)."
                    ),
                }
            )
        elif labels:
            result.update(
                {
                    "label_status": "available",
                    "label_source": "NLM DailyMed / FDA labeling",
                    "labels": [
                        {
                            "set_id": label.set_id,
                            "title": label.title,
                            "published_date": label.published_date,
                            "url": label.url,
                        }
                        for label in labels
                    ],
                    "message": (
                        "Official product labeling is available. "
                        "A dedicated validated DDI provider is required "
                        "for definitive pairwise interaction screening."
                    ),
                }
            )
        else:
            result.update(
                {
                    "label_status": "unavailable",
                    "label_source": "NLM DailyMed / FDA labeling",
                    "labels": [],
                    "message": (
                        "Medication was identified by RxNorm, but no "
                        "matching DailyMed label was found."
                    ),
                }
            )

        findings.append(result)

    return findings


# ---------------------------------------------------------------------------
# Cross-facility duplicate prescription detection
# ---------------------------------------------------------------------------

async def check_duplicate_prescriptions(
    medications: list[dict[str, Any]],
    *,
    provider: MedicationProvider | None = None,
) -> list[str]:
    """
    Flags the same active medication prescribed by more than one facility --
    the classic cross-hospital blind-spot this project exists to catch.

    Expected medication format:

        {
            "drug_name": "Warfarin",
            "active": True,
            "prescribed_by_facility": "Hospital A"
        }

    Medication identity is resolved through RxNorm (when reachable) instead
    of plain string comparison, so different names for the same medication
    (e.g. a brand name at one facility and its generic at another) can be
    reconciled where RxNorm resolves them to the same concept. When RxNorm
    cannot resolve a medication, matching falls back to the raw, lowercased
    name so this still works offline.

    Lookups run concurrently across all active medications.

    Returns:
        A list of human-readable strings, one per facility pair a duplicate
        spans, e.g. `"Warfarin prescribed by both Hospital A and Hospital B"`.
        A medication active at 3+ facilities produces one string per pair
        of facilities.
    """

    provider = provider or MedicationProvider()

    active: list[tuple[str, str]] = []

    for medication in medications:

        if not medication.get("active"):
            continue

        raw_name = medication.get("drug_name")

        if not isinstance(raw_name, str):
            continue

        drug_name = raw_name.strip()

        if not drug_name:
            continue

        facility = medication.get(
            "prescribed_by_facility",
            "unknown",
        )

        facility = (
            str(facility).strip()
            if facility is not None
            else "unknown"
        ) or "unknown"

        active.append((drug_name, facility))

    if not active:
        return []

    normalized_map = await _normalize_many(
        [drug_name for drug_name, _ in active],
        provider,
    )

    grouped: dict[str, dict[str, Any]] = {}

    for drug_name, facility in active:
        normalized = normalized_map.get(drug_name.casefold())
        key = _canonical_key(drug_name, normalized)

        entry = grouped.setdefault(
            key,
            {
                "display_name": (
                    normalized.normalized_name
                    if normalized and normalized.normalized_name
                    else drug_name
                ),
                "facilities": set(),
            },
        )

        entry["facilities"].add(facility)

    duplicates: list[str] = []

    for entry in grouped.values():

        facilities = sorted(entry["facilities"])

        if len(facilities) <= 1:
            continue

        for facility_a, facility_b in combinations(facilities, 2):
            duplicates.append(
                f"{entry['display_name']} prescribed by both "
                f"{facility_a} and {facility_b}"
            )

    return duplicates


# ---------------------------------------------------------------------------
# Combined medication reconciliation
# ---------------------------------------------------------------------------

async def reconcile_medications(
    medications: list[dict[str, Any]],
    *,
    provider: MedicationProvider | None = None,
) -> dict[str, Any]:
    """
    Run the MediBridge medication reconciliation workflow.

    Returns:
        {
            "medications": [...],
            "duplicates": [...],
            "interaction_support": [...]
        }

    `interaction_support` reports RxNorm/DailyMed identity and labeling
    coverage per medication (see `get_medication_support`) -- it
    deliberately reports source/coverage state rather than claiming that
    the absence of a finding means "safe". For rule-based pairwise
    interaction warnings, see `check_interactions` separately.
    """

    provider = provider or MedicationProvider()

    active_medications = [
        med
        for med in medications
        if med.get("active")
        and isinstance(med.get("drug_name"), str)
        and med["drug_name"].strip()
    ]

    drug_names = [
        med["drug_name"].strip()
        for med in active_medications
    ]

    normalized = await normalize_medications(
        drug_names,
        provider=provider,
    )

    duplicates = await check_duplicate_prescriptions(
        active_medications,
        provider=provider,
    )

    interaction_support = await get_medication_support(
        drug_names,
        provider=provider,
    )

    return {
        "medications": [
            {
                "original_name": item.original_name,
                "normalized_name": item.normalized_name,
                "rxcui": item.rxcui,
                "status": item.status,
            }
            for item in normalized
        ],
        "duplicates": duplicates,
        "interaction_support": interaction_support,
        "interaction_engine": {
            "status": "not_available",
            "message": (
                "RxNorm and DailyMed provide medication normalization "
                "and official labeling. A validated clinical drug-drug "
                "interaction database is required for definitive "
                "pairwise DDI screening beyond the KNOWN_INTERACTIONS "
                "demo table used by check_interactions."
            ),
        },
    }
