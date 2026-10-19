"""reference_codes: HIS lookup lists (states, cities, postcodes, nations, titles, ...)

Revision ID: 0f1a7c3d9b52
Revises: b8e4d1a7c3f2
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0f1a7c3d9b52"
down_revision = "b8e4d1a7c3f2"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[2] / "app" / "reference_data.json"


def upgrade() -> None:
    t = op.create_table(
        "reference_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("parent", sa.String(64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
    )
    op.create_index("ix_reference_codes_kind", "reference_codes", ["kind"])
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    op.bulk_insert(t, [dict(kind=k, code=c, name=n, parent=p, extra=e) for k, c, n, p, e in rows])


def downgrade() -> None:
    op.drop_index("ix_reference_codes_kind", table_name="reference_codes")
    op.drop_table("reference_codes")

