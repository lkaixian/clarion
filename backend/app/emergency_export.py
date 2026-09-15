"""Offline emergency-export appliance (P5.3, tender: two-campus rollout --
`healthcare/On-Prem Architecture.md`'s "nightly encrypted offline
emergency-export appliance (the `critical_for_emergency` subset) for WAN
cuts").

Builds the same critical-for-emergency shape `routers/emergency.py`'s public
QR/NFC scan returns (reuses its `_scoped_fields`/`_resolved_discontinued_ids`
rather than re-deriving that logic) for every patient a facility already has
a relationship to (same scoping helper `patients.py::list_patients` uses) --
this is the FACILITY's own offline safety net for a WAN cut to the central
DB, independent of any individual patient's opt-in EmergencyToken card.

Encryption reuses the exact `age` CLI + recipient/identity convention already
pinned for backups (`backend/backup/lib.sh::maybe_age`) -- one crypto tool
for the whole stack, not two, and the same key-custody model (identity file
lives only on the appliance, never in the central repo).
"""
import json
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .audit import log_access
from .clinical_access import _facility_known_patient_ids_select
from .routers.emergency import _ResponderAudit, _audit_sharing_bypass_if_any, _resolved_discontinued_ids, _scoped_fields

# There is no per-patient consent grant behind this export (unlike the
# QR-card flow's grant.scope) -- it always uses the full vocabulary.
FULL_SCOPE = frozenset({"blood_type", "allergies", "medications", "conditions"})


class UnknownFacilityError(ValueError):
    pass


def build_emergency_export(db: Session, facility_name: str, *, actor: str = "cron:emergency_export_appliance") -> list:
    """Every patient known to `facility_name`, reduced to their
    critical-for-emergency subset, plus a lookup key. Runs on facility-owned
    hardware for facility staff during a WAN cut -- not the unauthenticated
    public scan endpoint, so (unlike that endpoint's Security Audit M7b
    age-only rule) full name and NRIC are included; staff already have the
    patient in front of them.

    Security review 2026-09-15 (P5.3): unlike every other reader of this
    data shape (/emergency/scan, /emergency/nfc/scan, get_patient_full_record,
    list_patients -- all of which call log_access), this bulk export was
    leaving zero audit trail for data that then leaves the network entirely
    as a file. Fixed with one log_access row per export run (fields=None,
    detail carries facility+count -- not a per-patient row; a nightly export
    of an entire facility isn't "N accesses", it's one export event) plus,
    per patient, the SAME cross-hospital-sharing-bypass audit the live scan
    endpoint writes via _audit_sharing_bypass_if_any (this export reads
    patient.conditions/medications/allergies unfiltered by authoring
    facility, same life-safety bypass _scoped_fields's caller in
    routers/emergency.py makes -- it must leave the same reviewable trail).

    Raises UnknownFacilityError if `facility_name` doesn't match a
    registered HospitalSetting row -- same registry
    _audit_sharing_bypass_if_any already trusts, and cheap insurance against
    a typo'd --facility silently producing an empty (or on a near-miss
    string, wrong) export. This is NOT an RBAC check (the CLI is
    operator-trusted, same model as every other backend/db/*.py maintenance
    script -- retention_scan.py, security_analytics_scan.py, etc.) --
    the log_access row above is what makes running it accountable."""
    if not db.query(models.HospitalSetting.facility_name).filter(
        models.HospitalSetting.facility_name == facility_name
    ).first():
        raise UnknownFacilityError(f"no HospitalSetting registered for facility {facility_name!r}")

    known = _facility_known_patient_ids_select(facility_name)
    patients = (
        db.query(models.Patient)
        .filter(models.Patient.id.in_(select(known.c.patient_id)))
        .order_by(models.Patient.full_name)
        .all()
    )
    ident = _ResponderAudit(actor=actor, actor_role="system", actor_facility=facility_name, detail_suffix="")
    out = []
    for patient in patients:
        resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, patient.id)
        fields = _scoped_fields(patient, FULL_SCOPE, resolved_cond_ids, discontinued_med_ids)
        fields["patient_id"] = patient.id
        fields["national_id"] = patient.normalized_national_id
        out.append(fields)
        _audit_sharing_bypass_if_any(db, patient, ident)

    log_access(
        db, None,
        actor=actor, actor_role="system",
        action="emergency_export_build",
        detail=f"facility={facility_name} count={len(out)}",
        actor_facility=facility_name,
    )
    return out


def encrypt_export(payload: list, recipients: list) -> bytes:
    """age-encrypt the JSON export for `recipients` (age public keys) --
    same flag shape as `backend/backup/lib.sh::maybe_age`. Requires `age`
    on PATH; raises CalledProcessError if it isn't (fail loud, never write
    an unencrypted export to the appliance)."""
    if not recipients:
        raise ValueError("encrypt_export requires at least one age recipient")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    args = ["age"]
    for r in recipients:
        args += ["-r", r]
    proc = subprocess.run(args, input=data, capture_output=True, check=True)
    return proc.stdout


def decrypt_export(blob: bytes, identity_file: str) -> list:
    """Inverse of encrypt_export -- run ON THE APPLIANCE during a WAN cut,
    with the age private-key file that never leaves it (same key-custody
    model as `backend/backup/restore-test.sh`'s AGE_IDENTITY)."""
    proc = subprocess.run(
        ["age", "-d", "-i", identity_file], input=blob, capture_output=True, check=True
    )
    return json.loads(proc.stdout.decode("utf-8"))
