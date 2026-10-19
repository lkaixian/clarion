"""Pending registration claims + flagged emails

Revision ID: a3c5e7f9b1d2
Revises: 9d0e2f4a6b88
"""
from alembic import op
import sqlalchemy as sa

revision = "a3c5e7f9b1d2"
down_revision = "9d0e2f4a6b88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("otp_code_hash", sa.String(255), nullable=True),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("otp_request_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("otp_request_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("photo_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("patient_id", "email", name="uq_registration_claims_patient_email"),
    )
    op.create_index("ix_registration_claims_patient_id", "registration_claims", ["patient_id"])
    op.create_table(
        "flagged_emails",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("flagged_emails")
    op.drop_index("ix_registration_claims_patient_id", table_name="registration_claims")
    op.drop_table("registration_claims")
