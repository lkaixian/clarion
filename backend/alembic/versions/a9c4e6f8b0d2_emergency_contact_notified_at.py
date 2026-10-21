"""Patient.emergency_contact_notified_at: throttle window for emergency-contact scan alerts

Revision ID: a9c4e6f8b0d2
Revises: f8b0d2e4a6c7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "a9c4e6f8b0d2"
down_revision = "f8b0d2e4a6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("patients") as b:
        b.add_column(sa.Column("emergency_contact_notified_at",
                            sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("patients") as b:
        b.drop_column("emergency_contact_notified_at")
