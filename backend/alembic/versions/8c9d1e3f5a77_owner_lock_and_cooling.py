"""Owner lock + self-registration cooling period

Revision ID: 8c9d1e3f5a77
Revises: 7b8c0d2e4f66
"""
from alembic import op
import sqlalchemy as sa

revision = "8c9d1e3f5a77"
down_revision = "7b8c0d2e4f66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("owner_locked_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("self_registered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("self_registered_at")
        b.drop_column("owner_locked_at")
