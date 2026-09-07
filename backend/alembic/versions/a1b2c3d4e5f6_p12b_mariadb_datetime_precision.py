"""P1.2b MariaDB DATETIME(6) precision

Revision ID: a1b2c3d4e5f6
Revises: 9f2c8a1b7e4d
Create Date: 2026-08-30 18:30:00.000000

On MySQL/MariaDB, bare ``DATETIME`` carries no fractional-seconds precision and
silently ignores ``timezone=True``. ``models.py`` now declares every timestamp
column via ``TZDateTime`` (``DATETIME(6)`` on the mysql dialect); this migration
brings a MariaDB schema built from the ``5e6a60dfe274`` baseline up to match.

It is a **no-op on SQLite** -- ``TZDateTime`` renders identically to
``DateTime(timezone=True)`` there, so the SQLite-generated baseline already
matches and there is nothing to alter.

Data-driven: it walks ``Base.metadata`` for ``DateTime`` columns rather than
hard-coding ~50 table/column pairs, so it stays correct if a timestamp column
is added or removed before this revision is first applied to a real MariaDB.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9f2c8a1b7e4d"
branch_labels = None
depends_on = None


def _datetime_columns():
    """(table, column, nullable) for every DateTime column on the ORM metadata."""
    import app.models  # noqa: F401  -- registers every table on Base.metadata
    from app.database import Base

    cols = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, sa.DateTime):
                cols.append((table.name, col.name, col.nullable))
    return cols


def _apply(datetime_type: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    for table, column, nullable in _datetime_columns():
        null_sql = "NULL" if nullable else "NOT NULL"
        op.execute(f"ALTER TABLE `{table}` MODIFY `{column}` {datetime_type} {null_sql}")


def upgrade() -> None:
    _apply("DATETIME(6)")


def downgrade() -> None:
    _apply("DATETIME")
