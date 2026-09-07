"""P1.6 - move the legacy ``backend/uploads/`` tree into the ObjectStore and
backfill the ``*_object_key`` / ``*_sha256`` / ``*_bytes`` / ``*_mime`` columns.

Run this ONCE, on a DB that still holds the old ``*_path`` values - i.e. BEFORE
``alembic upgrade`` to revision ``84f653e6c999`` drops those columns. The Alembic
step is schema-only and cannot touch the filesystem, so this script is how the
data crosses over.

    alembic upgrade 84f653e6c999        # part 1: add the new key columns
    python -m db.migrate_uploads_to_objectstore --dry-run
    python -m db.migrate_uploads_to_objectstore
    alembic upgrade head                # part 2: drop the old *_path columns

It talks to the DB through reflection + SQLAlchemy Core (never the ORM models,
whose columns don't match the pre-migration schema), so it is safe to run while
the DB is still at the old revision. Each row is handled independently and
idempotently: a row that already has an ``*_object_key`` is skipped, a missing
file is reported and skipped, re-running is safe. The old files are left in
place - delete ``uploads/`` by hand once you have verified the object store.

For the SQLite demo you do not need this: ``rm clarion.db && python seed.py``
rebuilds everything straight into the object store.
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, select, update

from app.database import engine
from app.storage import (
    BUCKET_DOCUMENTS,
    BUCKET_MEDICINE,
    BUCKET_SIGNATURES,
    get_object_store,
    sanitize_filename,
)

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}


def _guess_mime(path: str) -> str:
    return _MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _sig_key(prefix: str):
    return lambda row: f"{prefix}/{row['id']}.png"


def _doc_key(row) -> str:
    return (
        f"{row['patient_id']}/{row['id']}_"
        + sanitize_filename(row.get("original_filename"), fallback="upload")
    )


def _medicine_key(row) -> str:
    base = os.path.basename((row.get("image_path") or "").replace("\\", "/"))
    return f"{row['id']}_" + sanitize_filename(base, fallback="image")


# table, legacy path column, new column prefix, bucket, key builder,
# extra columns the key builder needs
_TARGETS = [
    ("users", "signature_image_path", "signature", BUCKET_SIGNATURES, _sig_key("users"), []),
    ("encounters", "signature_image_path", "signature", BUCKET_SIGNATURES, _sig_key("encounters"), []),
    ("clinical_record_annotations", "signature_image_path", "signature", BUCKET_SIGNATURES, _sig_key("annotations"), []),
    ("clinical_documents", "file_path", "file", BUCKET_DOCUMENTS, _doc_key, ["patient_id", "original_filename"]),
    ("medicine_inventory", "image_path", "image", BUCKET_MEDICINE, _medicine_key, []),
]


def _resolve_legacy(path: str, uploads_root: str) -> str:
    """Legacy `*_path` values are usually absolute, but a relative one must
    resolve against the uploads root, NOT the process CWD — otherwise every
    file looks 'MISSING' when the script is run from the wrong directory."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(uploads_root, path))


def main() -> int:
    ap = argparse.ArgumentParser(description="Move backend/uploads/ into the ObjectStore (P1.6).")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument(
        "--uploads-root",
        default=str(Path(__file__).resolve().parent.parent / "uploads"),
        help="base dir for resolving relative legacy paths (default: backend/uploads)",
    )
    args = ap.parse_args()

    md = MetaData()
    store = get_object_store()
    moved = skipped = missing = 0

    for tbl_name, path_col, prefix, bucket, key_of, extra_cols in _TARGETS:
        # One transaction per table: a failure mid-run leaves earlier tables
        # committed and the current one rolled back — safe to resume (the
        # already-set key columns make re-runs a no-op).
        with engine.begin() as conn:
            tbl = Table(tbl_name, md, autoload_with=conn)
            cols = set(tbl.c.keys())
            if path_col not in cols:
                print(f"! {tbl_name}.{path_col} is already gone - DB is past this migration; skipping")
                continue
            key_col = f"{prefix}_object_key"
            if key_col not in cols:
                print(
                    f"! {tbl_name}.{key_col} does not exist yet - run "
                    "'alembic upgrade 84f653e6c999' first, then re-run this script"
                )
                return 2

            wanted = ["id", path_col, key_col] + [c for c in extra_cols if c in cols]
            rows = conn.execute(select(*[tbl.c[c] for c in wanted])).mappings().all()

            for row in rows:
                legacy = row[path_col]
                if not legacy:
                    continue
                if row.get(key_col):
                    skipped += 1
                    continue
                resolved = _resolve_legacy(legacy, args.uploads_root)
                if not os.path.isfile(resolved):
                    print(f"  MISSING  {tbl_name} {row['id']}: {resolved}")
                    missing += 1
                    continue

                with open(resolved, "rb") as fh:
                    data = fh.read()
                key = key_of(row)
                print(f"  move     {tbl_name} {row['id']}: {resolved} -> {bucket}/{key} ({len(data)} B)")
                moved += 1
                if args.dry_run:
                    continue

                meta = store.put(bucket, key, data, mime=_guess_mime(resolved))
                conn.execute(
                    update(tbl)
                    .where(tbl.c.id == row["id"])
                    .values(
                        **{
                            f"{prefix}_object_key": meta.key,
                            f"{prefix}_sha256": meta.sha256,
                            f"{prefix}_bytes": meta.size,
                            f"{prefix}_mime": meta.mime,
                        }
                    )
                )

    if args.dry_run:
        print(f"\nDRY RUN - would move {moved}, skip {skipped} (already migrated), {missing} missing file(s)")
    else:
        print(f"\nDONE - moved {moved}, skipped {skipped} (already migrated), {missing} missing file(s)")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
