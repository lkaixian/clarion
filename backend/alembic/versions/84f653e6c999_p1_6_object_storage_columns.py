"""P1.6 object storage columns (add)

Revision ID: 84f653e6c999
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30 20:36:03.581440

Part 1 of 2. Adds the ObjectStore coordinate columns
(``*_object_key`` + ``*_sha256`` + ``*_bytes`` + ``*_mime``) alongside the
existing local-filesystem ``*_path`` columns, which revision ``b7f1c0d94a2e``
drops once the blobs have been moved:

    users.signature_image_path                -> signature_object_key + siblings
    encounters.signature_image_path           -> signature_object_key + siblings
    clinical_record_annotations.signature_*   -> signature_object_key + siblings
    clinical_documents.file_path              -> file_object_key + siblings
    medicine_inventory.image_path             -> image_object_key + siblings

Splitting add-then-drop across two revisions lets
``db/migrate_uploads_to_objectstore.py`` run in between, while BOTH the old
path column and the new key columns exist, and populate the new columns from
the on-disk files (a schema-only migration can't touch the filesystem). For
the SQLite demo there is nothing to migrate — ``rm clarion.db && python
seed.py`` rebuilds straight into the object store.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "84f653e6c999"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> new column prefix
_PREFIX = {
    "users": "signature",
    "encounters": "signature",
    "clinical_record_annotations": "signature",
    "clinical_documents": "file",
    "medicine_inventory": "image",
}


def _add_cols(prefix: str) -> list:
    return [
        sa.Column(f"{prefix}_object_key", sa.String(length=512), nullable=True),
        sa.Column(f"{prefix}_sha256", sa.String(length=64), nullable=True),
        sa.Column(f"{prefix}_bytes", sa.Integer(), nullable=True),
        sa.Column(f"{prefix}_mime", sa.String(length=128), nullable=True),
    ]


def upgrade() -> None:
    for table, prefix in _PREFIX.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for col in _add_cols(prefix):
                batch_op.add_column(col)


def downgrade() -> None:
    for table, prefix in _PREFIX.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for suffix in ("mime", "bytes", "sha256", "object_key"):
                batch_op.drop_column(f"{prefix}_{suffix}")
