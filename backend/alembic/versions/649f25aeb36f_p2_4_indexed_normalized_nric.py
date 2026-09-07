"""P2.4 indexed normalized NRIC (Security Audit M2)

Revision ID: 649f25aeb36f
Revises: 90f10b24a6db
Create Date: 2026-09-07 01:13:59.824130

Adds ``patients.normalized_national_id`` (unique indexed) and backfills it
from each existing row's ``national_id`` via ``nric.normalize_nric`` --
without this data step, every pre-existing patient with a real NRIC would
be unfindable by auth_router._resolve_patient_by_nric (login, both
OTP-reset endpoints, reception check-in, admission-by-IC) until their next
unrelated write, since national_id itself is otherwise immutable
post-creation. See models.Patient.normalized_national_id's docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

from app.nric import normalize_nric

# revision identifiers, used by Alembic.
revision: str = '649f25aeb36f'
down_revision: Union[str, Sequence[str], None] = '90f10b24a6db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('normalized_national_id', sa.String(length=64), nullable=True))

    # Backfill BEFORE creating the unique index -- two legacy rows whose
    # national_id differs only by dashes/case (which the OLD Python-loop
    # resolver already treated as a collision, so this can't introduce a
    # NEW conflict that didn't already exist in practice) would otherwise
    # make create_index fail outright instead of surfacing a clear
    # duplicate to fix by hand.
    bind = op.get_bind()
    session = orm.Session(bind=bind)
    patients_table = sa.table(
        "patients",
        sa.column("id", sa.String),
        sa.column("national_id", sa.String),
        sa.column("normalized_national_id", sa.String),
    )
    rows = session.execute(
        sa.select(patients_table.c.id, patients_table.c.national_id)
        .where(patients_table.c.national_id.isnot(None))
    ).all()
    for patient_id, national_id in rows:
        normalized = normalize_nric(national_id) or None
        if normalized:
            session.execute(
                patients_table.update()
                .where(patients_table.c.id == patient_id)
                .values(normalized_national_id=normalized)
            )
    session.commit()

    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_patients_normalized_national_id'), ['normalized_national_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_patients_normalized_national_id'))
        batch_op.drop_column('normalized_national_id')
