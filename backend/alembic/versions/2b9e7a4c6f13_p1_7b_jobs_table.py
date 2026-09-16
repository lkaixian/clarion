"""P1.7b: jobs table

Revision ID: 2b9e7a4c6f13
Revises: 15e85cc1320c
Create Date: 2026-09-16 10:00:00.000000

Backs `app/jobs.py` -- the generic async job queue (roadmap P1.7b's deferred
"async normalisation worker", scoped to thumbnail priming). Purely
additive -- no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "2b9e7a4c6f13"
down_revision: Union[str, Sequence[str], None] = "15e85cc1320c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_jobs_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_created_at"))
        batch_op.drop_index(batch_op.f("ix_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_jobs_kind"))
    op.drop_table("jobs")
