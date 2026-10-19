"""P4.8: analyser_result_inbox table

Revision ID: 15e85cc1320c
Revises: 17f8b8eec362
Create Date: 2026-09-14 13:00:00.000000

Backs `app/hl7_listener.py` (roadmap P4.8, the tender -- lab-analyser
HL7 v2 integration). Purely additive -- no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "15e85cc1320c"
down_revision: Union[str, Sequence[str], None] = "17f8b8eec362"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "analyser_result_inbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_request_id", sa.String(length=36), nullable=True),
        sa.Column("facility_name", sa.String(length=255), nullable=True),
        sa.Column("hl7_control_id", sa.String(length=64), nullable=True),
        sa.Column("sending_facility", sa.String(length=255), nullable=True),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=False),
        sa.Column("flag_abnormal", sa.Boolean(), nullable=False),
        sa.Column("received_at", _TZ, nullable=True),
        sa.Column("discarded_at", _TZ, nullable=True),
        sa.Column("discarded_by", sa.String(length=36), nullable=True),
        sa.Column("discarded_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_request_id"], ["service_requests.id"],
            name=op.f("fk_analyser_result_inbox_service_request_id_service_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["discarded_by"], ["users.id"],
            name=op.f("fk_analyser_result_inbox_discarded_by_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyser_result_inbox")),
    )
    with op.batch_alter_table("analyser_result_inbox", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_analyser_result_inbox_service_request_id"), ["service_request_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_analyser_result_inbox_facility_name"), ["facility_name"], unique=False)


def downgrade() -> None:
    # drop_table removes the table's indexes; dropping them first fails on MariaDB when an index backs a FK.
    op.drop_table("analyser_result_inbox")
