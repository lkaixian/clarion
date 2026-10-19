"""P3.4: signed structured SOAP consultation notes.

Revision ID: 2c4e6a8b0d12
Revises: 190811a20bb0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "2c4e6a8b0d12"
down_revision: Union[str, Sequence[str], None] = "190811a20bb0"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "consultation_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("encounter_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("facility_name", sa.String(length=255), nullable=False),
        sa.Column("subjective", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("treatment_plan", sa.Text(), nullable=True),
        sa.Column("follow_up_at", _TZ, nullable=True),
        sa.Column("referral_service_request_id", sa.String(length=36), nullable=True),
        sa.Column("signed_by", sa.String(length=36), nullable=False),
        sa.Column("signed_by_name", sa.String(length=255), nullable=True),
        sa.Column("signed_at", _TZ, nullable=False),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="CASCADE", name=op.f("fk_consultation_notes_encounter_id_encounters")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE", name=op.f("fk_consultation_notes_patient_id_patients")),
        sa.ForeignKeyConstraint(["referral_service_request_id"], ["service_requests.id"], name=op.f("fk_consultation_notes_referral_service_request_id_service_requests")),
        sa.ForeignKeyConstraint(["signed_by"], ["users.id"], name=op.f("fk_consultation_notes_signed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultation_notes")),
    )
    with op.batch_alter_table("consultation_notes") as batch_op:
        # A single UNIQUE INDEX, not a separate UniqueConstraint -- matches
        # what `Column(..., unique=True, index=True)` on models.py's
        # ConsultationNote.encounter_id actually resolves to; a
        # UniqueConstraint here caused `check_schema.py`'s autogenerate
        # diff to see permanent drift (schema-review fix).
        batch_op.create_index(batch_op.f("ix_consultation_notes_encounter_id"), ["encounter_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_consultation_notes_patient_id"), ["patient_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_consultation_notes_facility_name"), ["facility_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_consultation_notes_referral_service_request_id"), ["referral_service_request_id"], unique=False)


def downgrade() -> None:
    # drop_table removes the table's indexes; dropping them first fails on MariaDB when an index backs a FK.
    op.drop_table("consultation_notes")
