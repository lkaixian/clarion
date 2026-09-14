"""P4.1: FHIR coding-triple columns + resource_identifiers table

Revision ID: a3f7c92e6b1d
Revises: 4c1cb27217d3
Create Date: 2026-09-14 00:00:00.000000

the tender (FHIR-readiness). Purely additive/nullable -- see
healthcare/FHIR Schema Readiness.md and app/fhir_terminology.py. Existing
rows get NULL codes (valid: FHIR's `code` is [0..1]); no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "a3f7c92e6b1d"
down_revision: Union[str, Sequence[str], None] = "4c1cb27217d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    with op.batch_alter_table("conditions", schema=None) as b:
        b.add_column(sa.Column("code_system", sa.String(length=255), nullable=True))
        b.add_column(sa.Column("code_code", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("code_display", sa.String(length=255), nullable=True))

    with op.batch_alter_table("medication_statements", schema=None) as b:
        b.add_column(sa.Column("code_system", sa.String(length=255), nullable=True))
        b.add_column(sa.Column("code_code", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("code_display", sa.String(length=255), nullable=True))

    with op.batch_alter_table("allergy_intolerances", schema=None) as b:
        b.add_column(sa.Column("code_system", sa.String(length=255), nullable=True))
        b.add_column(sa.Column("code_code", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("code_display", sa.String(length=255), nullable=True))

    with op.batch_alter_table("service_catalog_items", schema=None) as b:
        b.add_column(sa.Column("code_system", sa.String(length=255), nullable=True))
        b.add_column(sa.Column("code_display", sa.String(length=255), nullable=True))

    op.create_table(
        "resource_identifiers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("system", sa.String(length=255), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("created_at", _TZ, nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"],
                                 name=op.f("fk_resource_identifiers_patient_id_patients"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_identifiers")),
        sa.UniqueConstraint("patient_id", "system", "value", name="uq_resource_identifiers_patient_system_value"),
    )
    with op.batch_alter_table("resource_identifiers", schema=None) as b:
        b.create_index(b.f("ix_resource_identifiers_patient_id"), ["patient_id"], unique=False)


def downgrade() -> None:
    op.drop_table("resource_identifiers")

    with op.batch_alter_table("service_catalog_items", schema=None) as b:
        b.drop_column("code_display")
        b.drop_column("code_system")

    with op.batch_alter_table("allergy_intolerances", schema=None) as b:
        b.drop_column("code_display")
        b.drop_column("code_code")
        b.drop_column("code_system")

    with op.batch_alter_table("medication_statements", schema=None) as b:
        b.drop_column("code_display")
        b.drop_column("code_code")
        b.drop_column("code_system")

    with op.batch_alter_table("conditions", schema=None) as b:
        b.drop_column("code_display")
        b.drop_column("code_code")
        b.drop_column("code_system")
