"""P2.12: data_quality_alerts table

Revision ID: c3e8f1a4d5b7
Revises: b2d7e4a9c1f6
Create Date: 2026-09-08 12:00:00.000000

Backs `app/data_quality.py::run_scan` (roadmap P2.12, the tender --
automated data-quality monitoring: missing values / duplicate patients /
inconsistent coding / anomalous entries, with configurable admin alerts).
Purely additive -- no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "c3e8f1a4d5b7"
down_revision: Union[str, Sequence[str], None] = "b2d7e4a9c1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "data_quality_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("first_seen_at", _TZ, nullable=False),
        sa.Column("last_seen_at", _TZ, nullable=False),
        sa.Column("times_seen", sa.Integer(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=36), nullable=True),
        sa.Column("acknowledged_at", _TZ, nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", _TZ, nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"],
            name=op.f("fk_data_quality_alerts_patient_id_patients"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"], ["users.id"],
            name=op.f("fk_data_quality_alerts_acknowledged_by_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_alerts")),
        sa.UniqueConstraint(
            "rule", "entity_type", "entity_id",
            name="uq_data_quality_alerts_rule_entity",
        ),
    )
    with op.batch_alter_table("data_quality_alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_data_quality_alerts_rule"), ["rule"], unique=False)
        batch_op.create_index(batch_op.f("ix_data_quality_alerts_patient_id"), ["patient_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_data_quality_alerts_resolved"), ["resolved"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("data_quality_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_quality_alerts_resolved"))
        batch_op.drop_index(batch_op.f("ix_data_quality_alerts_patient_id"))
        batch_op.drop_index(batch_op.f("ix_data_quality_alerts_rule"))
    op.drop_table("data_quality_alerts")
