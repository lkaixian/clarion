"""
Clinical Summarisation Agent.

Two modes:
1. Local-LLM mode (default, on-prem -- P4.3, the tender): asks
   the local Ollama server (see ai/local_llm.py) to generate a natural
   handover brief from the structured record. Nothing leaves the machine.
2. Deterministic fallback (used automatically if Ollama isn't running/the
   model isn't pulled): builds a clean, readable summary directly from the
   structured FHIR-lite data. This is what runs out-of-the-box on a demo
   laptop with no GPU/Ollama configured yet -- fully reliable, no external
   service needed.
"""
from .local_llm import generate_text


def _fallback_summary(patient: dict) -> str:
    lines = [f"Patient: {patient['full_name']} (DOB: {patient['date_of_birth']})"]

    if patient.get("blood_type"):
        lines.append(f"Blood type: {patient['blood_type']}")

    active_conditions = [c["name"] for c in patient.get("conditions", []) if c.get("status") == "active"]
    if active_conditions:
        lines.append("Active conditions: " + ", ".join(active_conditions))

    chronic = [c["name"] for c in patient.get("conditions", []) if c.get("is_chronic")]
    if chronic:
        lines.append("Chronic conditions requiring ongoing management: " + ", ".join(chronic))

    active_meds = [m["drug_name"] for m in patient.get("medications", []) if m.get("active")]
    if active_meds:
        lines.append("Current medications: " + ", ".join(active_meds))

    allergies = [f"{a['substance']} ({a.get('severity', 'unknown')})" for a in patient.get("allergies", [])]
    if allergies:
        lines.append("Known allergies: " + ", ".join(allergies))
    else:
        lines.append("No known allergies on record.")

    encounters = patient.get("encounters", [])
    if encounters:
        recent = sorted(encounters, key=lambda e: e.get("started_at", ""), reverse=True)[:3]
        lines.append("Recent visits: " + "; ".join(
            f"{e['facility_name']} ({e['encounter_type']})" for e in recent
        ))

    return "\n".join(lines)


def generate_handover_brief(patient: dict) -> str:
    prompt = (
        "You are a clinical handover assistant. Given this structured "
        "patient record (JSON), write a concise 4-6 sentence handover "
        "brief for a clinician meeting this patient for the first time. "
        "Plain clinical language, no speculation beyond the data given.\n\n"
        f"{patient}"
    )
    return generate_text(prompt, max_tokens=400) or _fallback_summary(patient)
