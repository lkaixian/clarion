"""fee schedules, product price tiers, ward/bed/diet/misc dictionaries from his_open_1

Revision ID: 2c3d5e7f9a11
Revises: 1b2c4d6e8f10
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "2c3d5e7f9a11"
down_revision = "1b2c4d6e8f10"
branch_labels = None
depends_on = None

APP = Path(__file__).resolve().parents[2] / "app"
CHUNK = 1000


def _load(table, name: str) -> None:
    d = json.loads((APP / "his_data" / f"{name}.json").read_text(encoding="utf-8"))
    rows = [dict(zip(d["cols"], r)) for r in d["rows"]]
    for i in range(0, len(rows), CHUNK):
        op.bulk_insert(table, rows[i:i + CHUNK])


def _kinds() -> list:
    rows = json.loads((APP / "reference_data_3.json").read_text(encoding="utf-8"))
    return rows


def upgrade() -> None:
    S, F, I = sa.String, sa.Float, sa.Integer
    fees = op.create_table(
        "fee_schedules",
        sa.Column("fee_code", S(32), primary_key=True),
        sa.Column("part", S(32)), sa.Column("header", S(255)), sa.Column("sub_header", S(255)),
        sa.Column("description", sa.Text()), sa.Column("value", S(200)), sa.Column("value2", S(200)),
    )
    op.create_index("ix_fee_schedules_part", "fee_schedules", ["part"])
    tiers = op.create_table(
        "product_price_tiers",
        sa.Column("tier_id", I, primary_key=True),
        sa.Column("charge_code", S(64), nullable=False),
        sa.Column("tier_min", F), sa.Column("tier_max", F), sa.Column("rates", sa.JSON()),
    )
    op.create_index("ix_product_price_tiers_charge_code", "product_price_tiers", ["charge_code"])
    _load(fees, "fee_schedules")
    _load(tiers, "product_price_tiers")

    ref = sa.table("reference_codes", sa.column("kind", S), sa.column("code", S),
                   sa.column("name", S), sa.column("parent", S), sa.column("extra", sa.JSON))
    op.bulk_insert(ref, [dict(kind=k, code=c, name=n, parent=p, extra=e) for k, c, n, p, e in _kinds()])


def downgrade() -> None:
    ref = sa.table("reference_codes", sa.column("kind", sa.String))
    op.execute(ref.delete().where(ref.c.kind.in_(sorted({r[0] for r in _kinds()}))))
    op.drop_table("product_price_tiers")
    op.drop_table("fee_schedules")
