"""P1.6 drop legacy *_path columns

Revision ID: b7f1c0d94a2e
Revises: 84f653e6c999
Create Date: 2026-08-30 21:05:00.000000

Part 2 of 2. Drops the local-filesystem ``*_path`` columns now that the
ObjectStore coordinate columns added in ``84f653e6c999`` are the source of
truth. Run ``db/migrate_uploads_to_objectstore.py`` BEFORE this revision to
move the blobs and populate the new columns -- this step is schema-only and
does not copy data.

``downgrade`` re-adds the columns (empty); the blobs are not moved back.

Code-review follow-up 2026-09-07: ``upgrade`` now REFUSES to run if any row still holds a
legacy ``*_path`` value without a corresponding ``*_object_key`` -- i.e. the
blob-move script has not been run -- so a bare ``alembic upgrade head``
against a populated database can no longer silently drop the only pointer to
every stored signature / document / medicine photo. The SQLite demo has no
such rows (``rm clarion.db && python seed.py`` rebuilds straight into the
object store), so it is unaffected. Set
``CLARION_FORCE_DROP_LEGACY_PATH_COLUMNS=1`` to drop the columns anyway and
knowingly accept the loss of those blob pointers.
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7f1c0d94a2e"
down_revision: Union[str, Sequence[str], None] = "84f653e6c999"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> (legacy path column, replacement object-key column)
_LEGACY = {
    "users": ("signature_image_path", "signature_object_key"),
    "encounters": ("signature_image_path", "signature_object_key"),
    "clinical_record_annotations": ("signature_image_path", "signature_object_key"),
    "clinical_documents": ("file_path", "file_object_key"),
    "medicine_inventory": ("image_path", "image_object_key"),
}

_OVERRIDE_ENV = "CLARION_FORCE_DROP_LEGACY_PATH_COLUMNS"


def _assert_blobs_migrated(bind) -> None:
    if os.environ.get(_OVERRIDE_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return

    unmigrated: list[str] = []
    for table, (path_col, key_col) in _LEGACY.items():
        count = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE {path_col} IS NOT NULL AND {path_col} <> '' "
                f"AND ({key_col} IS NULL OR {key_col} = '')"
            )
        ).scalar()
        if count:
            unmigrated.append(
                f"  - {table}.{path_col}: {count} row(s) still only on the local filesystem"
            )

    if unmigrated:
        raise RuntimeError(
            "Refusing to drop the legacy *_path columns: blobs still reference the "
            "local filesystem and have NOT been copied to the object store:\n"
            + "\n".join(unmigrated)
            + "\n\nRun  python db/migrate_uploads_to_objectstore.py  first (it moves the "
            "files and populates the *_object_key columns), then re-run "
            "`alembic upgrade head`. To drop the columns anyway and ACCEPT the loss of "
            f"those blob pointers, set {_OVERRIDE_ENV}=1."
        )


def upgrade() -> None:
    _assert_blobs_migrated(op.get_bind())
    for table, (path_col, _key_col) in _LEGACY.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column(path_col)


def downgrade() -> None:
    for table, (path_col, _key_col) in _LEGACY.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column(path_col, sa.String(length=512), nullable=True))
