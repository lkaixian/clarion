"""P5.3 offline emergency-export appliance: build_emergency_export must be
facility-scoped (same rule as list_patients, Security Audit H2), only ever
surface critical-for-emergency items (same rule the public /emergency/scan
endpoint already enforces via _scoped_fields), refuse an unregistered
facility, and (security review 2026-09-15) leave an audit trail -- this
bulk export otherwise had zero rows in audit_logs despite the data leaving
the network entirely as a file."""
import shutil

import pytest

from app import models
from app.emergency_export import (
    UnknownFacilityError,
    build_emergency_export,
    decrypt_export,
    encrypt_export,
)


def _make_patient(db_session, **overrides):
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Test Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _give_encounter_at(db_session, patient, facility_name: str):
    db_session.add(models.Encounter(
        patient_id=patient.id, facility_name=facility_name, encounter_type="outpatient",
    ))
    db_session.commit()


def _register_facility(db_session, facility_name: str):
    db_session.add(models.HospitalSetting(facility_name=facility_name))
    db_session.commit()


def test_export_is_facility_scoped_and_critical_only(db_session):
    _register_facility(db_session, "University Branch")
    known = _make_patient(db_session, full_name="Known To Branch", national_id="900101011234")
    _give_encounter_at(db_session, known, "University Branch")
    elsewhere = _make_patient(db_session, full_name="Only At Main Campus")
    _give_encounter_at(db_session, elsewhere, "Main Campus")

    db_session.add_all([
        models.AllergyIntolerance(patient_id=known.id, substance="Penicillin", severity="severe",
                                   critical_for_emergency=True),
        models.AllergyIntolerance(patient_id=known.id, substance="Pollen", severity="mild",
                                   critical_for_emergency=False),
    ])
    db_session.commit()

    export = build_emergency_export(db_session, "University Branch")

    names = {p["full_name"] for p in export}
    assert "Known To Branch" in names
    assert "Only At Main Campus" not in names  # facility-scoped, not global

    row = next(p for p in export if p["full_name"] == "Known To Branch")
    assert row["national_id"] == known.normalized_national_id
    assert row["allergies"] == [{"substance": "Penicillin", "severity": "severe", "reaction": None}]
    assert row["omitted_non_critical"] == {"allergies": 1}  # the mild one is on file but withheld

    # Security review finding 1: this bulk export must show up in audit_logs.
    log = (
        db_session.query(models.AuditLog)
        .filter(models.AuditLog.action == "emergency_export_build")
        .order_by(models.AuditLog.timestamp.desc())
        .first()
    )
    assert log is not None
    assert log.actor_facility == "University Branch"
    assert "count=1" in log.detail


def test_unregistered_facility_is_refused(db_session):
    with pytest.raises(UnknownFacilityError):
        build_emergency_export(db_session, "Not A Real Facility")


@pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age/age-keygen CLI not installed on this machine",
)
def test_encrypt_decrypt_roundtrip():
    """Generates a real throwaway keypair at test time rather than
    hardcoding one -- age-keygen prints `# public key: age1...` plus the
    AGE-SECRET-KEY-1... identity line, all to stdout."""
    import os
    import subprocess
    import tempfile

    keygen = subprocess.run(["age-keygen"], capture_output=True, check=True, text=True)
    lines = keygen.stdout.splitlines()
    pubkey = next(l.split(": ", 1)[1] for l in lines if l.startswith("# public key:"))
    identity = next(l for l in lines if l.startswith("AGE-SECRET-KEY"))

    payload = [{"full_name": "Roundtrip Test", "national_id": "1"}]
    blob = encrypt_export(payload, [pubkey])
    assert isinstance(blob, bytes) and blob  # opaque ciphertext, not the plaintext JSON

    fd, path = tempfile.mkstemp()
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(identity)
        assert decrypt_export(blob, path) == payload
    finally:
        os.remove(path)
