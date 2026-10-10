"""status_daily: per-day component health counters for the public status page

Revision ID: e5b7c1d9a3f4
Revises: d3a91c5e7b20
"""
from alembic import op
import sqlalchemy as sa

revision = "e5b7c1d9a3f4"
down_revision = "d3a91c5e7b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_daily",
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("component", sa.String(32), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bad", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("day", "component"),
    )


def downgrade() -> None:
    op.drop_table("status_daily")
