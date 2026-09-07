"""P2.5 refresh tokens (Security Audit M4)

Revision ID: c4f34fe29451
Revises: 649f25aeb36f
Create Date: 2026-09-07 01:32:35.481044

New `refresh_tokens` table backing the short-access-token +
long-refresh-token session model (see app/auth.py's issue/rotate/revoke_
refresh_token functions and models.RefreshToken's docstring). Purely
additive -- no existing table/column touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'c4f34fe29451'
down_revision: Union[str, Sequence[str], None] = '649f25aeb36f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('refresh_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql'), nullable=True),
    sa.Column('replaced_by_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['replaced_by_id'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_replaced_by_id_refresh_tokens')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens'))
    )
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_refresh_tokens_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_refresh_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_refresh_tokens_user_id'), ['user_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refresh_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_refresh_tokens_token_hash'))
        batch_op.drop_index(batch_op.f('ix_refresh_tokens_expires_at'))

    op.drop_table('refresh_tokens')
