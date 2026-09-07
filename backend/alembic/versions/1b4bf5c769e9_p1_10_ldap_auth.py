"""P1.10 LDAP/AD auth provider

Revision ID: 1b4bf5c769e9
Revises: b7f1c0d94a2e
Create Date: 2026-09-07 00:06:14.773526

Adds the admin-editable AD-group -> role mapping table
(``ldap_role_mappings``) and two additive columns on ``users``:
``auth_source`` (server_default 'local' so every existing row backfills to
its real, only behaviour -- no existing account becomes LDAP-backed by this
migration) and ``ldap_dn`` (nullable cache, audit/debugging only). See
app/ldap_auth.py and healthcare/Integration Engine and LDAP.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '1b4bf5c769e9'
down_revision: Union[str, Sequence[str], None] = 'b7f1c0d94a2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ldap_role_mappings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('group_dn', sa.String(length=512), nullable=False),
    sa.Column('role', sa.String(length=64), nullable=False),
    sa.Column('facility', sa.String(length=255), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ldap_role_mappings')),
    sa.UniqueConstraint('group_dn', name=op.f('uq_ldap_role_mappings_group_dn'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auth_source', sa.String(length=32), server_default='local', nullable=False))
        batch_op.add_column(sa.Column('ldap_dn', sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('ldap_dn')
        batch_op.drop_column('auth_source')

    op.drop_table('ldap_role_mappings')
