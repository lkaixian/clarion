"""tamper seal columns on signed-off clinical records

Revision ID: d3a91c5e7b20
Revises: f47db9202edd
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "d3a91c5e7b20"
down_revision = "f47db9202edd"
branch_labels = None
depends_on = None

TABLES = ("encounters", "clinical_record_annotations", "service_results", "dental_chart_entries")
_TS = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    for t in TABLES:
        with op.batch_alter_table(t) as b:
            b.add_column(sa.Column("seal", sa.String(128), nullable=True))
            b.add_column(sa.Column("seal_key_id", sa.String(16), nullable=True))
            b.add_column(sa.Column("sealed_at", _TS, nullable=True))


def downgrade() -> None:
    for t in TABLES:
        with op.batch_alter_table(t) as b:
            b.drop_column("sealed_at")
            b.drop_column("seal_key_id")
            b.drop_column("seal")
