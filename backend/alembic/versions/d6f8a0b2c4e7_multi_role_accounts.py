"""One account, several roles: user_roles table, users.last_role, users.responder_tier

Revision ID: d6f8a0b2c4e7
Revises: c5e7a9b1d3f6
"""
from alembic import op
import sqlalchemy as sa

revision = "d6f8a0b2c4e7"
down_revision = "c5e7a9b1d3f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(length=64), primary_key=True),
    )
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("last_role", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("responder_tier", sa.String(length=16), nullable=True))
        # One login per patient record: the role-grant check-then-act could otherwise double-link.
        b.create_unique_constraint("uq_users_patient_id", ["patient_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_patient_id", type_="unique")
        b.drop_column("responder_tier")
        b.drop_column("last_role")
    op.drop_table("user_roles")
