"""P2.10: PDPA tables -- consent ledger, data-subject requests, DPO register, retention

Revision ID: d4a9c1e6f2b8
Revises: c3e8f1a4d5b7
Create Date: 2026-09-08 14:00:00.000000

Backs routers/pdpa.py + app/retention.py (roadmap P2.10, the tender).
Purely additive. Malaysia's PDPA has no right to erasure -- there is no
"delete" anything here; a withdraw_consent request appends to the consent
ledger, the retention scan only flags.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "d4a9c1e6f2b8"
down_revision: Union[str, Sequence[str], None] = "c3e8f1a4d5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=36), nullable=True),
        sa.Column("recorded_by_role", sa.String(length=64), nullable=True),
        sa.Column("created_at", _TZ, nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"],
                                name=op.f("fk_consent_records_patient_id_patients"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_records")),
    )
    with op.batch_alter_table("consent_records", schema=None) as b:
        b.create_index(b.f("ix_consent_records_patient_id"), ["patient_id"], unique=False)
        b.create_index(b.f("ix_consent_records_purpose"), ["purpose"], unique=False)
        b.create_index(b.f("ix_consent_records_created_at"), ["created_at"], unique=False)

    op.create_table(
        "data_subject_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("facility_name", sa.String(length=255), nullable=True),
        sa.Column("requested_by", sa.String(length=36), nullable=True),
        sa.Column("requested_at", _TZ, nullable=False),
        sa.Column("due_at", _TZ, nullable=True),
        sa.Column("assigned_to", sa.String(length=36), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", _TZ, nullable=True),
        sa.Column("export_object_key", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"],
                                name=op.f("fk_data_subject_requests_patient_id_patients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"],
                                name=op.f("fk_data_subject_requests_assigned_to_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_subject_requests")),
    )
    with op.batch_alter_table("data_subject_requests", schema=None) as b:
        b.create_index(b.f("ix_data_subject_requests_patient_id"), ["patient_id"], unique=False)
        b.create_index(b.f("ix_data_subject_requests_status"), ["status"], unique=False)
        b.create_index(b.f("ix_data_subject_requests_facility_name"), ["facility_name"], unique=False)

    op.create_table(
        "dpo_register",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("facility_name", sa.String(length=255), nullable=False),
        sa.Column("dpo_name", sa.String(length=255), nullable=True),
        sa.Column("dpo_email", sa.String(length=255), nullable=True),
        sa.Column("dpo_phone", sa.String(length=64), nullable=True),
        sa.Column("jpdp_registration_ref", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", _TZ, nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_dpo_register_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dpo_register")),
    )
    with op.batch_alter_table("dpo_register", schema=None) as b:
        b.create_index(b.f("ix_dpo_register_facility_name"), ["facility_name"], unique=True)

    op.create_table(
        "retention_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("retain_years", sa.Integer(), nullable=True),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", _TZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retention_policies")),
        sa.UniqueConstraint("category", name=op.f("uq_retention_policies_category")),
    )

    op.create_table(
        "retention_review_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("last_activity_at", _TZ, nullable=True),
        sa.Column("retain_until", _TZ, nullable=True),
        sa.Column("first_flagged_at", _TZ, nullable=False),
        sa.Column("last_flagged_at", _TZ, nullable=False),
        sa.Column("disposed", sa.Boolean(), nullable=False),
        sa.Column("disposed_by", sa.String(length=36), nullable=True),
        sa.Column("disposed_at", _TZ, nullable=True),
        sa.Column("disposition_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"],
                                name=op.f("fk_retention_review_items_patient_id_patients"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retention_review_items")),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_retention_review_items_entity"),
    )
    with op.batch_alter_table("retention_review_items", schema=None) as b:
        b.create_index(b.f("ix_retention_review_items_patient_id"), ["patient_id"], unique=False)
        b.create_index(b.f("ix_retention_review_items_disposed"), ["disposed"], unique=False)


def downgrade() -> None:
    for t in ("retention_review_items", "retention_policies", "dpo_register",
              "data_subject_requests", "consent_records"):
        op.drop_table(t)
