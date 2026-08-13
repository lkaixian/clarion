import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from . import models
from .database import engine
from .routers import auth_router, patients, emergency, ai_router

models.Base.metadata.create_all(bind=engine)


def _backup_sqlite_file_before_migration():
    """Best-effort copy of the live SQLite file to backend/backups/ before
    any ALTER TABLE runs. Only called when _migrate_lightweight() has
    detected at least one pending column/index addition, so a normal
    restart (no pending schema change) never touches disk beyond the usual
    DB file. Silently no-ops for non-SQLite backends or if the file can't
    be found — this is a cheap safety net for the demo DB, not a real
    backup strategy (no retention/rotation policy; old backups just
    accumulate under backend/backups/)."""
    try:
        db_url = engine.url
        if db_url.get_backend_name() != "sqlite" or not db_url.database:
            return
        db_path = Path(db_url.database)
        if not db_path.is_file():
            return
        backups_dir = db_path.parent / "backups"
        backups_dir.mkdir(exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups_dir / f"{db_path.stem}_pre_migration_{timestamp}{db_path.suffix}"
        shutil.copy2(db_path, backup_path)
    except OSError:
        # Never let a backup failure block startup/migration of the live DB.
        pass


def _migrate_lightweight():
    """This project has no Alembic (SQLite + `create_all`, hackathon-scale
    on purpose) — `create_all` only creates *missing tables*, not missing
    *columns* (or indexes on pre-existing columns) on tables that already
    existed on disk. So when a column is added to an existing model (like
    `EmergencyToken.nfc_uid`), an already-seeded `medibridge.db` from
    before that change needs a manual `ALTER TABLE`. This runs once at
    startup, is a no-op if the column/index already exists, and only ever
    adds columns/indexes — never destructive. A backup of the DB file is
    taken first, but only if something is actually about to change."""
    inspector = inspect(engine)

    existing_columns = set()
    if "emergency_tokens" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("emergency_tokens")}

    existing_user_columns = set()
    existing_user_indexes = set()
    if "users" in inspector.get_table_names():
        existing_user_columns = {col["name"] for col in inspector.get_columns("users")}
        existing_user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}

    pending = (
        ("emergency_tokens" in inspector.get_table_names() and (
            "nfc_uid" not in existing_columns or "registered_by" not in existing_columns
        ))
        or ("users" in inspector.get_table_names() and (
            "must_change_password" not in existing_user_columns
            or "reset_attempt_count" not in existing_user_columns
            or "reset_locked_until" not in existing_user_columns
            or "login_failed_count" not in existing_user_columns
            or "login_locked_until" not in existing_user_columns
            or "ix_users_patient_id" not in existing_user_indexes
        ))
    )
    if pending:
        _backup_sqlite_file_before_migration()

    if "emergency_tokens" in inspector.get_table_names():
        with engine.begin() as conn:
            if "nfc_uid" not in existing_columns:
                conn.execute(text("ALTER TABLE emergency_tokens ADD COLUMN nfc_uid VARCHAR"))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_emergency_tokens_nfc_uid "
                    "ON emergency_tokens (nfc_uid)"
                ))
            if "registered_by" not in existing_columns:
                conn.execute(text("ALTER TABLE emergency_tokens ADD COLUMN registered_by VARCHAR"))

    # Added for staff-issued patient accounts / self-service password reset
    # (POST /auth/patients/{id}/issue-account, /auth/forgot-password,
    # /auth/change-password). All nullable/defaulted so this is a safe
    # additive ALTER TABLE against an already-seeded medibridge.db.
    if "users" in inspector.get_table_names():
        with engine.begin() as conn:
            if "must_change_password" not in existing_user_columns:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
                ))
            if "reset_attempt_count" not in existing_user_columns:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN reset_attempt_count INTEGER NOT NULL DEFAULT 0"
                ))
            if "reset_locked_until" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN reset_locked_until DATETIME"))
            # Added for POST /auth/login lockout (brute-force protection on
            # the login endpoint itself, distinct from the reset_* columns
            # above which only cover /auth/forgot-password).
            if "login_failed_count" not in existing_user_columns:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN login_failed_count INTEGER NOT NULL DEFAULT 0"
                ))
            if "login_locked_until" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN login_locked_until DATETIME"))
            # patient_id is a hot-path lookup key (login NRIC resolution,
            # issue-account, forgot-password) — index it on already-seeded
            # DBs too, matching models.py's `index=True` (which only takes
            # effect for brand-new tables via create_all).
            if "ix_users_patient_id" not in existing_user_indexes:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_users_patient_id ON users (patient_id)"
                ))


_migrate_lightweight()

app = FastAPI(
    title="MediBridge API",
    description="Emergency-first, interoperable health record continuity system.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your web/mobile origins before any real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(patients.router)
app.include_router(emergency.router)
app.include_router(ai_router.router)


@app.get("/")
def root():
    return {"status": "MediBridge API running", "docs": "/docs"}
