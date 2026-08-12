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
        models.MedicationStatement(patient_id=patient.id, drug_name="Metformin", dosage="500mg", frequency="twice daily", prescribed_by_facility="Klinik Kesihatan Bandar", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Warfarin", dosage="5mg", frequency="once daily", prescribed_by_facility="Hospital Sejahtera", active=True, critical_for_emergency=True),
        models.MedicationStatement(patient_id=patient.id, drug_name="Aspirin", dosage="75mg", frequency="once daily", prescribed_by_facility="Private Clinic Damansara", active=True, critical_for_emergency=True),
        models.AllergyIntolerance(patient_id=patient.id, substance="Penicillin", reaction="Anaphylaxis", severity="severe", critical_for_emergency=True),
        models.Encounter(patient_id=patient.id, facility_name="Klinik Kesihatan Bandar", encounter_type="outpatient", reason="Routine diabetes checkup"),
        models.Encounter(patient_id=patient.id, facility_name="Hospital Sejahtera", encounter_type="inpatient", reason="Chest pain investigation"),
    ])
    db.commit()
    print(f"Seeded demo patient: {patient.id}")
    print("Login: admin@medibridge.demo / admin123")
    print("Login: clinician@medibridge.demo / clinician123")
    print("Login: patient@medibridge.demo / patient123")
else:
    print("Demo data already seeded.")

db.close()
