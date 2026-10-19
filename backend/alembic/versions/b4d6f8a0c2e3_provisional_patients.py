"""Provisional patients (web sign-up with no hospital record) + claimant name

Revision ID: b4d6f8a0c2e3
Revises: a3c5e7f9b1d2
"""
from alembic import op
import sqlalchemy as sa

revision = "b4d6f8a0c2e3"
down_revision = "a3c5e7f9b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("patients") as b:
        b.add_column(sa.Column("provisional", sa.Boolean, nullable=False, server_default=sa.false()))
    with op.batch_alter_table("registration_claims") as b:
        b.add_column(sa.Column("full_name", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("registration_claims") as b:
        b.drop_column("full_name")
    with op.batch_alter_table("patients") as b:
        b.drop_column("provisional")
