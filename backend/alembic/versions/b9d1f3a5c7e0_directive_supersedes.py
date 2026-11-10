"""critical_directives: supersedes_id + unique (patient, kind, supersedes) = optimistic conflict check

Revision ID: b9d1f3a5c7e0
Revises: a8c0e2f4b6d9
"""
from alembic import op
import sqlalchemy as sa

revision = "b9d1f3a5c7e0"
down_revision = "a8c0e2f4b6d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("critical_directives") as b:
        b.add_column(sa.Column("supersedes_id", sa.String(length=36), nullable=False, server_default=""))
    # Existing rows (feature not released) get a distinct chain value so the unique index can be built.
    op.execute("UPDATE critical_directives SET supersedes_id = id")
    op.create_index("uq_critical_directives_supersedes", "critical_directives",
                    ["patient_id", "kind", "supersedes_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_critical_directives_supersedes", table_name="critical_directives")
    with op.batch_alter_table("critical_directives") as b:
        b.drop_column("supersedes_id")
