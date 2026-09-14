"""P4.5: security_alerts table

Revision ID: 17f8b8eec362
Revises: a3f7c92e6b1d
Create Date: 2026-09-14 12:00:00.000000

Backs `app/security_analytics.py::run_scan` (roadmap P4.5, tender
 -- access-anomaly detection + AI-driven audit-trail
intelligence over the `audit_logs` hash chain). Purely additive -- no
existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "17f8b8eec362"
down_revision: Union[str, Sequence[str], None] = "a3f7c92e6b1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "security_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("actor_facility", sa.String(length=255), nullable=True),
        sa.Column("window_start", _TZ, nullable=False),
        sa.Column("window_end", _TZ, nullable=False),
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
        sa.Column("ai_explanation", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"], ["users.id"],
            name=op.f("fk_security_alerts_acknowledged_by_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_alerts")),
        sa.UniqueConstraint(
            "rule", "actor", "actor_facility", "window_start",
            name="uq_security_alerts_rule_actor_facility_window",
        ),
    )
    with op.batch_alter_table("security_alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_security_alerts_rule"), ["rule"], unique=False)
        batch_op.create_index(batch_op.f("ix_security_alerts_actor"), ["actor"], unique=False)
        batch_op.create_index(batch_op.f("ix_security_alerts_resolved"), ["resolved"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("security_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_security_alerts_resolved"))
        batch_op.drop_index(batch_op.f("ix_security_alerts_actor"))
        batch_op.drop_index(batch_op.f("ix_security_alerts_rule"))
    op.drop_table("security_alerts")
