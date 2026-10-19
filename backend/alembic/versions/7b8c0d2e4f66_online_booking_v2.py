"""Online booking v2: per-facility timetable, saved booking profiles, appointment attendee snapshot

Revision ID: 7b8c0d2e4f66
Revises: 6a7b9c1d3e55

Additive only: 3 new tables (booking_services, booking_hours, booking_profiles),
3 columns on hospital_settings (online_booking_enabled NOT NULL with a server
default so existing rows backfill to false, latitude, longitude) and 5 nullable
columns on appointments.
"""
import contextlib

from alembic import op
from alembic.operations import batch as _batch
import sqlalchemy as sa

revision = "7b8c0d2e4f66"
down_revision = "6a7b9c1d3e55"
branch_labels = None
depends_on = None

_DT = sa.DateTime(timezone=True)


@contextlib.contextmanager
def _appointments_batch():
    """batch_alter_table('appointments'), made safe for SQLite.

    appointments carries the generated column active_clinician_slot_key
    (aa914ee7cc2f). SQLite batch mode rebuilds the table with INSERT..SELECT of
    every column and SQLite refuses to INSERT into a generated column. Dropping
    it from the transfer list lets the rebuilt table recompute it. Other
    dialects ALTER in place and need no help.
    """
    if op.get_bind().dialect.name != "sqlite":
        with op.batch_alter_table("appointments") as b:
            yield b
        return
    orig = _batch.ApplyBatchImpl.__init__

    def patched(self, *a, **k):
        orig(self, *a, **k)
        self.column_transfers["active_clinician_slot_key"] = {}  # no "expr": not inserted

    _batch.ApplyBatchImpl.__init__ = patched
    try:
        with op.batch_alter_table("appointments") as b:
            yield b
    finally:
        _batch.ApplyBatchImpl.__init__ = orig


def upgrade() -> None:
    op.create_table(
        "booking_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("relationship", sa.String(32), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("national_id", sa.String(32), nullable=True),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("created_at", _DT, nullable=True),
        sa.Column("updated_at", _DT, nullable=True),
    )
    op.create_index("ix_booking_profiles_owner_user_id", "booking_profiles", ["owner_user_id"])

    op.create_table(
        "booking_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("advance_days", sa.Integer(), nullable=False),
        sa.Column("min_notice_minutes", sa.Integer(), nullable=False),
        sa.UniqueConstraint("facility_name", "category", name="uq_booking_services_facility_category"),
    )

    op.create_table(
        "booking_hours",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("booking_services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.CheckConstraint("end_minute > start_minute", name="ck_booking_hours_end_after_start"),
    )
    op.create_index("ix_booking_hours_service_id", "booking_hours", ["service_id"])

    with op.batch_alter_table("hospital_settings") as b:
        b.add_column(sa.Column("online_booking_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        b.add_column(sa.Column("longitude", sa.Float(), nullable=True))

    with _appointments_batch() as b:
        b.add_column(sa.Column("booking_category", sa.String(32), nullable=True))
        b.add_column(sa.Column("booked_for_profile_id", sa.String(36), nullable=True))
        b.add_column(sa.Column("attendee_name", sa.String(255), nullable=True))
        b.add_column(sa.Column("attendee_relationship", sa.String(32), nullable=True))
        b.add_column(sa.Column("attendee_dob", sa.Date(), nullable=True))
        b.create_foreign_key(
            b.f("fk_appointments_booked_for_profile_id_booking_profiles"),
            "booking_profiles", ["booked_for_profile_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with _appointments_batch() as b:
        # FK first: MariaDB refuses to drop a column that still carries one.
        b.drop_constraint(b.f("fk_appointments_booked_for_profile_id_booking_profiles"), type_="foreignkey")
        b.drop_column("attendee_dob")
        b.drop_column("attendee_relationship")
        b.drop_column("attendee_name")
        b.drop_column("booked_for_profile_id")
        b.drop_column("booking_category")

    with op.batch_alter_table("hospital_settings") as b:
        b.drop_column("longitude")
        b.drop_column("latitude")
        b.drop_column("online_booking_enabled")

    op.drop_index("ix_booking_hours_service_id", table_name="booking_hours")
    op.drop_table("booking_hours")
    op.drop_table("booking_services")
    op.drop_index("ix_booking_profiles_owner_user_id", table_name="booking_profiles")
    op.drop_table("booking_profiles")
