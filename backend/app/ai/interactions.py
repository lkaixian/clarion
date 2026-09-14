"""
Medication Reconciliation and Interaction Support.

CLARION uses this module for two related, but distinct, purposes:

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

3. Drug-class-level screening (P4.4, the tender), layered on
   top of both of the above using RxClass (also free NIH/NLM data, same
   family as RxNorm/DailyMed):
   - ``CLASS_INTERACTIONS`` generalizes ``KNOWN_INTERACTIONS`` from named
     pairs to therapeutic classes (matched by ATC classId prefix, e.g. any
     NSAID + any anticoagulant/antiplatelet), so ``check_interactions``
     catches combinations the named-pair table doesn't happen to list.
   - ``check_allergy_conflicts`` (used by ``ai/cds_hint.py``) generalizes
     the plain substring allergy check the same way -- e.g. a "Penicillin"
     allergy now also flags "Amoxicillin" via their shared ATC class, not
     just an exact name match.
   - ``screen_prescription`` (used by the pre-save Add Medication check,
     ``GET /ai/prescription-screen/{patient_id}``) runs both checks against
     a single candidate drug name that has not been saved yet -- the
     tender's "real-time alert before confirmation" requirement.

Important:
- RxNorm/DailyMed support does NOT constitute a complete drug-drug
  interaction (DDI) engine. Absence of a warning or label match must NOT be
  interpreted as proof that no interaction exists.
- For production clinical DDI screening, replace/extend
  ``KNOWN_INTERACTIONS``/``CLASS_INTERACTIONS`` with a validated clinical
  drug-interaction database/service (e.g. First Databank, Micromedex, or
  Malaysia's MIMS). MIMS itself has no public API and requires a paid
  clinical-data license -- out of reach for a self-hosted demo, same call as
  declining to fabricate a seed ICD-10/MyDrug/LOINC list in P4.1/P4.2 (see
  the roadmap). ``RISK_CLASS_PREFIXES``/``ALLERGY_CLASS_PREFIXES`` below are
  a small, curated set of real ATC classes -- a genuine improvement over
  plain name matching, still not a licensed formulary's full coverage.

The public function signatures are intentionally simple so the backend API
and frontend do not need to change when a production DDI provider is added.
"""

from __future__ import annotations

import asyncio
import time
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
RXCLASS_BASE_URL = "https://rxnav.nlm.nih.gov/REST/rxclass"

DEFAULT_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Class-level rule tables (P4.4)
# ---------------------------------------------------------------------------
# ATC codes are hierarchical (e.g. "B01AA" -- Vitamin K antagonists -- sits
# under "B01A" -- Antithrombotic agents), so a classId *prefix* groups every
# drug in a therapeutic class without listing each one by name. Each label
# below was checked against RxNav's live RxClass API for its example drugs
# before being added here (see the P4.4 changelog entry) -- these are not
# guessed class codes.
RISK_CLASS_PREFIXES: dict[str, tuple[str, ...]] = {
    "anticoagulant_or_antiplatelet": ("B01A",),  # e.g. warfarin, clopidogrel, DOACs
    "nsaid": ("M01A",),                          # e.g. ibuprofen, naproxen, diclofenac
    "ace_inhibitor": ("C09A",),                  # e.g. lisinopril, enalapril
    "potassium_sparing_diuretic": ("C03D",),     # e.g. spironolactone
    "statin": ("C10AA",),                        # e.g. simvastatin, atorvastatin
    "macrolide": ("J01FA",),                     # e.g. clarithromycin, erythromycin
}

# (class_a, class_b) -> (severity, explanation), matched the same way as
# KNOWN_INTERACTIONS but keyed on the labels above instead of drug names --
# demo-scope curated set, not exhaustive.
CLASS_INTERACTIONS: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"anticoagulant_or_antiplatelet", "nsaid"}): (
        "high",
        "NSAIDs increase bleeding risk when combined with any anticoagulant "
        "or antiplatelet agent (drug-class match).",
    ),
    frozenset({"ace_inhibitor", "potassium_sparing_diuretic"}): (
        "moderate",
        "ACE inhibitors combined with potassium-sparing diuretics raise the "
        "risk of hyperkalaemia (drug-class match).",
    ),
    frozenset({"statin", "macrolide"}): (
        "high",
        "Macrolide antibiotics can raise statin plasma levels via CYP3A4 "
        "inhibition, increasing risk of myopathy/rhabdomyolysis (drug-class "
        "match).",
    ),
}

# Allergy-substance keyword (matched as a substring of the clinician-entered
# allergy substance, same convention as the plain-name check below) -> ATC
# classId prefixes it cross-reacts with. Also verified live against RxClass
# for the example drugs before being added.
ALLERGY_CLASS_PREFIXES: dict[str, tuple[str, ...]] = {
    "penicillin": ("J01C",),      # e.g. amoxicillin, ampicillin
    "cephalosporin": ("J01D",),   # e.g. cephalexin
    "sulfa": ("J01E",),           # e.g. sulfamethoxazole
    "sulfonamide": ("J01E",),
    "nsaid": ("M01A",),           # e.g. ibuprofen, naproxen
    "aspirin": ("M01A", "N02BA"),
}


# ---------------------------------------------------------------------------
# Shared HTTP client + in-process response cache
# ---------------------------------------------------------------------------
# Code-review follow-up 2026-09-07: the interaction-check endpoint previously called
# resolve/normalize once per medication PER top-level function (3x the work
# for the same drug set), spun up a brand-new httpx.AsyncClient on every
# single request (no connection reuse), and kept no cache between requests
# -- so every button press re-hit rxnav.nlm.nih.gov / dailymed.nlm.nih.gov
# from scratch (~6N + N external calls) with a real risk of NIH throttling
# the deployment.
#
# RxNorm identity and DailyMed label availability for a given drug name are
# effectively static, so a 1-hour process-local TTL cache is safe and
# removes almost all repeat traffic. The cache key always includes the
# lookup kind so the three namespaces never collide.

_CACHE_TTL_SECONDS = 3600.0
_CACHE_MAX_ENTRIES = 5000
_MISS = object()
_response_cache: dict[tuple[str, str], tuple[float, Any]] = {}

_shared_client: httpx.AsyncClient | None = None


def _cache_get(key: tuple[str, str]) -> Any:
    hit = _response_cache.get(key)
    if hit is None:
        return _MISS
    stored_at, value = hit
    if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
        _response_cache.pop(key, None)
        return _MISS
    return value


def _cache_put(key: tuple[str, str], value: Any) -> None:
    # Crude bound -- the real drug vocabulary is a few hundred names, so this
    # only trips under pathological/abusive input; a full clear is fine.
    if len(_response_cache) >= _CACHE_MAX_ENTRIES:
        _response_cache.clear()
    _response_cache[key] = (time.monotonic(), value)


def _get_shared_client() -> httpx.AsyncClient:
    """One pooled AsyncClient for the process (FastAPI runs a single event
    loop). Recreated only if it was closed."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "CLARION/1.0"},
        )
    return _shared_client


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
    throughout CLARION.
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
            client = _get_shared_client()
            response = await client.get(url, params=params)
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

        cache_key = ("resolve_rxcui", name.casefold())
        cached = _cache_get(cache_key)
        if cached is not _MISS:
            return cached

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

        result = str(rxnorm_ids[0]) if rxnorm_ids else None
        _cache_put(cache_key, result)
        return result

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

        cache_key = ("get_rxcui_name", rxcui.strip())
        cached = _cache_get(cache_key)
        if cached is not _MISS:
            return cached

        url = f"{RXNORM_BASE_URL}/rxcui/{rxcui}/properties.json"

        data = await self._get(url)

        properties = data.get("properties", {})

        name = properties.get("name")

        result = name.strip() if isinstance(name, str) else None
        _cache_put(cache_key, result)
        return result

    async def get_drug_classes(
        self,
        rxcui: str,
    ) -> frozenset[str]:
        """
        Resolve an RxCUI to its ATC classIds via RxClass (P4.4).

        Returns an empty frozenset when RxClass reports no classes for this
        RxCUI. Raises `MedicationServiceError` on a provider failure -- same
        as `resolve_rxcui`/`get_rxcui_properties` -- callers isolate this via
        `asyncio.gather(return_exceptions=True)`, same pattern as the rest of
        this module.
        """

        if not rxcui.strip():
            return frozenset()

        cache_key = ("get_drug_classes", rxcui.strip())
        cached = _cache_get(cache_key)
        if cached is not _MISS:
            return cached

        url = f"{RXCLASS_BASE_URL}/class/byRxcui.json"

        data = await self._get(
            url,
            params={
                "rxcui": rxcui,
                "relaSource": "ATC",
            },
        )

        items = data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo") or []

        class_ids = frozenset(
            item.get("rxclassMinConceptItem", {}).get("classId")
            for item in items
            if item.get("rxclassMinConceptItem", {}).get("classId")
        )

        _cache_put(cache_key, class_ids)
        return class_ids

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

        cache_key = ("search_dailymed", f"{name.casefold()}|{limit}")
        cached = _cache_get(cache_key)
        if cached is not _MISS:
            return cached

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

        _cache_put(cache_key, results)
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


async def _resolve_classes_many(
    normalized: dict[str, NormalizedMedication],
    provider: MedicationProvider,
) -> dict[str, frozenset[str]]:
    """
    Resolve ATC drug classes (P4.4) for every already-RxNorm-resolved
    medication in `normalized`, concurrently. Skips medications RxNorm could
    not identify -- there is no RxCUI to look up classes for. A single
    medication's class lookup failure is isolated to that medication and
    degrades to an empty class set, same discipline as `_normalize_many`.

    Returns a mapping keyed the same way as `normalized` (casefolded name).
    """

    resolvable = [(key, med.rxcui) for key, med in normalized.items() if med.rxcui]

    if not resolvable:
        return {}

    raw_results = await asyncio.gather(
        *(provider.get_drug_classes(rxcui) for _, rxcui in resolvable),
        return_exceptions=True,
    )

    classes: dict[str, frozenset[str]] = {}

    for (key, _), result in zip(resolvable, raw_results):
        classes[key] = frozenset() if isinstance(result, BaseException) else result

    return classes


def _labels_for_classes(
    class_ids: frozenset[str],
    table: dict[str, tuple[str, ...]],
) -> set[str]:
    """Map a drug's ATC classIds to the risk-category labels (keys of
    `table`) whose prefixes it matches -- see RISK_CLASS_PREFIXES /
    ALLERGY_CLASS_PREFIXES."""
    return {
        label
        for label, prefixes in table.items()
        if any(class_id.startswith(prefix) for class_id in class_ids for prefix in prefixes)
    }


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

    # P4.4: ATC-class labels per drug, so a pair with no exact entry in
    # KNOWN_INTERACTIONS can still be caught at the class level (e.g. any
    # NSAID + any anticoagulant, not just the specific pairs listed there).
    class_map = await _resolve_classes_many(normalized_map, provider)
    class_labels = [
        _labels_for_classes(class_map.get(name.casefold(), frozenset()), RISK_CLASS_PREFIXES)
        for name in cleaned
    ]

    findings: list[dict[str, Any]] = []

    for i, j in combinations(range(len(cleaned)), 2):
        key = frozenset({canonical_keys[i], canonical_keys[j]})

        match = KNOWN_INTERACTIONS.get(key)

        if match is None:
            match = next(
                (
                    CLASS_INTERACTIONS[frozenset({label_a, label_b})]
                    for label_a in class_labels[i]
                    for label_b in class_labels[j]
                    if label_a != label_b and frozenset({label_a, label_b}) in CLASS_INTERACTIONS
                ),
                None,
            )

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
    Run the CLARION medication reconciliation workflow.

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


# ---------------------------------------------------------------------------
# Allergy-conflict check (P4.4) -- used by ai/cds_hint.py's mid-consult
# reference note AND by GET /ai/prescription-screen's pre-save alert
# (routers/ai_router.py).
# ---------------------------------------------------------------------------
# Deliberately synchronous, with its own plain httpx calls (not
# MedicationProvider's async client): cds-hint's `def` route runs Ollama's
# own blocking HTTP call already, so calling this directly is free; the
# prescription-screen `async def` route calls this via
# `starlette.concurrency.run_in_threadpool` instead (same convention as
# every other blocking ai/* call from an async route in this codebase --
# see e.g. routers/consultation.py's voice_to_soap call). Reusing the async
# client's event-loop-bound connection pool from a worker thread would risk
# a cross-event-loop error, so this stays a small, separate, sync-only path.

def _sync_get(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Synchronous GET for the allergy-conflict check's RxNorm/RxClass
    lookups. Never raises -- any failure (network, timeout, bad JSON)
    returns None so the caller degrades to the plain substring check alone,
    same discipline as local_llm.py's `_call_ollama`."""
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=DEFAULT_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "CLARION/1.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def resolve_drug_classes_sync(medication_name: str) -> frozenset[str]:
    """
    Synchronous counterpart to `MedicationProvider.get_drug_classes` --
    resolves a medication name straight to its ATC classIds. Reads/writes
    the exact same cache keys the async path (`resolve_rxcui`/
    `get_drug_classes`) uses -- not just the same dict -- so a drug already
    resolved by `check_interactions` earlier in the same request (see
    `GET /ai/prescription-screen`, which calls both) is a cache hit here
    instead of a second round trip to RxNorm/RxClass for the same name.
    Returns an empty frozenset on any failure or unresolved name; never
    raises.
    """

    name = medication_name.strip()

    if not name:
        return frozenset()

    rxcui_key = ("resolve_rxcui", name.casefold())
    rxcui = _cache_get(rxcui_key)

    if rxcui is _MISS:
        rxcui_data = _sync_get(f"{RXNORM_BASE_URL}/rxcui.json", {"name": name, "search": 1})
        rxnorm_ids = ((rxcui_data or {}).get("idGroup") or {}).get("rxnormId") or []
        rxcui = str(rxnorm_ids[0]) if rxnorm_ids else None
        _cache_put(rxcui_key, rxcui)

    if not rxcui:
        return frozenset()

    classes_key = ("get_drug_classes", rxcui)
    class_ids = _cache_get(classes_key)
    if class_ids is not _MISS:
        return class_ids

    class_data = _sync_get(
        f"{RXCLASS_BASE_URL}/class/byRxcui.json",
        {"rxcui": rxcui, "relaSource": "ATC"},
    )
    items = ((class_data or {}).get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo") or []

    class_ids = frozenset(
        item.get("rxclassMinConceptItem", {}).get("classId")
        for item in items
        if item.get("rxclassMinConceptItem", {}).get("classId")
    )

    _cache_put(classes_key, class_ids)
    return class_ids


def check_allergy_conflicts(allergies: list[dict], active_medications: list[dict]) -> list[str]:
    """
    Flag active medications that may conflict with a recorded allergy.

    Two checks per allergy/medication pair:
    1. Plain, case-insensitive substring match (e.g. a "Penicillin" allergy
       against a "Penicillin"-containing prescription).
    2. ATC drug-class match via RxNorm/RxClass (e.g. a "Penicillin" allergy
       against an "Amoxicillin" prescription -- P4.4's class-aware floor,
       see ALLERGY_CLASS_PREFIXES). Only attempted when check 1 didn't
       already flag the pair, and skipped entirely for an allergy substance
       that matches no known class keyword. Degrades silently to check 1
       alone if RxNorm/RxClass is unreachable (never raises).

    Neither is a full allergist-grade cross-reactivity engine -- see the
    module docstring.
    """

    conflicts: list[str] = []
    resolved_classes: dict[str, frozenset[str]] = {}

    for allergy in allergies:
        substance = (allergy.get("substance") or "").strip().lower()
        if not substance:
            continue

        severity = allergy.get("severity", "unknown")
        class_keys = [key for key in ALLERGY_CLASS_PREFIXES if key in substance]

        for med in active_medications:
            drug_name = (med.get("drug_name") or "").strip()
            if not drug_name:
                continue

            drug_lower = drug_name.lower()

            if substance in drug_lower or drug_lower in substance:
                conflicts.append(
                    f"Active medication '{drug_name}' may relate to recorded "
                    f"allergy '{allergy['substance']}' ({severity} severity)."
                )
                continue

            if not class_keys:
                continue

            if drug_lower not in resolved_classes:
                resolved_classes[drug_lower] = resolve_drug_classes_sync(drug_name)
            drug_classes = resolved_classes[drug_lower]

            prefixes = [prefix for key in class_keys for prefix in ALLERGY_CLASS_PREFIXES[key]]
            if any(class_id.startswith(prefix) for class_id in drug_classes for prefix in prefixes):
                conflicts.append(
                    f"Active medication '{drug_name}' is in the same drug "
                    f"class as recorded allergy '{allergy['substance']}' "
                    f"({severity} severity) -- cross-reactivity risk via "
                    f"RxNorm/RxClass, not a name match."
                )

    return conflicts
