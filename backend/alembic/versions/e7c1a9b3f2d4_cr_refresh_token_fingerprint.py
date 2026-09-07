"""Code-review follow-up (2026-09-07): refresh_tokens.client_fingerprint

Revision ID: e7c1a9b3f2d4
Revises: d5e8a1c4b6f2
Create Date: 2026-09-07 00:00:00.000000

Adds the nullable ``client_fingerprint`` column
(``auth._is_concurrent_refresh_race`` uses it to refuse the concurrent-tab
grace when a reuse comes from a different device than the token was issued
to). Additive and nullable -- existing rows stay NULL and the fingerprint
check is skipped for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c1a9b3f2d4"
down_revision: Union[str, Sequence[str], None] = "d5e8a1c4b6f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_fingerprint", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.drop_column("client_fingerprint")
