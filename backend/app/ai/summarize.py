"""
Clinical Summarisation Agent.

Two modes:
1. LLM mode (recommended once you have an API key): set ANTHROPIC_API_KEY
   in your environment and this will call Claude to generate a natural
   handover brief from the structured record.
2. Deterministic fallback (default, no key required): builds a clean,
   readable summary directly from the structured FHIR-lite data. This is
   what will run out-of-the-box for your demo and judging — it is fully
   reliable and needs no external service, which matters if Wi-Fi at the
   symposium venue is unreliable.
"""
import os
from typing import Optional


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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_summary(patient)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are a clinical handover assistant. Given this structured "
            "patient record (JSON), write a concise 4-6 sentence handover "
            "brief for a clinician meeting this patient for the first time. "
            "Plain clinical language, no speculation beyond the data given.\n\n"
            f"{patient}"
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception:
        # Never let a network/API hiccup break the demo — fall back silently.
        return _fallback_summary(patient)
