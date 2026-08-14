"""
Run once after first setup: python seed.py
Creates a demo admin, a demo clinician, and one synthetic patient with a
realistic multi-facility history — enough to demo every pillar end to end.
"""
from datetime import datetime, timedelta

from app.database import SessionLocal, engine, Base
from app import models, auth

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if not db.query(models.User).filter(models.User.email == "admin@medibridge.demo").first():
    admin = models.User(
        email="admin@medibridge.demo", hashed_password=auth.hash_password("admin123"),
        full_name="Demo Admin", role="admin",
        # The `admin` role is facility-scoped ("manager admin, not super
        # admin" -- see routers/admin.py's module docstring): every
        # inventory/ward/appointments-dashboard endpoint filters to this
        # exact facility string. Matches the seeded clinician's facility so
        # the demo hospital is coherent (an admin with no facility would see
        # empty lists everywhere on first login -- a bad first-look demo).
        facility="Hospital Sejahtera",
    )
    clinician = models.User(
        email="clinician@medibridge.demo", hashed_password=auth.hash_password("clinician123"),
        full_name="Dr. Aisyah Rahman", role="clinician", facility="Hospital Sejahtera",
    )
    db.add_all([admin, clinician])
    db.commit()

    patient = models.Patient(
        full_name="Ahmad bin Ismail", date_of_birth="1952-03-14", gender="male",
        national_id="520314-01-1234", blood_type="O+", phone="+60123456789",
        senior_citizen_mode=True,
    )
    db.add(patient)
    db.commit()

    patient_user = models.User(
        email="patient@medibridge.demo", hashed_password=auth.hash_password("patient123"),
        full_name="Ahmad bin Ismail", role="patient", patient_id=patient.id,
    )
    db.add(patient_user)

    db.add_all([
        models.Condition(patient_id=patient.id, name="Type 2 Diabetes", status="active", is_chronic=True, critical_for_emergency=True),
        models.Condition(patient_id=patient.id, name="Hypertension", status="active", is_chronic=True, critical_for_emergency=True),
        # Justifies Warfarin below -- 74yo with AFib is a realistic reason to
        # be anticoagulated (and is exactly the kind of patient where a
        # second facility unknowingly adding Aspirin is dangerous).
        models.Condition(patient_id=patient.id, name="Atrial Fibrillation", status="active", is_chronic=True, critical_for_emergency=True),
        # Justifies Simvastatin below. critical_for_emergency=True matches the
        # web "Add Condition" form's own default for this checkbox -- the
        # demo patient's data should follow the same default a real clinician
        # would get, not a special-cased exception (a Hyperlipidemia dx is a
        # legitimate thing a first responder should see, e.g. it's why
        # they're on Simvastatin -- there's no good reason to have hidden it
        # from the emergency scan).
        models.Condition(patient_id=patient.id, name="Hyperlipidemia", status="active", is_chronic=True, critical_for_emergency=True),

        # Deliberately spread across three facilities and sized/varied
        # enough to demo BOTH pillars of the Medication Interaction Check in
        # one click, not just one lucky pairwise match:
        #   - interactions: Warfarin+Aspirin AND Simvastatin+Clarithromycin
        #     both match backend/app/ai/interactions.py::KNOWN_INTERACTIONS.
        #   - cross-facility duplicate: Metformin is (realistically, and
        #     probably unknowingly) prescribed by BOTH the outpatient clinic
        #     and the hospital -- the exact cross-hospital blind spot this
        #     project exists to catch.
        models.MedicationStatement(patient_id=patient.id, drug_name="Metformin", dosage="500mg", frequency="twice daily", prescribed_by_facility="Klinik Kesihatan Bandar", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Metformin", dosage="500mg", frequency="twice daily", prescribed_by_facility="Hospital Sejahtera", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Warfarin", dosage="5mg", frequency="once daily", prescribed_by_facility="Hospital Sejahtera", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Aspirin", dosage="75mg", frequency="once daily", prescribed_by_facility="Private Clinic Damansara", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Simvastatin", dosage="20mg", frequency="once daily at night", prescribed_by_facility="Hospital Sejahtera", active=True, critical_for_emergency=False),
        # A short-course antibiotic left marked active=True for demo
        # purposes (see KNOWN_INTERACTIONS check filters on `active`) --
        # in reality this would usually be time-limited/resolved, but the
        # point being demoed is the interaction, not the prescription's
        # own lifecycle.
        models.MedicationStatement(patient_id=patient.id, drug_name="Clarithromycin", dosage="500mg", frequency="twice daily", prescribed_by_facility="Private Clinic Damansara", active=True, critical_for_emergency=False),
        models.AllergyIntolerance(patient_id=patient.id, substance="Penicillin", reaction="Anaphylaxis", severity="severe", critical_for_emergency=True),
        models.Encounter(patient_id=patient.id, facility_name="Klinik Kesihatan Bandar", encounter_type="outpatient", reason="Routine diabetes checkup"),
        models.Encounter(patient_id=patient.id, facility_name="Hospital Sejahtera", encounter_type="inpatient", reason="Chest pain investigation"),
        models.Encounter(patient_id=patient.id, facility_name="Private Clinic Damansara", encounter_type="outpatient", reason="Respiratory infection"),
    ])
    db.commit()

    # Admin-console demo data (GET/POST/PATCH /admin/inventory, /admin/wards
    # -- see routers/admin.py). All facility_name="Hospital Sejahtera" so it
    # shows up for the seeded admin above; varied enough to demo both the
    # low-stock indicator and a capacity-pressure indicator on first login.
    now = datetime.utcnow()
    db.add_all([
        # Clearly LOW relative to its threshold -- demos the is_low_stock
        # computed flag without needing any manual data entry first.
        models.MedicineInventoryItem(
            facility_name="Hospital Sejahtera", drug_name="Insulin Glargine (Lantus)",
            quantity_on_hand=8, unit="vials", reorder_threshold=20,
            notes="Cold-chain item — check fridge stock physically, not just this count.",
            last_restocked_at=now - timedelta(days=18),
        ),
        # Also low, different unit ("boxes") so the demo isn't monotonous.
        models.MedicineInventoryItem(
            facility_name="Hospital Sejahtera", drug_name="Amoxicillin 500mg",
            quantity_on_hand=15, unit="boxes", reorder_threshold=25,
            last_restocked_at=now - timedelta(days=40),
        ),
        # Healthy stock, no low-stock flag expected.
        models.MedicineInventoryItem(
            facility_name="Hospital Sejahtera", drug_name="Paracetamol 500mg",
            quantity_on_hand=1200, unit="tablets", reorder_threshold=300,
            last_restocked_at=now - timedelta(days=5),
        ),
        models.MedicineInventoryItem(
            facility_name="Hospital Sejahtera", drug_name="Metformin 500mg",
            quantity_on_hand=600, unit="tablets", reorder_threshold=150,
            last_restocked_at=now - timedelta(days=10),
        ),
        # reorder_threshold=None -- deliberately demonstrates the "no
        # low-stock tracking for this item" case (e.g. a cheap, bulky
        # consumable nobody bothers reorder-alerting on).
        models.MedicineInventoryItem(
            facility_name="Hospital Sejahtera", drug_name="Saline Solution 0.9% 500ml",
            quantity_on_hand=340, unit="bottles", reorder_threshold=None,
            last_restocked_at=now - timedelta(days=2),
        ),
    ])
    db.add_all([
        # Near-full -- demos a capacity-pressure indicator (occupancy_pct
        # close to 100%).
        models.Ward(
            facility_name="Hospital Sejahtera", ward_name="ICU", ward_type="icu",
            total_beds=10, occupied_beds=9,
        ),
        # Comfortably available.
        models.Ward(
            facility_name="Hospital Sejahtera", ward_name="General Ward A", ward_type="general",
            total_beds=40, occupied_beds=22,
        ),
        # Empty/new -- a ward that's just come online, nobody admitted yet.
        models.Ward(
            facility_name="Hospital Sejahtera", ward_name="Maternity Wing (New)", ward_type="maternity",
            total_beds=15, occupied_beds=0,
        ),
    ])
    db.commit()
    print(f"Seeded demo patient: {patient.id}")
    print("Login: admin@medibridge.demo / admin123")
    print("Login: clinician@medibridge.demo / clinician123")
    print("Login: patient@medibridge.demo / patient123")
else:
    print("Demo data already seeded.")

db.close()
