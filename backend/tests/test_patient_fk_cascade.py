"""Migration a7c3f92e0b4d -- FK ondelete=CASCADE on remaining patient-linked tables.

Verifies that the Alembic migration correctly configured ondelete=CASCADE
at the DB level for the 6 patient-linked tables:
  1. AppointmentRescheduleRequest.patient_id (appointment_reschedule_requests)
  2. Admission.patient_id (admissions)
  3. EmergencyToken.patient_id (emergency_tokens)
  4. SelfRegistrationAttempt.patient_id (self_registration_attempts)
  5. QueueTicket.patient_id (queue_tickets)
  6. ClinicalRecordAnnotation.patient_id (clinical_record_annotations)

Also verifies that un-cascaded foreign keys (such as AuditLog.patient_id)
are untouched and retain their non-cascading behavior.
"""
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import audit, models
from conftest import _make_patient


def test_patient_raw_sql_delete_cascades_to_all_six_tables(db_session, make_user):
    """Create one patient and one valid row in each of the 6 patient-linked
    tables. Deleting the patient via a raw SQL DELETE (with SQLite foreign_keys
    pragma enabled) must cascade and delete all 6 child rows at the DB level,
    without routing through SQLAlchemy ORM relationship cascade.

    `PRAGMA foreign_keys` is a per-DBAPI-connection setting, not a per-Session
    one -- SQLite keeps it on whichever pooled connection(s) this test
    happened to check out (this test's own multiple `commit()`s mean more
    than one physical connection can be involved), so a LATER test in the
    suite could silently inherit enforcement it doesn't expect (the rest of
    this suite is written assuming FKs are off, per the app's own SQLite
    behavior -- see database.py; a previous version of this test that only
    reset the pragma on one connection still leaked into
    test_reception_smoke.py's teardown). Disposing the whole engine's pool
    afterward is the reliable fix -- every connection this test may have
    touched gets thrown away rather than recycled, so later tests always get
    a fresh connection in the default (FK-unenforced) state."""
    # Ensure foreign key constraints are strictly enforced in SQLite
    db_session.execute(sa.text("PRAGMA foreign_keys = ON"))
    try:
        _run_cascade_check(db_session, make_user)
    finally:
        db_session.get_bind().dispose()


def _run_cascade_check(db_session, make_user):
    # Required user fixture for tables requiring created_by / requested_by / checked_in_by
    staff_user = make_user(role="clinician", facility="Main Hospital")

    # Create the patient
    patient = _make_patient(db_session, full_name="Cascade Target Patient")
    patient_id = patient.id

    now = datetime.now(timezone.utc)

    # 1. Appointment & AppointmentRescheduleRequest
    appointment = models.Appointment(
        patient_id=patient_id,
        facility_name="Main Hospital",
        scheduled_at=now + timedelta(days=2),
        created_by=staff_user.id,
    )
    db_session.add(appointment)
    db_session.commit()

    reschedule_req = models.AppointmentRescheduleRequest(
        appointment_id=appointment.id,
        patient_id=patient_id,
        requested_by=staff_user.id,
        reason_code="scheduling_conflict",
    )
    db_session.add(reschedule_req)

    # 2. Ward & Admission
    ward = models.Ward(
        facility_name="Main Hospital",
        ward_name="Ward 3A",
        total_beds=12,
    )
    db_session.add(ward)
    db_session.commit()

    admission = models.Admission(
        facility_name="Main Hospital",
        patient_id=patient_id,
        ward_id=ward.id,
        bed_number=1,
    )
    db_session.add(admission)

    # 3. EmergencyToken
    emergency_token = models.EmergencyToken(
        patient_id=patient_id,
        token=f"tok-{uuid.uuid4().hex}",
        expires_at=now + timedelta(hours=24),
    )
    db_session.add(emergency_token)

    # 4. SelfRegistrationAttempt
    self_reg = models.SelfRegistrationAttempt(
        patient_id=patient_id,
        email=f"selfreg-{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(self_reg)

    # 5. QueueTicket
    queue_ticket = models.QueueTicket(
        patient_id=patient_id,
        facility_name="Main Hospital",
        queue_date=now.strftime("%Y-%m-%d"),
        queue_number=42,
        source="manual",
        checked_in_by=staff_user.id,
    )
    db_session.add(queue_ticket)

    # 6. ClinicalRecordAnnotation
    annotation = models.ClinicalRecordAnnotation(
        patient_id=patient_id,
        target_type="condition",
        target_id=str(uuid.uuid4()),
        kind="note",
    )
    db_session.add(annotation)

    # Negative assertion baseline: AuditLog (patient_id nullable, un-cascaded)
    audit.log_access(db_session, None, "system", "system", "cascade_verification_event")

    db_session.commit()

    # Pre-condition: assert all 6 child rows exist
    assert db_session.query(models.AppointmentRescheduleRequest).filter_by(patient_id=patient_id).count() == 1
    assert db_session.query(models.Admission).filter_by(patient_id=patient_id).count() == 1
    assert db_session.query(models.EmergencyToken).filter_by(patient_id=patient_id).count() == 1
    assert db_session.query(models.SelfRegistrationAttempt).filter_by(patient_id=patient_id).count() == 1
    assert db_session.query(models.QueueTicket).filter_by(patient_id=patient_id).count() == 1
    assert db_session.query(models.ClinicalRecordAnnotation).filter_by(patient_id=patient_id).count() == 1

    # Explicitly enforce foreign keys right before raw SQL DELETE
    db_session.execute(sa.text("PRAGMA foreign_keys = ON"))

    # Execute raw SQL DELETE bypassing ORM cascade
    db_session.execute(sa.text("DELETE FROM patients WHERE id = :id"), {"id": patient_id})
    db_session.commit()

    # Assert 0 rows remain across all 6 tables for this patient_id
    assert db_session.query(models.AppointmentRescheduleRequest).filter_by(patient_id=patient_id).count() == 0
    assert db_session.query(models.Admission).filter_by(patient_id=patient_id).count() == 0
    assert db_session.query(models.EmergencyToken).filter_by(patient_id=patient_id).count() == 0
    assert db_session.query(models.SelfRegistrationAttempt).filter_by(patient_id=patient_id).count() == 0
    assert db_session.query(models.QueueTicket).filter_by(patient_id=patient_id).count() == 0
    assert db_session.query(models.ClinicalRecordAnnotation).filter_by(patient_id=patient_id).count() == 0

    # Negative check: un-cascaded AuditLog entry is unaffected and remains intact
    audit_row = db_session.query(models.AuditLog).filter_by(action="cascade_verification_event").first()
    assert audit_row is not None


def test_migration_fk_cascade_metadata_inspection(db_session):
    """Verify that Alembic migration a7c3f92e0b4d configured ondelete='CASCADE'
    on the foreign keys of all 6 target tables, while audit_logs is untouched."""
    insp = sa.inspect(db_session.bind)
    target_tables = (
        "appointment_reschedule_requests",
        "admissions",
        "emergency_tokens",
        "self_registration_attempts",
        "queue_tickets",
        "clinical_record_annotations",
    )

    for table_name in target_tables:
        fks = insp.get_foreign_keys(table_name)
        patient_fk = next(
            (
                fk
                for fk in fks
                if fk["referred_table"] == "patients" and "patient_id" in fk["constrained_columns"]
            ),
            None,
        )
        assert patient_fk is not None, f"Foreign key to patients table missing on {table_name}"
        ondelete = str(patient_fk.get("options", {}).get("ondelete", "")).upper()
        assert ondelete == "CASCADE", (
            f"Expected ondelete='CASCADE' on {table_name}.patient_id, got {patient_fk.get('options')}"
        )

    # Negative check: audit_logs.patient_id must NOT have ondelete=CASCADE
    audit_fks = insp.get_foreign_keys("audit_logs")
    audit_patient_fk = next(
        (
            fk
            for fk in audit_fks
            if fk["referred_table"] == "patients" and "patient_id" in fk["constrained_columns"]
        ),
        None,
    )
    assert audit_patient_fk is not None, "Foreign key to patients table missing on audit_logs"
    audit_ondelete = str(audit_patient_fk.get("options", {}).get("ondelete", "")).upper()
    assert audit_ondelete != "CASCADE", (
        f"audit_logs.patient_id should NOT have ondelete='CASCADE', got {audit_patient_fk.get('options')}"
    )
