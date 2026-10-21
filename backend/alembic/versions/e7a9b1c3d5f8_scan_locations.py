"""ScanLocation: where an emergency card was scanned (reported by the scanner's device)

Revision ID: e7a9b1c3d5f8
Revises: d6f8a0b2c4e7
"""
from alembic import op
import sqlalchemy as sa

revision = "e7a9b1c3d5f8"
down_revision = "d6f8a0b2c4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_locations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("actor_facility", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scan_location_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("emergency_token_id", sa.String(length=36), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("actor_facility", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scan_location_grants_token_hash", "scan_location_grants", ["token_hash"], unique=True)
    op.create_index("ix_scan_location_grants_patient_id", "scan_location_grants", ["patient_id"])
    op.create_index("ix_scan_location_grants_expires_at", "scan_location_grants", ["expires_at"])
    op.create_index("ix_scan_locations_patient_id", "scan_locations", ["patient_id"])
    op.create_index("ix_scan_locations_created_at", "scan_locations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scan_location_grants_expires_at", table_name="scan_location_grants")
    op.drop_index("ix_scan_location_grants_patient_id", table_name="scan_location_grants")
    op.drop_index("ix_scan_location_grants_token_hash", table_name="scan_location_grants")
    op.drop_table("scan_location_grants")
    op.drop_index("ix_scan_locations_created_at", table_name="scan_locations")
    op.drop_index("ix_scan_locations_patient_id", table_name="scan_locations")
    op.drop_table("scan_locations")
