"""deposit_refunds: timestamped events so day close can net deposit refunds

Revision ID: 4e5f7a9b1c33
Revises: 3d4e6f8a0b22
"""
from alembic import op
import sqlalchemy as sa

revision = "4e5f7a9b1c33"
down_revision = "3d4e6f8a0b22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deposit_refunds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deposit_id", sa.String(36), sa.ForeignKey("deposits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("refunded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("refunded_by_name", sa.String(255), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deposit_refunds_deposit_id", "deposit_refunds", ["deposit_id"])
    op.create_index("ix_deposit_refunds_facility_name", "deposit_refunds", ["facility_name"])


def downgrade() -> None:
    op.drop_table("deposit_refunds")
