"""
Run once after first setup: python seed.py
Creates a demo admin, a demo clinician, and one synthetic patient with a
realistic multi-facility history — enough to demo every pillar end to end.
"""
from app.database import SessionLocal, engine, Base
from app import models, auth

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if not db.query(models.User).filter(models.User.email == "admin@medibridge.demo").first():
    admin = models.User(
        email="admin@medibridge.demo", hashed_password=auth.hash_password("admin123"),
        full_name="Demo Admin", role="admin",
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
        # Justifies Simvastatin below.
        models.Condition(patient_id=patient.id, name="Hyperlipidemia", status="active", is_chronic=True, critical_for_emergency=False),

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
    print(f"Seeded demo patient: {patient.id}")
    print("Login: admin@medibridge.demo / admin123")
    print("Login: clinician@medibridge.demo / clinician123")
    print("Login: patient@medibridge.demo / patient123")
else:
    print("Demo data already seeded.")

db.close()
