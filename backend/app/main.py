import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Loaded as early as possible, before anything (email_service in
# particular) reads MAILGUN_* / other env vars, so a local backend/.env
# file works the same as real environment variables in a deployment. A
# missing .env is fine -- load_dotenv() just no-ops.
load_dotenv()

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

    existing_patient_columns = set()
    if "patients" in inspector.get_table_names():
        existing_patient_columns = {col["name"] for col in inspector.get_columns("patients")}

    existing_document_columns = set()
    if "clinical_documents" in inspector.get_table_names():
        existing_document_columns = {col["name"] for col in inspector.get_columns("clinical_documents")}

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
            or "otp_code_hash" not in existing_user_columns
            or "otp_expires_at" not in existing_user_columns
            or "otp_attempt_count" not in existing_user_columns
            or "otp_request_count" not in existing_user_columns
            or "otp_request_window_start" not in existing_user_columns
        ))
        or ("patients" in inspector.get_table_names() and (
            "email" not in existing_patient_columns
            or "emergency_contact_name" not in existing_patient_columns
            or "emergency_contact_phone" not in existing_patient_columns
            or "emergency_contact_relationship" not in existing_patient_columns
        ))
        or ("clinical_documents" in inspector.get_table_names() and (
            "file_path" not in existing_document_columns
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
            # Added for the email-OTP password reset flow (POST
            # /auth/request-password-reset-otp, POST
            # /auth/reset-password-with-otp), replacing the old NRIC+DOB
            # single-step /auth/forgot-password. Only ever the HASH of the
            # OTP is stored (otp_code_hash), never the plaintext code.
            if "otp_code_hash" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN otp_code_hash VARCHAR"))
            if "otp_expires_at" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN otp_expires_at DATETIME"))
            if "otp_attempt_count" not in existing_user_columns:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN otp_attempt_count INTEGER NOT NULL DEFAULT 0"
                ))
            if "otp_request_count" not in existing_user_columns:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN otp_request_count INTEGER NOT NULL DEFAULT 0"
                ))
            if "otp_request_window_start" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN otp_request_window_start DATETIME"))

    # Added for patient self-service profile editing (PATCH
    # /patients/{id}/profile). All nullable — additive/safe ALTER TABLE
    # against an already-seeded medibridge.db. `email` here is the
    # patient's own contact address (where the password-reset OTP is
    # sent), distinct from users.email which stays the internal
    # login-identifier field.
    if "patients" in inspector.get_table_names():
        with engine.begin() as conn:
            if "email" not in existing_patient_columns:
                conn.execute(text("ALTER TABLE patients ADD COLUMN email VARCHAR"))
            if "emergency_contact_name" not in existing_patient_columns:
                conn.execute(text("ALTER TABLE patients ADD COLUMN emergency_contact_name VARCHAR"))
            if "emergency_contact_phone" not in existing_patient_columns:
                conn.execute(text("ALTER TABLE patients ADD COLUMN emergency_contact_phone VARCHAR"))
            if "emergency_contact_relationship" not in existing_patient_columns:
                conn.execute(text("ALTER TABLE patients ADD COLUMN emergency_contact_relationship VARCHAR"))

    # Added for original-file retrieval of uploaded clinical documents (GET
    # /patients/{id}/documents/{id}/file) -- see ClinicalDocument.file_path.
    # Nullable/additive; existing rows just get file_path=NULL (their
    # original file was never persisted -- only OCR'd text is available for
    # those, same as before this change).
    if "clinical_documents" in inspector.get_table_names():
        with engine.begin() as conn:
            if "file_path" not in existing_document_columns:
                conn.execute(text("ALTER TABLE clinical_documents ADD COLUMN file_path VARCHAR"))


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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """FastAPI's default handler for a pydantic validation failure returns
    `{"detail": [{"type": ..., "loc": [...], "msg": "Value error, ...", ...}]}`
    -- a list of objects. Every other error in this API returns
    `{"detail": "<plain string>"}`, and every client (mobile's
    ApiException, web's `e?.response?.data?.detail`) expects/displays a
    plain string, so this one class of error (any pydantic field_validator
    failure -- password length being the case that got reported, but this
    applies app-wide to any current/future validator) rendered as raw
    JSON/junk in the UI instead of a readable message.

    Fixed centrally here rather than per-field: take the first error, strip
    pydantic's "Value error, " prefix (added automatically for a
    ValueError raised inside a field_validator) if present, and return a
    single clean string at 422 -- same shape as every other error response
    in this API.
    """
    first_error = exc.errors()[0]
    message = str(first_error.get("msg", "Invalid request."))
    prefix = "Value error, "
    if message.startswith(prefix):
        message = message[len(prefix):]
    return JSONResponse(status_code=422, content={"detail": message})


app.include_router(auth_router.router)
app.include_router(patients.router)
app.include_router(emergency.router)
app.include_router(ai_router.router)


@app.get("/")
def root():
    return {"status": "MediBridge API running", "docs": "/docs"}
