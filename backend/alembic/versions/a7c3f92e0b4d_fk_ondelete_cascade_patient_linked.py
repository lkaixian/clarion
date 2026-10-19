"""FK ondelete=CASCADE on the remaining patient-linked tables

Revision ID: a7c3f92e0b4d
Revises: 2c4e6a8b0d12
Create Date: 2026-09-13 18:00:00.000000

Architecture-review follow-up (2026-09-13): most `patients.id` FKs already
carry `ondelete="CASCADE"` (models.py, added incrementally as each table was
written). Six were missed -- AppointmentRescheduleRequest, Admission,
EmergencyToken, SelfRegistrationAttempt, QueueTicket,
ClinicalRecordAnnotation -- relying on nothing but "no Patient-delete
endpoint exists yet" to stay safe. Not a live bug (already tracked in
AGENTS.md), but the DB constraint should say what the app already means:
these six are exactly as patient-owned as Condition/MedicationStatement/
Appointment/etc., which already cascade. `AuditLog.patient_id` and
`User.patient_id` are deliberately left alone -- audit trail and login
accounts should not vanish just because the clinical patient row does.

batch_alter_table (not a raw ALTER) so this runs unchanged on SQLite (full
table rebuild) and MariaDB (native DROP/ADD FOREIGN KEY) -- same pattern as
9f2c8a1b7e4d. Constraint names come from database.py's naming_convention and
match exactly what baseline migration 5e6a60dfe274 already created them as.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7c3f92e0b4d'
down_revision: Union[str, None] = '2c4e6a8b0d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, fk_constraint_name, patient_id nullable?)
_TABLES = (
    ("appointment_reschedule_requests", "fk_appointment_reschedule_requests_patient_id_patients", False),
    ("admissions", "fk_admissions_patient_id_patients", False),
    ("emergency_tokens", "fk_emergency_tokens_patient_id_patients", False),
    ("self_registration_attempts", "fk_self_registration_attempts_patient_id_patients", False),
    ("queue_tickets", "fk_queue_tickets_patient_id_patients", False),
    ("clinical_record_annotations", "fk_clinical_record_annotations_patient_id_patients", False),
)


def upgrade() -> None:
    for table, fk_name, nullable in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                fk_name, "patients", ["patient_id"], ["id"], ondelete="CASCADE",
            )


def downgrade() -> None:
    for table, fk_name, nullable in reversed(_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(fk_name, "patients", ["patient_id"], ["id"])
