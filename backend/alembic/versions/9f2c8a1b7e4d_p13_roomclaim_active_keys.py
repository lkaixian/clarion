"""P1.3 RoomClaim active keys

Revision ID: 9f2c8a1b7e4d
Revises: 5e6a60dfe274
Create Date: 2026-08-30 16:59:00.000000

Adds the two VIRTUAL generated columns (active_room_key / active_user_key) and
their UNIQUE constraints that restore RoomClaim active-claim exclusivity on
MariaDB (models.RoomClaim).

NOTE: on the SQLite *demo* DB these columns are already added at startup by
main.py::_migrate_lightweight, so this revision is effectively stamp-only there
(`alembic stamp head`, per AGENTS.md) -- running a real `alembic upgrade` against
a booted SQLite demo DB would hit "duplicate column". SQLite is not the intended
Alembic target; MariaDB is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f2c8a1b7e4d'
down_revision: Union[str, None] = '5e6a60dfe274'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("room_claims", schema=None) as batch_op:
        batch_op.add_column(sa.Column("active_room_key", sa.String(36), sa.Computed("CASE WHEN released_at IS NULL THEN room_id END", persisted=False), nullable=True))
        batch_op.add_column(sa.Column("active_user_key", sa.String(36), sa.Computed("CASE WHEN released_at IS NULL THEN user_id END", persisted=False), nullable=True))
        batch_op.create_unique_constraint("uq_room_claims_active_room_key", ["active_room_key"])
        batch_op.create_unique_constraint("uq_room_claims_active_user_key", ["active_user_key"])


def downgrade() -> None:
    with op.batch_alter_table("room_claims", schema=None) as batch_op:
        batch_op.drop_constraint("uq_room_claims_active_user_key", type_="unique")
        batch_op.drop_constraint("uq_room_claims_active_room_key", type_="unique")
        batch_op.drop_column("active_user_key")
        batch_op.drop_column("active_room_key")
