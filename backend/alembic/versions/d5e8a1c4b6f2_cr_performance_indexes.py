"""Code-review follow-up (2026-09-07): performance indexes

Revision ID: d5e8a1c4b6f2
Revises: c4f34fe29451
Create Date: 2026-09-07 00:00:00.000000

Adds indexes the code-review perf pass flagged as missing:

* ``patient_id`` on every clinical-history table (conditions,
  medication_statements, allergy_intolerances, encounters,
  clinical_documents, appointments, audit_logs) -- these are read by
  ``_serialize_patient``'s relationship loads and by ``get_audit_log`` on
  every record open, and were created with only a bare ForeignKeyConstraint
  (no index). ``queue_tickets`` / ``admissions`` /
  ``clinical_record_annotations`` already had theirs.
* the authoring-facility columns scanned by ``list_patients``'
  facility-scope check (``_FACILITY_RELATIONSHIP_SOURCES``):
  ``encounters.facility_name``, ``appointments.facility_name``,
  ``conditions.authored_by_facility``,
  ``allergy_intolerances.authored_by_facility``,
  ``medication_statements.recorded_by_facility``.
* ``(facility_name, queue_date)`` on ``queue_tickets`` -- the public
  waiting-room board (polled up to 120x/min per screen) and every reception
  queue view filter on exactly this pair; the existing
  ``(facility_name, checked_in_at)`` index does not cover ``queue_date``.

Index names match SQLAlchemy's ``index=True`` convention (``ix_<table>_<col>``)
so ``alembic revision --autogenerate`` stays clean against models.py.

All operations are plain ``CREATE INDEX`` (no table rewrite / lock on
MariaDB's online-DDL for secondary indexes). ``downgrade`` drops them.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.exc import OperationalError


revision: str = "d5e8a1c4b6f2"
down_revision: Union[str, Sequence[str], None] = "c4f34fe29451"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index name, table, [columns])
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_conditions_patient_id", "conditions", ["patient_id"]),
    ("ix_medication_statements_patient_id", "medication_statements", ["patient_id"]),
    ("ix_allergy_intolerances_patient_id", "allergy_intolerances", ["patient_id"]),
    ("ix_encounters_patient_id", "encounters", ["patient_id"]),
    ("ix_clinical_documents_patient_id", "clinical_documents", ["patient_id"]),
    ("ix_appointments_patient_id", "appointments", ["patient_id"]),
    ("ix_audit_logs_patient_id", "audit_logs", ["patient_id"]),
    ("ix_encounters_facility_name", "encounters", ["facility_name"]),
    ("ix_appointments_facility_name", "appointments", ["facility_name"]),
    ("ix_conditions_authored_by_facility", "conditions", ["authored_by_facility"]),
    ("ix_allergy_intolerances_authored_by_facility", "allergy_intolerances", ["authored_by_facility"]),
    ("ix_medication_statements_recorded_by_facility", "medication_statements", ["recorded_by_facility"]),
    ("ix_queue_tickets_facility_date", "queue_tickets", ["facility_name", "queue_date"]),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        try:
            op.drop_index(name, table_name=table)
        except OperationalError as exc:
            # MariaDB error 1553: the index also backs a foreign key (creating it replaced
            # the FK's own implicit index), so it cannot be dropped. Leaving a redundant
            # index behind is harmless; anything else is a real failure.
            if getattr(exc.orig, "args", (None,))[0] != 1553:
                raise
