"""Remember the NFC chip type a card was registered with

Revision ID: 9d0e2f4a6b88
Revises: 8c9d1e3f5a77
"""
from alembic import op
import sqlalchemy as sa

revision = "9d0e2f4a6b88"
down_revision = "8c9d1e3f5a77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.add_column(sa.Column("nfc_tag_type", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("emergency_tokens") as b:
        b.drop_column("nfc_tag_type")
