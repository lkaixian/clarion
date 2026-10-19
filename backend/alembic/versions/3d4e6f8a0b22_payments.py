"""payments: online payment intents, refunds (two-person), admission deposits

Revision ID: 3d4e6f8a0b22
Revises: 2c3d5e7f9a11
"""
from alembic import op
import sqlalchemy as sa

revision = "3d4e6f8a0b22"
down_revision = "2c3d5e7f9a11"
branch_labels = None
depends_on = None


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    S, I = sa.String, sa.Integer
    op.create_table(
        "payment_intents",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("bill_id", S(36), sa.ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", S(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_name", S(255), nullable=False),
        sa.Column("amount_cents", I, nullable=False),
        sa.Column("provider", S(32), nullable=False),
        sa.Column("provider_ref", S(128), nullable=True, unique=True),
        sa.Column("status", S(16), nullable=False),
        sa.Column("idempotency_key", S(64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("payment_id", S(36), sa.ForeignKey("payments.id"), nullable=True),
        _ts("created_at"), _ts("expires_at", nullable=False), _ts("completed_at", nullable=True),
        sa.UniqueConstraint("patient_id", "idempotency_key", name="uq_payment_intent_patient_key"),
    )
    for col in ("bill_id", "patient_id", "facility_name", "status"):
        op.create_index(f"ix_payment_intents_{col}", "payment_intents", [col])

    op.create_table(
        "refunds",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("payment_id", S(36), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bill_id", S(36), sa.ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_name", S(255), nullable=False),
        sa.Column("amount_cents", I, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", S(16), nullable=False),
        sa.Column("requested_by", S(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("requested_by_name", S(255), nullable=True),
        _ts("requested_at"),
        sa.Column("decided_by", S(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_by_name", S(255), nullable=True),
        _ts("decided_at", nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("provider_ref", S(128), nullable=True),
    )
    for col in ("payment_id", "bill_id", "facility_name", "status"):
        op.create_index(f"ix_refunds_{col}", "refunds", [col])

    op.create_table(
        "deposits",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("patient_id", S(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_name", S(255), nullable=False),
        sa.Column("amount_cents", I, nullable=False),
        sa.Column("applied_cents", I, nullable=False, server_default="0"),
        sa.Column("refunded_cents", I, nullable=False, server_default="0"),
        sa.Column("method", S(32), nullable=False),
        sa.Column("reference_no", S(128), nullable=True),
        sa.Column("received_by", S(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("received_by_name", S(255), nullable=True),
        _ts("received_at"),
    )
    op.create_index("ix_deposits_patient_id", "deposits", ["patient_id"])
    op.create_index("ix_deposits_facility_name", "deposits", ["facility_name"])


def downgrade() -> None:
    op.drop_table("deposits")
    op.drop_table("refunds")
    op.drop_table("payment_intents")
