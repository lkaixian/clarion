"""User.access_expires_at: hard expiry for time-boxed (community responder) accounts

Revision ID: d6f8b0c2e4a5
Revises: c5e7a9b1d3f4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "d6f8b0c2e4a5"
down_revision = "c5e7a9b1d3f4"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("access_expires_at", _TZ, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("access_expires_at")
