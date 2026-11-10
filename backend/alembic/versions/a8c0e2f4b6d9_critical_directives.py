"""critical_directives: append-only organ donation / transfusion / device / advance directive rows

Revision ID: a8c0e2f4b6d9
Revises: e7a9b1c3d5f8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "a8c0e2f4b6d9"
down_revision = "e7a9b1c3d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "critical_directives",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("evidence_ref", sa.String(length=120), nullable=True),
        sa.Column("recorded_by", sa.String(length=36), nullable=True),
        sa.Column("recorded_by_name", sa.String(length=255), nullable=True),
        sa.Column("recorded_by_role", sa.String(length=64), nullable=True),
        sa.Column("recorded_by_facility", sa.String(length=255), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
                  nullable=False),
    )
    op.create_index("ix_critical_directives_patient_id", "critical_directives", ["patient_id"])


def downgrade() -> None:
    # The FK is the only thing tying this table to patients; on MariaDB the patient_id index backs it, so
    # drop the table (which drops the FK and index together) rather than the index alone.
    op.drop_table("critical_directives")
