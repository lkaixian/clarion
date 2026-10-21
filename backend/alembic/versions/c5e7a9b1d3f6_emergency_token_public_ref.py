"""EmergencyToken.public_ref: random token in the link on an NFC tag (instead of the UID)

Revision ID: c5e7a9b1d3f6
Revises: b3d5f7a9c1e4
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e7a9b1d3f6"
down_revision = "b3d5f7a9c1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.add_column(sa.Column("public_ref", sa.String(length=64), nullable=True))
        b.create_unique_constraint("uq_emergency_tokens_public_ref", ["public_ref"])


def downgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.drop_constraint("uq_emergency_tokens_public_ref", type_="unique")
        b.drop_column("public_ref")
