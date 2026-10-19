"""EmergencyToken.nfc_revocation_id: lets offline devices recognise a revoked card

Revision ID: c5e7a9b1d3f4
Revises: b4d6f8a0c2e3
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e7a9b1d3f4"
down_revision = "b4d6f8a0c2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.add_column(sa.Column("nfc_revocation_id", sa.String(32), nullable=True))
        b.create_index("ix_emergency_tokens_nfc_revocation_id", ["nfc_revocation_id"])


def downgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.drop_index("ix_emergency_tokens_nfc_revocation_id")
        b.drop_column("nfc_revocation_id")
