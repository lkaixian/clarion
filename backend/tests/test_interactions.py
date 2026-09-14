"""P4.4: the ATC-class layer on top of interactions.py's named-
pair DDI table and cds_hint.py's plain-name allergy check, plus the pre-save
`GET /ai/prescription-screen/{patient_id}` endpoint. RxNorm/RxClass calls are
monkeypatched throughout -- these tests must not depend on live network
access.
"""
import asyncio

from app import models
from app.ai import interactions
from conftest import _facility, _make_patient

# A small fake RxNorm/RxClass world covering exactly the drugs used below.
# Real ATC classIds (verified live against RxClass before P4.4 landed --
# see interactions.py's RISK_CLASS_PREFIXES/ALLERGY_CLASS_PREFIXES).
_FAKE_RXCUI = {
    "warfarin": "11289",
    "aspirin": "1191",
    "naproxen": "7258",
    "clopidogrel": "236991",
    "amoxicillin": "133008",
    "paracetamol": "161",
}
_FAKE_NAME = {rxcui: name for name, rxcui in _FAKE_RXCUI.items()}
_FAKE_CLASSES = {
    "11289": frozenset({"B01AA"}),   # warfarin -- vitamin K antagonist
    "1191": frozenset({"B01AC"}),    # aspirin -- platelet aggregation inhibitor
    "7258": frozenset({"M01AE"}),    # naproxen -- NSAID
    "236991": frozenset({"B01AC"}),  # clopidogrel -- platelet aggregation inhibitor
    "133008": frozenset({"J01CA"}),  # amoxicillin -- penicillin
    "161": frozenset(),              # paracetamol -- no relevant class
}


async def _fake_resolve_rxcui(self, medication_name):
    return _FAKE_RXCUI.get(medication_name.strip().lower())


async def _fake_get_rxcui_name(self, rxcui):
    return _FAKE_NAME.get(rxcui)


async def _fake_get_drug_classes(self, rxcui):
    return _FAKE_CLASSES.get(rxcui, frozenset())


def _patch_provider(monkeypatch):
    monkeypatch.setattr(interactions.MedicationProvider, "resolve_rxcui", _fake_resolve_rxcui)
    monkeypatch.setattr(interactions.MedicationProvider, "get_rxcui_name", _fake_get_rxcui_name)
    monkeypatch.setattr(interactions.MedicationProvider, "get_drug_classes", _fake_get_drug_classes)


async def _fake_provider_get(self, url, *, params=None):
    """Fakes MedicationProvider._get itself (the lowest-level HTTP call),
    unlike `_patch_provider` above which replaces the higher-level methods
    wholesale -- this lets resolve_rxcui/get_rxcui_name/get_drug_classes run
    for real, including their own `_cache_put` calls, so a cache-sharing
    test can check the real cache instead of a bypassed one."""
    params = params or {}
    if url == f"{interactions.RXNORM_BASE_URL}/rxcui.json":
        rxcui = _FAKE_RXCUI.get(params.get("name", "").strip().lower())
        return {"idGroup": {"rxnormId": [rxcui] if rxcui else []}}
    if url.startswith(f"{interactions.RXNORM_BASE_URL}/rxcui/") and url.endswith("/properties.json"):
        rxcui = url.rsplit("/", 2)[-2]
        return {"properties": {"name": _FAKE_NAME.get(rxcui, "")}}
    if url == f"{interactions.RXCLASS_BASE_URL}/class/byRxcui.json":
        class_ids = _FAKE_CLASSES.get(params.get("rxcui"), frozenset())
        return {"rxclassDrugInfoList": {"rxclassDrugInfo": [
            {"rxclassMinConceptItem": {"classId": cid}} for cid in class_ids
        ]}}
    raise AssertionError(f"unexpected URL in test: {url}")


def test_named_pair_interaction_still_matches(monkeypatch):
    """Existing KNOWN_INTERACTIONS behavior is unaffected by the new class
    layer -- the named entry is found first and the class engine never runs
    for this pair."""
    _patch_provider(monkeypatch)
    findings = asyncio.run(interactions.check_interactions(["warfarin", "aspirin"]))
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_class_level_pair_not_in_named_table_is_caught(monkeypatch):
    """naproxen (NSAID) + clopidogrel (antiplatelet) has no entry in
    KNOWN_INTERACTIONS, but both classes are in CLASS_INTERACTIONS -- this is
    the actual P4.4 upgrade over pure name matching."""
    _patch_provider(monkeypatch)
    findings = asyncio.run(interactions.check_interactions(["naproxen", "clopidogrel"]))
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert "class" in findings[0]["explanation"].lower()


def test_unrelated_classes_produce_no_finding(monkeypatch):
    _patch_provider(monkeypatch)
    findings = asyncio.run(interactions.check_interactions(["amoxicillin", "paracetamol"]))
    assert findings == []


def test_allergy_conflict_substring_match_unchanged():
    conflicts = interactions.check_allergy_conflicts(
        [{"substance": "Penicillin", "severity": "severe"}],
        [{"drug_name": "Penicillin V", "active": True}],
    )
    assert len(conflicts) == 1
    assert "Penicillin" in conflicts[0]


def test_allergy_conflict_class_match_catches_amoxicillin(monkeypatch):
    """The gap ai/cds_hint.py used to flag as a known limitation: a
    'Penicillin' allergy against an 'Amoxicillin' prescription doesn't
    substring-match, but does share the penicillin ATC class."""
    monkeypatch.setattr(
        interactions, "resolve_drug_classes_sync",
        lambda name: frozenset({"J01CA"}) if name == "Amoxicillin" else frozenset(),
    )
    conflicts = interactions.check_allergy_conflicts(
        [{"substance": "Penicillin", "severity": "severe"}],
        [{"drug_name": "Amoxicillin", "active": True}],
    )
    assert len(conflicts) == 1
    assert "cross-reactivity" in conflicts[0]


def test_sync_class_resolution_reuses_async_paths_cache(monkeypatch):
    """resolve_drug_classes_sync must read/write the SAME cache keys
    resolve_rxcui/get_drug_classes use, not a separate namespace -- so a
    drug check_interactions already resolved earlier in the same request
    (see GET /ai/prescription-screen, which calls both) isn't looked up
    again via a second RxNorm/RxClass round trip for the allergy check."""
    monkeypatch.setattr(interactions, "_response_cache", {})
    monkeypatch.setattr(interactions.MedicationProvider, "_get", _fake_provider_get)

    asyncio.run(interactions.check_interactions(["amoxicillin", "warfarin"]))

    def _boom(*a, **kw):
        raise AssertionError("resolve_drug_classes_sync made an HTTP call instead of using the cache")
    monkeypatch.setattr(interactions, "_sync_get", _boom)

    assert interactions.resolve_drug_classes_sync("amoxicillin") == frozenset({"J01CA"})


def test_allergy_conflict_degrades_silently_when_rxclass_unreachable(monkeypatch):
    """Never raises, never blocks the consultation screen -- a network
    hiccup just means no class-based flag."""
    monkeypatch.setattr(interactions, "resolve_drug_classes_sync", lambda name: frozenset())
    conflicts = interactions.check_allergy_conflicts(
        [{"substance": "Penicillin", "severity": "severe"}],
        [{"drug_name": "Amoxicillin", "active": True}],
    )
    assert conflicts == []


def test_prescription_screen_endpoint_flags_new_allergy_and_interaction(
    db_session, test_client, make_user, auth_headers, monkeypatch,
):
    """GET /ai/prescription-screen/{patient_id} -- the pre-save, real-time
    check the Add Medication form calls before it lets the clinician
    confirm."""
    _patch_provider(monkeypatch)
    monkeypatch.setattr(
        interactions, "resolve_drug_classes_sync",
        lambda name: frozenset({"J01CA"}) if name == "Amoxicillin" else frozenset(),
    )

    facility = _facility("RX")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    db_session.add(models.AllergyIntolerance(patient_id=patient.id, substance="Penicillin", severity="severe"))
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="warfarin", active=True))
    db_session.commit()

    resp = test_client.get(
        f"/ai/prescription-screen/{patient.id}",
        headers=auth_headers(clinician),
        params={"drug_name": "Amoxicillin"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Amoxicillin has no rule against warfarin -- no drug_interactions here,
    # only the allergy cross-reactivity flag.
    assert body["drug_interactions"] == []
    assert len(body["allergy_conflicts"]) == 1
    assert "Amoxicillin" in body["allergy_conflicts"][0]


def test_prescription_screen_only_reports_pairs_involving_the_candidate(
    db_session, test_client, make_user, auth_headers, monkeypatch,
):
    """A pre-existing interaction among the patient's current active
    medications (not involving the drug about to be added) belongs to the
    Interaction Check panel, not this pre-save alert -- it must not be
    repeated here."""
    _patch_provider(monkeypatch)

    facility = _facility("RX")
    clinician = make_user(role="clinician", facility=facility)
    patient = _make_patient(db_session)
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="warfarin", active=True))
    db_session.add(models.MedicationStatement(patient_id=patient.id, drug_name="aspirin", active=True))
    db_session.commit()

    resp = test_client.get(
        f"/ai/prescription-screen/{patient.id}",
        headers=auth_headers(clinician),
        params={"drug_name": "paracetamol"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["drug_interactions"] == []
    assert body["allergy_conflicts"] == []
