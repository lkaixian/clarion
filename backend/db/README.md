# DB Scripts

## `check_schema.py` — migration integrity gate (P1.5, CI-wired at P2.11)

```bash
python -m db.check_schema                       # throwaway temp SQLite
python -m db.check_schema --url "mysql+pymysql://clarion_migrate:PW@host:3306/clarion_citest?charset=utf8mb4"
```

Asserts, against a throwaway DB: (1) `alembic upgrade head` works from empty;
(2) autogenerate against head is empty (models.py == migration chain); (3)
`upgrade head → downgrade base → upgrade head` round-trips. Exits non-zero on
the first failure.

## Migration: SQLite to MariaDB

To migrate data from the existing SQLite demo database (`clarion.db`) to a newly set up MariaDB schema, use `migrate_sqlite_to_mariadb.py`.

### Prerequisites
- Target MariaDB instance must be up and running.
- Alembic migrations must be fully applied on the target database (`alembic upgrade head`).

### Usage

```bash
# Dry run pre-flight scan
python -m db.migrate_sqlite_to_mariadb \
  --source sqlite:///./clarion.db \
  --target "mysql+pymysql://clarion_migrate:<PASSWORD>@<HOST>:3306/clarion?charset=utf8mb4" \
  --dry-run

# Run migration (truncate target tables before copying)
python -m db.migrate_sqlite_to_mariadb \
  --source sqlite:///./clarion.db \
  --target "mysql+pymysql://clarion_migrate:<PASSWORD>@<HOST>:3306/clarion?charset=utf8mb4" \
  --truncate-target
```

### Options
- `--source`: Source database connection string (default: `sqlite:///./clarion.db`).
- `--target`: Target database connection string (required). Use the `clarion_migrate` account.
- `--dry-run`: Run the pre-flight scan and exit without copying data.
- `--truncate-target`: `TRUNCATE` every target table before copying (FK checks toggled off only for the truncate). Required if the target is not empty.
- `--report`: Reconciliation report path (default: `db/migration_report_<timestamp>.txt` next to the script; git-ignored).
- `--force`: Proceed past a failed pre-flight scan. Does **not** disable target FK enforcement — a genuinely orphaned row still fails its `INSERT`.
- `--prune-orphans`: During the copy, skip (and log to the report) any source row whose foreign key has no parent row in the target. Keeps the target referentially clean; the report lists every pruned row and adjusts the expected row counts.

### Pre-flight scan (blockers)
The scan runs on the **source** before any copy and aborts (unless `--force`) on:
FK orphans · over-length strings (P1.2 added `String(n)` limits SQLite ignored) ·
unique-collision under `utf8mb4_unicode_ci` (case/accent-insensitive) ·
duplicate active `room_claims` (the new generated-key UNIQUE would reject them) ·
invalid JSON.

### Known state of the demo `clarion.db` (2026-08-30)
It contains **2 orphaned rows** — `room_claims` and `staff_clock_events` rows for a
since-deleted user (`3a4e7165-…`). A clean run will BLOCK on them. For a demo copy,
run with `--prune-orphans` (they are stale artifacts of a hard-deleted staff
account and carry no value). For a real migration, repair the source first.
