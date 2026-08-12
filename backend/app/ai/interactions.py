"""
Medication Interaction Checker (rule-based demo version).

A real product would call a licensed drug-interaction database (e.g. First
Databank, Micromedex) or an API such as the NIH's RxNav/RxNorm interaction
API. Those need commercial/API accounts, so this ships a small, clearly
labelled reference table covering common, high-teaching-value interactions
— enough to demo the *mechanism* (cross-facility prescriptions colliding)
convincingly. Swap KNOWN_INTERACTIONS for a real API call in Week 3 if time
allows; the function signature won't need to change.
"""
from itertools import combinations

# (drug_a, drug_b) -> (severity, explanation) -- case-insensitive, order-independent
KNOWN_INTERACTIONS = {
    frozenset({"warfarin", "aspirin"}): ("high", "Increased bleeding risk when anticoagulants are combined."),
    frozenset({"warfarin", "ibuprofen"}): ("high", "NSAIDs increase bleeding risk with anticoagulants."),
    frozenset({"metformin", "contrast dye"}): ("moderate", "Risk of lactic acidosis; often held around imaging procedures."),
    frozenset({"simvastatin", "clarithromycin"}): ("high", "Increased risk of statin-induced muscle toxicity."),
    frozenset({"lisinopril", "spironolactone"}): ("moderate", "Combined use raises risk of hyperkalaemia."),
    frozenset({"sildenafil", "nitroglycerin"}): ("high", "Severe, potentially fatal hypotension when combined."),
}


def check_interactions(drug_names: list[str]) -> list[dict]:
    normalized = [d.strip().lower() for d in drug_names if d.strip()]
    findings = []
    for a, b in combinations(normalized, 2):
        key = frozenset({a, b})
        if key in KNOWN_INTERACTIONS:
            severity, explanation = KNOWN_INTERACTIONS[key]
            findings.append({
                "drug_a": a, "drug_b": b,
                "severity": severity, "explanation": explanation,
            })
    return findings


def check_duplicate_prescriptions(medications: list[dict]) -> list[str]:
    """Flags the same active ingredient prescribed by more than one facility —
    the classic cross-hospital blind-spot this project exists to catch."""
    seen = {}
    duplicates = []
    for med in medications:
        if not med.get("active"):
            continue
        name = med["drug_name"].strip().lower()
        facility = med.get("prescribed_by_facility", "unknown")
        if name in seen and seen[name] != facility:
            duplicates.append(
                f"{med['drug_name']} prescribed by both {seen[name]} and {facility}"
            )
        seen[name] = facility
    return duplicates
