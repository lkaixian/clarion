"""EmergencyToken.tag_digest / tag_budget: what was last written to the card, to flag a stale tag

Revision ID: e7a9c1d3f5b6
Revises: d6f8b0c2e4a5
"""
from alembic import op
import sqlalchemy as sa

revision = "e7a9c1d3f5b6"
down_revision = "d6f8b0c2e4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.add_column(sa.Column("tag_digest", sa.String(16), nullable=True))
        b.add_column(sa.Column("tag_budget", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.drop_column("tag_budget")
        b.drop_column("tag_digest")
