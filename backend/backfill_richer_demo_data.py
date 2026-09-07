"""
One-off, idempotent backfill for the richer demo-patient data added to
seed.py (more interaction pairs + a real cross-facility duplicate for the
Medication Interaction Check demo), PLUS the facility-scoped admin-console
demo data (admin's own `facility`, medicine inventory, wards) added
alongside the `admin` role's new "manager admin, not super admin" scoping
(see routers/admin.py).

seed.py itself won't re-apply these rows to an already-seeded clarion.db
(it's guarded by "does admin@clarion.demo already exist?" and no-ops if
so) -- this script instead finds the existing demo patient by NRIC and the
existing demo admin by email, and adds only the specific rows/fields that
are missing, leaving all other data (passwords, audit logs, emergency
cards, uploaded documents, etc.) untouched.

Safe to run multiple times -- each row is only inserted if an equivalent
one doesn't already exist; the admin's facility is only set if currently
NULL (never overwrites a facility an operator has since changed by hand).

Run once: python backfill_richer_demo_data.py
"""
from datetime import datetime, timedelta

from app.database import SessionLocal, engine, Base
from app import models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

patient = (
    db.query(models.Patient)
    .filter(models.Patient.national_id == "520314-01-1234")
    .first()
)

if not patient:
    print("Demo patient (NRIC 520314-01-1234) not found -- nothing to backfill. "
          "Run seed.py first if you haven't yet.")
    db.close()
    raise SystemExit(0)


def _has_condition(name: str) -> bool:
    return (
        db.query(models.Condition)
        .filter(models.Condition.patient_id == patient.id, models.Condition.name == name)
        .first()
        is not None
    )


def _has_medication(drug_name: str, facility: str) -> bool:
    return (
        db.query(models.MedicationStatement)
        .filter(
            models.MedicationStatement.patient_id == patient.id,
            models.MedicationStatement.drug_name == drug_name,
            models.MedicationStatement.prescribed_by_facility == facility,
        )
        .first()
        is not None
    )


def _has_encounter(facility: str, reason: str) -> bool:
    return (
        db.query(models.Encounter)
        .filter(
            models.Encounter.patient_id == patient.id,
            models.Encounter.facility_name == facility,
            models.Encounter.reason == reason,
        )
        .first()
        is not None
    )


added = []

if not _has_condition("Atrial Fibrillation"):
    db.add(models.Condition(
        patient_id=patient.id, name="Atrial Fibrillation", status="active",
        is_chronic=True, critical_for_emergency=True,
    ))
    added.append("Condition: Atrial Fibrillation")

if not _has_condition("Hyperlipidemia"):
    # critical_for_emergency=True to match seed.py's corrected default (see
    # its comment) -- kept in sync so a fresh backfill run never reintroduces
    # the inconsistency this block's guard below is fixing for existing DBs.
    db.add(models.Condition(
        patient_id=patient.id, name="Hyperlipidemia", status="active",
        is_chronic=True, critical_for_emergency=True,
    ))
    added.append("Condition: Hyperlipidemia")
else:
    # One-off fix for clarion.db files seeded by an earlier version of
    # this script, which set critical_for_emergency=False here (an
    # inconsistency with seed.py's own default -- see above). Idempotent:
    # only writes/commits if the stale value is actually found, so re-running
    # this script is always safe.
    stale = (
        db.query(models.Condition)
        .filter(
            models.Condition.patient_id == patient.id,
            models.Condition.name == "Hyperlipidemia",
            models.Condition.critical_for_emergency.is_(False),
        )
        .first()
    )
    if stale:
        stale.critical_for_emergency = True
        db.add(stale)
        added.append("Fixed: Hyperlipidemia critical_for_emergency False -> True")

# Second Metformin prescription at a different facility -- the
# cross-facility duplicate for check_duplicate_prescriptions to catch.
if not _has_medication("Metformin", "Hospital Sejahtera"):
    db.add(models.MedicationStatement(
        patient_id=patient.id, drug_name="Metformin", dosage="500mg",
        frequency="twice daily", prescribed_by_facility="Hospital Sejahtera",
        active=True, critical_for_emergency=True,
    ))
    added.append("Medication: Metformin @ Hospital Sejahtera (duplicate demo)")

if not _has_medication("Simvastatin", "Hospital Sejahtera"):
    db.add(models.MedicationStatement(
        patient_id=patient.id, drug_name="Simvastatin", dosage="20mg",
        frequency="once daily at night", prescribed_by_facility="Hospital Sejahtera",
        active=True, critical_for_emergency=False,
    ))
    added.append("Medication: Simvastatin @ Hospital Sejahtera")

if not _has_medication("Clarithromycin", "Private Clinic Damansara"):
    db.add(models.MedicationStatement(
        patient_id=patient.id, drug_name="Clarithromycin", dosage="500mg",
        frequency="twice daily", prescribed_by_facility="Private Clinic Damansara",
        active=True, critical_for_emergency=False,
    ))
    added.append("Medication: Clarithromycin @ Private Clinic Damansara (Simvastatin interaction demo)")

if not _has_encounter("Private Clinic Damansara", "Respiratory infection"):
    db.add(models.Encounter(
        patient_id=patient.id, facility_name="Private Clinic Damansara",
        encounter_type="outpatient", reason="Respiratory infection",
    ))
    added.append("Encounter: Respiratory infection @ Private Clinic Damansara")

if added:
    db.commit()
    print(f"Backfilled {len(added)} row(s) onto patient {patient.id}:")
    for line in added:
        print(f"  - {line}")
    print(
        "\nMedication Interaction Check should now surface 2 interaction "
        "pairs (Warfarin+Aspirin, Simvastatin+Clarithromycin) and 1 "
        "cross-facility duplicate (Metformin)."
    )
else:
    print("All patient-record rows already present -- nothing to backfill there.")


# ---------- Admin-console demo data (facility scoping + inventory/wards) ----------
# Separate guard set, keyed off the demo admin account rather than the demo
# patient -- these two backfills are independent (an operator could in
# theory already have inventory/ward rows without ever having the interaction
# demo gaps above, or vice versa), so each half no-ops independently.
admin_user = (
    db.query(models.User)
    .filter(models.User.email == "admin@clarion.demo")
    .first()
)

admin_added = []

if admin_user is not None and not admin_user.facility:
    # Only ever sets facility when it's currently NULL -- never overwrites a
    # value an operator has since changed by hand. See routers/admin.py's
    # module docstring for why an admin with facility=None would otherwise
    # see empty lists on every new /admin/* endpoint.
    admin_user.facility = "Hospital Sejahtera"
    db.add(admin_user)
    admin_added.append("Set admin@clarion.demo facility -> Hospital Sejahtera")


def _has_inventory_item(drug_name: str, facility: str) -> bool:
    return (
        db.query(models.MedicineInventoryItem)
        .filter(
            models.MedicineInventoryItem.facility_name == facility,
            models.MedicineInventoryItem.drug_name == drug_name,
        )
        .first()
        is not None
    )


def _has_ward(ward_name: str, facility: str) -> bool:
    return (
        db.query(models.Ward)
        .filter(models.Ward.facility_name == facility, models.Ward.ward_name == ward_name)
        .first()
        is not None
    )


_now = datetime.utcnow()
_HOSPITAL = "Hospital Sejahtera"

_inventory_seed = [
    # (drug_name, quantity_on_hand, unit, reorder_threshold, notes, days_since_restock)
    ("Insulin Glargine (Lantus)", 8, "vials", 20,
     "Cold-chain item — check fridge stock physically, not just this count.", 18),
    ("Amoxicillin 500mg", 15, "boxes", 25, None, 40),
    ("Paracetamol 500mg", 1200, "tablets", 300, None, 5),
    ("Metformin 500mg", 600, "tablets", 150, None, 10),
    ("Saline Solution 0.9% 500ml", 340, "bottles", None, None, 2),
]
for drug_name, qty, unit, threshold, notes, days_ago in _inventory_seed:
    if not _has_inventory_item(drug_name, _HOSPITAL):
        db.add(models.MedicineInventoryItem(
            facility_name=_HOSPITAL, drug_name=drug_name, quantity_on_hand=qty,
            unit=unit, reorder_threshold=threshold, notes=notes,
            last_restocked_at=_now - timedelta(days=days_ago),
        ))
        admin_added.append(f"Inventory: {drug_name} @ {_HOSPITAL}")

_ward_seed = [
    # (ward_name, ward_type, total_beds, occupied_beds)
    ("ICU", "icu", 10, 9),                       # near-full -- capacity-pressure demo
    ("General Ward A", "general", 40, 22),        # comfortably available
    ("Maternity Wing (New)", "maternity", 15, 0),  # empty/new
]
for ward_name, ward_type, total_beds, occupied_beds in _ward_seed:
    if not _has_ward(ward_name, _HOSPITAL):
        db.add(models.Ward(
            facility_name=_HOSPITAL, ward_name=ward_name, ward_type=ward_type,
            total_beds=total_beds, occupied_beds=occupied_beds,
        ))
        admin_added.append(f"Ward: {ward_name} @ {_HOSPITAL}")

if admin_added:
    db.commit()
    print(f"\nBackfilled {len(admin_added)} admin-console row(s)/field(s):")
    for line in admin_added:
        print(f"  - {line}")
else:
    print("All admin-console rows/fields already present -- nothing to backfill there.")

db.close()
