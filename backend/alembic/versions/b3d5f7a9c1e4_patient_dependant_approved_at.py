"""PatientDependant.approved_at: an adult with a login of their own approves a carer

Revision ID: b3d5f7a9c1e4
Revises: a9c4e6f8b0d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "b3d5f7a9c1e4"
down_revision = "a9c4e6f8b0d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("patient_dependants") as b:
        b.add_column(sa.Column("approved_at",
                               sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("patient_dependants") as b:
        b.drop_column("approved_at")
