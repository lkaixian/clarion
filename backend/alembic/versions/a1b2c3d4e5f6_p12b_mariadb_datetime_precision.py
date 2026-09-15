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


def _datetime_columns(bind):
    """(table, column, nullable) for every DATETIME-family column that
    actually exists in the database right now -- reflected from the live
    bind, not from app.models.

    Reflecting app.models (the original approach) was a bug: it always
    walks TODAY's full model set, so any table added to models.py *after*
    this revision was written (audit_chain_state, security_alerts, every
    P2.9-P4.8 table) got included here too -- even though this revision
    sits early in the chain (right after 9f2c8a1b7e4d, 2026-08-30), before
    those tables' own CREATE TABLE migrations run. `alembic upgrade head`
    against a genuinely fresh MariaDB then fails with "table doesn't
    exist" -- found live during P5.2 load-test setup, the first time this
    revision was replayed start-to-finish against an empty database rather
    than one that already had the full current schema. Reflecting the bind
    is what "data-driven" was meant to deliver: exactly the tables/columns
    that exist at THIS point in the chain, whichever revision that turns
    out to be.
    """
    inspector = sa.inspect(bind)
    cols = []
    for table in inspector.get_table_names():
        for col in inspector.get_columns(table):
            if isinstance(col["type"], sa.DateTime):
                cols.append((table, col["name"], col["nullable"]))
    return cols


def _apply(datetime_type: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    for table, column, nullable in _datetime_columns(bind):
        null_sql = "NULL" if nullable else "NOT NULL"
        op.execute(f"ALTER TABLE `{table}` MODIFY `{column}` {datetime_type} {null_sql}")


def upgrade() -> None:
    _apply("DATETIME(6)")


def downgrade() -> None:
    _apply("DATETIME")
