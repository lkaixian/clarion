"""drug master + product catalogue + dictionaries from his_open_1

Revision ID: 1b2c4d6e8f10
Revises: 0f1a7c3d9b52
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "1b2c4d6e8f10"
down_revision = "0f1a7c3d9b52"
branch_labels = None
depends_on = None

APP = Path(__file__).resolve().parents[2] / "app"
CHUNK = 2000


def _fk(col: str, target: str):
    return sa.ForeignKeyConstraint([col], [target], ondelete="CASCADE")


def _load(table, name: str) -> None:
    d = json.loads((APP / "his_data" / f"{name}.json").read_text(encoding="utf-8"))
    rows = [dict(zip(d["cols"], r)) for r in d["rows"]]
    for i in range(0, len(rows), CHUNK):
        op.bulk_insert(table, rows[i:i + CHUNK])


def upgrade() -> None:
    S, F, I = sa.String, sa.Float, sa.Integer
    drugs = op.create_table(
        "drugs",
        sa.Column("drug_code", S(32), primary_key=True),
        sa.Column("drug_generic_name", S(255), nullable=False),
        sa.Column("drug_label", S(255)), sa.Column("active_ingredient", S(255)),
        sa.Column("drug_category", S(32)), sa.Column("drug_schedule", S(64)),
        sa.Column("drug_formulary", S(8)), sa.Column("drug_type", S(64)),
        sa.Column("item_subgroup", S(64)), sa.Column("trade_name", S(255)),
        sa.Column("strength", S(64)), sa.Column("uom_strength", S(64)),
        sa.Column("dosage_form", S(128)), sa.Column("sku_uom", S(32)),
        sa.Column("special_code", S(32)), sa.Column("instruction_code", S(32)),
        sa.Column("caution_code", S(32)),
    )
    op.create_index("ix_drugs_drug_generic_name", "drugs", ["drug_generic_name"])
    op.create_index("ix_drugs_drug_category", "drugs", ["drug_category"])
    rx = op.create_table(
        "drug_prescriptions",
        sa.Column("prescription_id", I, primary_key=True),
        sa.Column("drug_code", S(32), nullable=False),
        sa.Column("drug_dosage", F), sa.Column("dosage_code", S(32)),
        sa.Column("frequency_code", S(32)), sa.Column("route_code", S(32)),
        sa.Column("drug_duration", F), sa.Column("period_code", S(32)),
        sa.Column("drug_total_unit", F), sa.Column("instruction_code", S(32)),
        sa.Column("special_code", S(32)), sa.Column("caution_code", S(32)),
        _fk("drug_code", "drugs.drug_code"),
    )
    op.create_index("ix_drug_prescriptions_drug_code", "drug_prescriptions", ["drug_code"])
    dis = op.create_table(
        "drug_diseases",
        sa.Column("disease_id", I, primary_key=True),
        sa.Column("drug_code", S(32), nullable=False),
        sa.Column("indication_code", S(32), nullable=False),
        _fk("drug_code", "drugs.drug_code"),
    )
    op.create_index("ix_drug_diseases_drug_code", "drug_diseases", ["drug_code"])
    prod = op.create_table(
        "products",
        sa.Column("product_code", S(32), primary_key=True),
        sa.Column("product_name", S(255), nullable=False),
        sa.Column("product_name_other", S(255)), sa.Column("product_custom_id", S(64)),
        sa.Column("category_code", S(32)), sa.Column("unit_code", S(32)),
        sa.Column("order_form", S(32)), sa.Column("product_unit_charge", F),
        sa.Column("product_stocked", I), sa.Column("product_edit_price", I),
        sa.Column("product_reorder", F), sa.Column("product_input_tax", S(32)),
        sa.Column("form_code", S(32)), sa.Column("product_average_cost", F),
        sa.Column("charge_code", S(64)), sa.Column("product_output_tax", S(32)),
        sa.Column("status_code", S(32)), sa.Column("product_track_batch", I),
        sa.Column("product_on_hand", F), sa.Column("product_drop_charge", I),
        sa.Column("product_local_store", I), sa.Column("product_non_claimable", I),
        sa.Column("product_duration_use", I),
    )
    op.create_index("ix_products_product_name", "products", ["product_name"])
    op.create_index("ix_products_category_code", "products", ["category_code"])
    uom = op.create_table(
        "product_uoms",
        sa.Column("id", I, primary_key=True),
        sa.Column("product_code", S(32), nullable=False),
        sa.Column("unit_code", S(32)), sa.Column("uom_rate", F),
        sa.Column("uom_price", F), sa.Column("uom_price_2", F), sa.Column("uom_cost", F),
        sa.Column("uom_default_cost", I), sa.Column("uom_default_price", I),
    )
    op.create_index("ix_product_uoms_product_code", "product_uoms", ["product_code"])

    for t, n in ((drugs, "drugs"), (rx, "drug_prescriptions"), (dis, "drug_diseases"),
                 (prod, "products"), (uom, "product_uoms")):
        _load(t, n)

    ref = sa.table("reference_codes", sa.column("kind", S), sa.column("code", S),
                   sa.column("name", S), sa.column("parent", S), sa.column("extra", sa.JSON))
    rows = json.loads((APP / "reference_data_2.json").read_text(encoding="utf-8"))
    op.bulk_insert(ref, [dict(kind=k, code=c, name=n, parent=p, extra=e) for k, c, n, p, e in rows])


def downgrade() -> None:
    kinds = {r[0] for r in json.loads((APP / "reference_data_2.json").read_text(encoding="utf-8"))}
    ref = sa.table("reference_codes", sa.column("kind", sa.String))
    op.execute(ref.delete().where(ref.c.kind.in_(sorted(kinds))))
    for t in ("product_uoms", "products", "drug_diseases", "drug_prescriptions", "drugs"):
        op.drop_table(t)

