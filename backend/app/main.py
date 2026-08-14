import os
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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import inspect, text

from . import models
from .database import engine
from .rate_limit import limiter
from .routers import auth_router, patients, emergency, ai_router, appointments, admin, staff

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

    existing_audit_log_columns = set()
    if "audit_logs" in inspector.get_table_names():
        existing_audit_log_columns = {col["name"] for col in inspector.get_columns("audit_logs")}

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
            or "password_changed_at" not in existing_user_columns
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
        or ("audit_logs" in inspector.get_table_names() and (
            "actor_facility" not in existing_audit_log_columns
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
            # Added for JWT revocation-on-password-change (POST /auth/login,
            # auth._resolve_current_user). Nullable/additive -- existing rows
            # get password_changed_at=NULL, which auth._resolve_current_user
            # treats as "no watermark, don't reject" so this migration itself
            # doesn't force-logout every already-issued token; only an
            # actual subsequent password change (via _apply_new_password)
            # starts revoking tokens issued before it.
            if "password_changed_at" not in existing_user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_changed_at DATETIME"))

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

    # Added so GET /patients/{id}/audit-log can show WHERE a staff actor
    # accessed from, snapshotted at access time (see AuditLog's class
    # docstring for why this is a snapshot and not a live join, unlike the
    # actor's display name). Nullable/additive; existing rows just get
    # actor_facility=NULL (no snapshot exists for accesses logged before
    # this column existed).
    if "audit_logs" in inspector.get_table_names():
        with engine.begin() as conn:
            if "actor_facility" not in existing_audit_log_columns:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN actor_facility VARCHAR"))


_migrate_lightweight()

app = FastAPI(
    title="MediBridge API",
    description="Emergency-first, interoperable health record continuity system.",
    version="0.1.0",
)

# CORS_ALLOWED_ORIGINS: comma-separated list of real origins (e.g.
# "https://app.example.com,https://staff.example.com") to lock this down
# before any real deployment. Left unset (or APP_ENV=demo), this defaults
# to allow_origins=["*"] -- the "just works for judging" convenience this
# project has always had, appropriate for a not-yet-deployed hackathon/demo
# app but NOT for anything handling real patient data on the open internet.
# Once you deploy for real: set CORS_ALLOWED_ORIGINS to your actual web/
# mobile origins AND set APP_ENV to anything other than "demo" (or leave it
# unset -- see the condition below), so a forgotten/blank env var doesn't
# silently fall back to wide-open CORS in production.
_app_env = os.environ.get("APP_ENV", "").strip().lower()
_demo_mode = os.environ.get("DEMO_MODE", "").strip().lower()
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()

if _cors_origins_env:
    allow_origins = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
elif _app_env == "demo" or _demo_mode == "demo" or (not _app_env and not _demo_mode):
    # Preserves today's default behavior: unset APP_ENV/DEMO_MODE (this
    # project's status quo -- not yet deployed) or an explicit "demo" value
    # both mean "wide open, judging-friendly".
    allow_origins = ["*"]
else:
    # APP_ENV/DEMO_MODE explicitly set to something other than "demo" but no
    # CORS_ALLOWED_ORIGINS provided -- fail safe to "no origins allowed"
    # rather than silently falling back to "*" in what's been flagged as a
    # non-demo environment.
    allow_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    # No cookies are used anywhere in this app (JWT is sent via the
    # Authorization header, never a cookie) -- allow_credentials=True bought
    # nothing here and is exactly what forces Starlette's CORS middleware
    # into permissive origin-reflection behavior even when allow_origins is
    # locked down to a real list. False is correct and strictly tighter.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (slowapi -- see app/rate_limit.py for the shared Limiter
# instance and default-limit rationale). Individual routes opt out via
# @limiter.exempt (the three password/lockout endpoints in auth_router.py
# that already have their own stricter, persisted-in-DB lockout logic) or
# override with their own @limiter.limit(...) (the two unauthenticated
# emergency-scan endpoints in emergency.py, tighter than the 60/minute
# default).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def _security_headers_middleware(request, call_next):
    """Minimal, framework-agnostic security headers on every response.
    Deliberately does NOT set a Content-Security-Policy here -- this API
    returns JSON for almost every route (a CSP is meant to constrain a
    browser rendering HTML/JS/CSS from this origin, which basically never
    happens here); a CSP is far more relevant to web/'s own hosting layer
    (the React app's index.html), which is out of scope for this
    backend-only pass."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # HSTS only makes sense (and is only safe) over an actual HTTPS
    # connection -- sending it over plain HTTP local dev would tell a
    # browser to force HTTPS for this host, which is actively harmful when
    # there's no HTTPS dev server to redirect to. Checks both the direct
    # connection scheme and X-Forwarded-Proto (set by a reverse proxy/load
    # balancer terminating TLS in front of a plain-HTTP backend process,
    # the common real-deployment shape).
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    if is_https:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


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
app.include_router(appointments.router)
app.include_router(admin.router)
app.include_router(staff.router)


@app.get("/")
def root():
    return {"status": "MediBridge API running", "docs": "/docs"}
