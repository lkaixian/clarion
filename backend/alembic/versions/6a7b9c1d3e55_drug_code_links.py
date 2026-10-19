"""Link free-text drug names to the HIS drug catalogue (drugs.drug_code)

Adds a nullable drug_code to medication_statements, medicine_inventory and
medicine_purchase_proposals, then backfills it where a name matches exactly ONE catalogue
drug (generic or trade name, case-insensitive). Anything ambiguous or unmatched stays NULL.
Purchase order lines get the code through their inventory item, so they carry no column.

Revision ID: 6a7b9c1d3e55
Revises: 5f6a8b0c2d44
"""
from alembic import op
import sqlalchemy as sa

revision = "6a7b9c1d3e55"
down_revision = "5f6a8b0c2d44"
branch_labels = None
depends_on = None

# table, name column, index it?
_TARGETS = (
    ("medication_statements", "drug_name", True),
    ("medicine_inventory", "drug_name", True),
    ("medicine_purchase_proposals", "proposed_drug_name", False),
)


def _name_map(conn):
    """lower(trim(name)) -> drug_code, for names that identify exactly one drug."""
    seen = {}
    for code, generic, trade in conn.execute(
        sa.text("SELECT drug_code, drug_generic_name, trade_name FROM drugs")
    ):
        for n in (generic, trade):
            key = (n or "").strip().lower()
            if key:
                seen.setdefault(key, set()).add(code)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def upgrade() -> None:
    for table, _, indexed in _TARGETS:
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("drug_code", sa.String(32), nullable=True))
        if indexed:
            op.create_index(f"ix_{table}_drug_code", table, ["drug_code"])

    conn = op.get_bind()
    names = _name_map(conn)
    if not names:
        return
    for table, col, _ in _TARGETS:
        for (name,) in conn.execute(sa.text(f"SELECT DISTINCT {col} FROM {table}")).fetchall():
            code = names.get((name or "").strip().lower())
            if code:
                conn.execute(
                    sa.text(f"UPDATE {table} SET drug_code = :c WHERE {col} = :n AND drug_code IS NULL"),
                    {"c": code, "n": name},
                )


def downgrade() -> None:
    for table, _, indexed in reversed(_TARGETS):
        if indexed:
            op.drop_index(f"ix_{table}_drug_code", table_name=table)
        with op.batch_alter_table(table) as b:
            b.drop_column("drug_code")
