"""HIS dataset features: coded demographics, sponsors, dependants, bed movements, CPOE orders,
purchasing (suppliers, purchase orders), clinical forms

Revision ID: 5f6a8b0c2d44
Revises: 4e5f7a9b1c33
"""
from alembic import op
import sqlalchemy as sa

revision = "5f6a8b0c2d44"
down_revision = "4e5f7a9b1c33"
branch_labels = None
depends_on = None

_PATIENT_COLUMNS = (
    ("title_code", 32), ("religion_code", 32), ("race_code", 32), ("nation_code", 32),
    ("marital_code", 32), ("occupation_code", 32), ("address_line", 255), ("postcode", 16),
    ("city", 128), ("state_code", 32), ("sponsor_code", 32), ("sponsor_member_no", 64),
)


def _ts(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _idx(table, *cols):
    for c in cols:
        op.create_index(f"ix_{table}_{c}", table, [c])


def upgrade() -> None:
    with op.batch_alter_table("patients") as b:
        for name, size in _PATIENT_COLUMNS:
            b.add_column(sa.Column(name, sa.String(size), nullable=True))

    op.create_table(
        "sponsors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_number", sa.String(64)),
        sa.Column("street_1", sa.String(255)),
        sa.Column("street_2", sa.String(255)),
        sa.Column("city", sa.String(128)),
        sa.Column("postcode", sa.String(16)),
        sa.Column("state_code", sa.String(32)),
        sa.Column("country", sa.String(64)),
        sa.Column("phone", sa.String(64)),
        sa.Column("entitlement_code", sa.String(32)),
        sa.Column("description", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("facility_name", "code", name="uq_sponsors_facility_code"),
    )
    _idx("sponsors", "facility_name")

    op.create_table(
        "patient_dependants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependant_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_code", sa.String(32)),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
        _ts("created_at"),
        sa.UniqueConstraint("patient_id", "dependant_id", name="uq_patient_dependants_pair"),
    )
    _idx("patient_dependants", "patient_id", "dependant_id")

    op.create_table(
        "bed_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("admissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_ward_id", sa.String(36)),
        sa.Column("from_bed_number", sa.Integer()),
        sa.Column("to_ward_id", sa.String(36), nullable=False),
        sa.Column("to_bed_number", sa.Integer(), nullable=False),
        sa.Column("moved_by", sa.String(36), sa.ForeignKey("users.id")),
        _ts("moved_at"),
    )
    _idx("bed_movements", "facility_name", "admission_id", "patient_id")

    op.create_table(
        "clinical_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.String(36), sa.ForeignKey("encounters.id", ondelete="SET NULL")),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("product_code", sa.String(32)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_code", sa.String(32)),
        sa.Column("is_stat", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("strength", sa.String(64)),
        sa.Column("dosage", sa.String(64)),
        sa.Column("route_code", sa.String(32)),
        sa.Column("frequency_code", sa.String(32)),
        sa.Column("duration", sa.Integer()),
        sa.Column("period_code", sa.String(32)),
        sa.Column("urgency_code", sa.String(32)),
        sa.Column("side", sa.String(32)),
        sa.Column("region", sa.String(64)),
        sa.Column("view", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ordered_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("ordered_by_name", sa.String(255)),
        _ts("created_at"),
        sa.Column("completed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("completed_by_name", sa.String(255)),
        _ts("completed_at"),
        sa.Column("completion_note", sa.Text()),
        sa.Column("cancelled_by", sa.String(36), sa.ForeignKey("users.id")),
        _ts("cancelled_at"),
        sa.Column("cancel_reason", sa.Text()),
    )
    _idx("clinical_orders", "patient_id", "encounter_id", "facility_name", "status")

    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_number", sa.String(64)),
        sa.Column("tax_number", sa.String(64)),
        sa.Column("street_1", sa.String(255)),
        sa.Column("street_2", sa.String(255)),
        sa.Column("city", sa.String(128)),
        sa.Column("postcode", sa.String(16)),
        sa.Column("state_code", sa.String(32)),
        sa.Column("phone", sa.String(64)),
        sa.Column("email", sa.String(255)),
        sa.Column("contact_person", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("facility_name", "code", name="uq_suppliers_facility_code"),
    )
    _idx("suppliers", "facility_name")

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("po_number", sa.String(32), nullable=False),
        sa.Column("supplier_id", sa.String(36), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reference", sa.String(128)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
        _ts("created_at"),
        _ts("ordered_at"),
        _ts("closed_at"),
        sa.UniqueConstraint("po_number"),
    )
    _idx("purchase_orders", "facility_name", "supplier_id", "status")

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("medicine_inventory.id"), nullable=False),
        sa.Column("item_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Float()),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(64)),
        sa.Column("expiry_date", sa.String(16)),
    )
    _idx("purchase_order_lines", "order_id", "item_id")

    op.create_table(
        "clinical_forms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
        _ts("created_at"),
        sa.UniqueConstraint("facility_name", "code", "version", name="uq_clinical_forms_code_version"),
    )
    _idx("clinical_forms", "facility_name")

    op.create_table(
        "form_responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("form_id", sa.String(36), sa.ForeignKey("clinical_forms.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.String(36), sa.ForeignKey("encounters.id", ondelete="SET NULL")),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("submitted_by_name", sa.String(255)),
        _ts("created_at"),
    )
    _idx("form_responses", "form_id", "patient_id", "facility_name")


def downgrade() -> None:
    for t in ("form_responses", "clinical_forms", "purchase_order_lines", "purchase_orders", "suppliers",
              "clinical_orders", "bed_movements", "patient_dependants", "sponsors"):
        op.drop_table(t)
    with op.batch_alter_table("patients") as b:
        for name, _ in reversed(_PATIENT_COLUMNS):
            b.drop_column(name)
