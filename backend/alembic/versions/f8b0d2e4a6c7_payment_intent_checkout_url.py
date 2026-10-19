"""PaymentIntent.checkout_url: the hosted payment page a gateway (Stripe) sends the patient to

Revision ID: f8b0d2e4a6c7
Revises: e7a9c1d3f5b6
"""
from alembic import op
import sqlalchemy as sa

revision = "f8b0d2e4a6c7"
down_revision = "e7a9c1d3f5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payment_intents") as b:
        b.add_column(sa.Column("checkout_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("payment_intents") as b:
        b.drop_column("checkout_url")
