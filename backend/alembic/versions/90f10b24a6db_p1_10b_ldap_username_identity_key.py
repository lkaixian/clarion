"""P1.10b LDAP identity key fix (voltagent security review finding C1)

Revision ID: 90f10b24a6db
Revises: 1b4bf5c769e9
Create Date: 2026-09-07 00:36:53.741829

Adds ``users.ldap_username`` -- the stable identity key for an
``auth_source="ldap"`` row (the exact string typed as the login username at
JIT-provision time), unique and nullable. Fixes a real bug in the P1.10
migration this follows: keying an LDAP-backed account's identity on `email`
(populated from the directory's `mail` attribute) breaks re-login and the
"revoked AD group takes effect next login" resync under any
`LDAP_USER_SEARCH_FILTER` other than the default `(mail={username})` -- e.g.
a realistic `sAMAccountName`-based AD login, where `mail` and the login
string are different values. See app/routers/auth_router.py's
`_resolve_login_user`/`_jit_provision_ldap_user`/`_verify_ldap_existing_user`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90f10b24a6db'
down_revision: Union[str, Sequence[str], None] = '1b4bf5c769e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ldap_username', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_users_ldap_username'), ['ldap_username'])


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_users_ldap_username'), type_='unique')
        batch_op.drop_column('ldap_username')
