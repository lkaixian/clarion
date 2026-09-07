# Alembic Database Migrations — CLARION Backend

This directory manages database schema migrations for the CLARION backend (FastAPI + SQLAlchemy 2.0).

---

## 1. Environment & `DATABASE_URL` Convention

Migrations read the target database connection string from the `DATABASE_URL` environment variable. If `DATABASE_URL` is not set, Alembic defaults to `sqlite:///./clarion.db` (matching `app.database.SQLALCHEMY_DATABASE_URL`).

### Targeting SQLite (Local Development / Demo)
```powershell
# Uses default sqlite:///./clarion.db
& ".\venv\Scripts\python.exe" -m alembic upgrade head

# Or explicitly set DATABASE_URL
$env:DATABASE_URL="sqlite:///./clarion.db"
& ".\venv\Scripts\python.exe" -m alembic upgrade head
```

### Targeting MariaDB / MySQL (Production / Testing)
```powershell
$env:DATABASE_URL="mysql+pymysql://clarion_migrate:<password>@localhost:3306/clarion?charset=utf8mb4"
& ".\venv\Scripts\python.exe" -m alembic upgrade head
```

---

## 2. Common Migration Commands

Always execute Alembic commands from the `backend/` directory using the project virtual environment.

### Apply Migrations (Upgrade)
```powershell
# Upgrade to latest revision
& ".\venv\Scripts\python.exe" -m alembic upgrade head

# Upgrade by one step
& ".\venv\Scripts\python.exe" -m alembic upgrade +1
```

### Rollback Migrations (Downgrade)
```powershell
# Rollback the last migration
& ".\venv\Scripts\python.exe" -m alembic downgrade -1

# Rollback to baseline
& ".\venv\Scripts\python.exe" -m alembic downgrade base
```

### Autogenerate a New Migration Revision
When you modify models in `app/models.py`:
```powershell
& ".\venv\Scripts\python.exe" -m alembic revision --autogenerate -m "describe schema change"
```

> Always review the generated script in `alembic/versions/` before applying it.

### Inspect Migration Status
```powershell
# View currently applied revision
& ".\venv\Scripts\python.exe" -m alembic current

# View revision history
& ".\venv\Scripts\python.exe" -m alembic history --verbose
```

---

## 3. One-Time Setup for Existing `clarion.db`

For an existing demo SQLite database (`clarion.db`) that was previously created/migrated via `create_all()` and `_migrate_lightweight()` in `main.py`:

Do **not** run `alembic upgrade head` directly against an existing populated database, as tables already exist. Instead, **stamp** the database at the baseline revision:

```powershell
# From backend/
& ".\venv\Scripts\python.exe" -m alembic stamp head
```

This creates the `alembic_version` tracking table and records the baseline revision without attempting to re-execute table creation DDL.

