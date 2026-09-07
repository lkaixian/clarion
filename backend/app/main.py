import contextlib
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Loaded as early as possible, before anything (email_service in
# particular) reads MAILGUN_* / other env vars, so a local backend/.env
# file works the same as real environment variables in a deployment. A
# missing .env is fine -- load_dotenv() just no-ops.
load_dotenv()

# No app-wide logging config existed before this -- every `logger.info`/
# `logger.warning`/`logger.exception` call under app/ (nric_ocr.py's OCR
# fallback warnings, self_registration.py's verify-photos outcome log,
# etc.) was silently dropped: Python's root logger defaults to WARNING
# with no handler attached, and uvicorn only configures ITS OWN
# uvicorn.*/uvicorn.access loggers, not the app's. This makes every
# "clarion.*"-named (and any other) logger's INFO+ output actually reach
# the console uvicorn is already running in. Deliberately basicConfig, not
# a dictConfig/handler-per-module setup -- this is a single-process local
# dev/demo backend, not a service with log aggregation to wire up.
#
# Level is read from LOG_LEVEL (env var or backend/.env, defaulting to
# INFO) rather than hardcoded, so switching to DEBUG for a one-off
# debugging session (e.g. nric_ocr.py's raw Tesseract OCR text, which logs
# at DEBUG specifically because it's sensitive card-text output -- see
# that module) is a console-only change, no source edit needed: e.g.
# `$env:LOG_LEVEL="DEBUG"` (PowerShell) before starting uvicorn, then unset
# / close that shell afterward to go back to INFO.
#
# Unlike SECRET_KEY/OTP_HMAC_KEY elsewhere in this file (deliberately
# fail-closed with no fallback -- those are security-critical), an invalid
# LOG_LEVEL is just a typo in a cosmetic dev-convenience setting -- crashing
# the whole app over e.g. "DEBGU" would be a bad trade. logging.basicConfig
# raises ValueError for anything not a known level name, so validate first
# and fall back to INFO with a warning printed straight to stderr (the
# logging config itself isn't up yet at this point, so a real logger call
# here would be silently lost).
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if _LOG_LEVEL not in _VALID_LOG_LEVELS:
    print(f"[main] Ignoring invalid LOG_LEVEL={_LOG_LEVEL!r} -- falling back to INFO.")
    _LOG_LEVEL = "INFO"
logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import inspect

from fastapi import Depends

from . import auth
from .database import engine, DB_BACKEND
from .rate_limit import limiter
from .routers import auth_router, patients, emergency, ai_router, appointments, admin, staff, self_registration, reception, pharmacy, consultation, display, profile

# Schema management (P1.5): Alembic is the single source of schema truth. The
# old startup path -- create_all() plus a ~400-line hand-rolled
# _migrate_lightweight() that ran ALTER TABLE on every boot -- is gone
# (Security Audit M9: uncontrolled DDL as the app user on a shared server).
_IS_SQLITE = DB_BACKEND == "sqlite"


@contextlib.contextmanager
def _schema_lock():
    """Serialise :func:`_ensure_schema` across processes. gunicorn imports this
    module in every worker; without this, 4 workers race ``alembic upgrade`` on
    one SQLite file and corrupt it (tables land, ``alembic_version`` doesn't).
    POSIX + SQLite only -- MariaDB only verifies, and local dev is single-process."""
    if not _IS_SQLITE:
        yield
        return
    try:
        import fcntl
    except ImportError:  # Windows dev
        yield
        return
    db_path = engine.url.database or "clarion.db"
    lock_path = Path(db_path).resolve().parent / ".clarion_schema.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _ensure_schema() -> None:
    """Make sure the connected database is at the current Alembic head.

    - Non-SQLite (production MariaDB): the deploy runs `alembic upgrade head`
      with the `clarion_migrate` account *before* this process starts. Here we
      only VERIFY, and refuse to serve otherwise -- the runtime account is
      DML-only and must never issue DDL.
    - SQLite (demo): bring a fresh or already-Alembic-managed file up to head
      automatically. A *pre-Alembic* `clarion.db` (tables present, no
      `alembic_version`) is refused rather than blind-stamped -- those files
      were built by the retired `create_all` and carry real constraint drift
      (missing FK `ondelete`, missing UNIQUEs). Rebuild it: `rm clarion.db`
      then `python seed.py`.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    with _schema_lock():
        _ensure_schema_locked(cfg, head)


def _ensure_schema_locked(cfg, head) -> None:
    from alembic import command
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_tables = bool(inspect(conn).get_table_names())

    if current == head:
        return

    if not _IS_SQLITE:
        raise RuntimeError(
            f"Database schema is at revision {current!r}, expected head {head!r}. "
            "Run `alembic upgrade head` with the clarion_migrate account before "
            "starting the app. See docs/deployment.md (MariaDB cutover)."
        )

    if current is None and has_tables:
        raise RuntimeError(
            "backend/clarion.db predates Alembic (has tables but no alembic_version) "
            "and cannot be trusted to match the current schema. For a clean demo DB: "
            "`rm backend/clarion.db && python backend/seed.py`."
        )

    logging.getLogger("clarion.schema").info(
        "Bringing SQLite schema up to Alembic head %s.", head)
    command.upgrade(cfg, "head")


_ensure_schema()

app = FastAPI(
    title="CLARION API",
    description="Emergency-first, interoperable health record continuity system.",
    version="0.1.0",
)

# Browser CORS. Precedence:
#   1. CORS_ALLOWED_ORIGINS set  -> exactly that comma-separated allowlist
#      (e.g. "https://clarion.example.edu.my"). This is the real-deployment path.
#   2. else APP_ENV=demo / DEMO_MODE in {demo,1,true}  -> allow_origins=["*"]
#      (local dev + judging). This is now an EXPLICIT opt-in.
#   3. else (nothing configured, or a non-demo APP_ENV with no allowlist)
#      -> allow_origins=[] : fail CLOSED. A cross-origin SPA is blocked until
#      one of the above is set. (Security Audit M3 -- an unconfigured deploy
#      must not silently get wide-open CORS.)
# Same-origin setups (the web/ container's nginx /api proxy) need none of
# this -- the browser call is same-origin so CORS never engages.
_app_env = os.environ.get("APP_ENV", "").strip().lower()
_demo_mode = os.environ.get("DEMO_MODE", "").strip().lower()
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
_is_demo = _app_env == "demo" or _demo_mode in ("demo", "1", "true")
_cors_log = logging.getLogger("clarion.cors")

if _cors_origins_env:
    allow_origins = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
elif _is_demo:
    allow_origins = ["*"]
    _cors_log.warning(
        "CORS is wide open (allow_origins=['*']) because APP_ENV/DEMO_MODE=demo. "
        "Set CORS_ALLOWED_ORIGINS and APP_ENV=production before any real deployment."
    )
else:
    allow_origins = []
    _cors_log.warning(
        "CORS disabled (allow_origins=[]): no CORS_ALLOWED_ORIGINS set and "
        "APP_ENV/DEMO_MODE is not 'demo'. Cross-origin browser calls will be "
        "blocked -- set CORS_ALLOWED_ORIGINS for a real deployment, or "
        "APP_ENV=demo for local cross-origin dev. (Same-origin /api proxy needs neither.)"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    # P2.5 (Security Audit M4) introduced ONE cookie: the HttpOnly refresh
    # token POST /auth/login sets (see auth_router.py's
    # _set_refresh_cookie). Every other authenticated call is still a
    # Bearer header, unaffected by this setting either way. Credentialed
    # CORS is spec-forbidden with a wildcard origin (`allow_origins=["*"]`)
    # -- browsers reject the combination outright -- so this is True ONLY
    # when an explicit, real allowlist is configured (the actual-deployment
    # path); the demo wildcard and fail-closed-empty paths both get False,
    # which means the refresh cookie simply isn't sent/received on a
    # cross-origin call in either of those modes (e.g. the rotating
    # trycloudflare-tunnel demo) -- the browser silently drops it, so that
    # mode degrades to "re-login when the 15-minute access token expires"
    # rather than misbehaving. Same-origin setups (the web/ container's
    # nginx /api proxy) need none of this either way -- no CORS preflight,
    # no credentials mode, the cookie just works.
    allow_credentials=bool(_cors_origins_env),
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


_unhandled_log = logging.getLogger("clarion.unhandled")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Code-review follow-up 2026-09-07: previously there was no app-wide handler for an
    unhandled exception -- Starlette's default logged a bare traceback to
    stdout and returned a 500, so a failing endpoint (pharmacy stock
    conflict blowing up, self-registration, an emergency path) was
    effectively invisible unless someone was tailing the container logs and
    happened to catch it.

    This logs every unhandled exception at ERROR with the full traceback,
    the request method + path, and a short correlation id, then returns that
    id to the caller in a clean `{"detail": ..., "request_id": ...}` 500 --
    the exception text itself is never sent to the client. An operator can
    grep the logs for the id a user reports.

    HTTPException / RequestValidationError / RateLimitExceeded are handled by
    their own registered handlers and never reach here."""
    request_id = uuid.uuid4().hex[:12]
    _unhandled_log.error(
        "unhandled exception [%s] on %s %s",
        request_id, request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


# Per-facility, admin-configurable page-access control (see
# app/permissions.py + models.RolePagePermission). auth.require_page_access
# is applied at ROUTER level here -- NOT per endpoint -- so it's an
# additional gate layered on top of each route's own require_roles(...)
# without touching every route. It's a no-op for admin (all pages) and for
# non-configurable roles (patient / emergency_responder), so the
# patient-facing / self-service routes that live on the patients + reception
# routers stay reachable by a patient token. Deliberately NOT applied to
# auth_router (login/me), emergency (unauthenticated), staff (clock-in/out
# -- any staff), or admin (already admin-only).
app.include_router(auth_router.router)
app.include_router(
    patients.router,
    dependencies=[Depends(auth.require_page_access("patients"))],
)
app.include_router(emergency.router)
app.include_router(
    ai_router.router,
    # AI tools are clinical -- same gate as the patient record itself.
    dependencies=[Depends(auth.require_page_access("patients"))],
)
app.include_router(
    appointments.router,
    # Appointments hang off a patient record and carry clinical context
    # (reason, precaution_notes, fasting instructions) -- same gate as the
    # record itself and as ai_router. A patient token is unaffected (patient
    # is outside CONFIGURABLE_STAFF_ROLES, so require_page_access is a no-op
    # for it) so own-record self-service (request-reschedule) keeps working;
    # a pharmacist / receptionist without the `patients` page no longer
    # reaches any appointment endpoint. Code-review follow-up 2026-09-07.
    dependencies=[Depends(auth.require_page_access("patients"))],
)
app.include_router(admin.router)
app.include_router(staff.router)
# Self-service patient registration (NRIC-OCR identity verification, see
# routers/self_registration.py's module docstring).
app.include_router(self_registration.router)
# Reception desk check-in + queue number system.
app.include_router(
    reception.router,
    dependencies=[Depends(auth.require_page_access("reception"))],
)
# Pharmacy stock endpoints (routers/pharmacy.py).
app.include_router(
    pharmacy.router,
    dependencies=[Depends(auth.require_page_access("pharmacy"))],
)
# Clinician "Start session" (clock-in + claim-a-room in one step) + the
# per-room consultation worklist and sign-off. Gated on the `patients` page
# -- a clinician's default page set is now ["patients"] only (see
# app/permissions.py::DEFAULT_ROLE_PAGES); admin / records_officer also hold
# it. reception.py does NOT import consultation.py, so consultation.py
# reusing reception's helpers is cycle-free.
app.include_router(
    consultation.router,
    dependencies=[Depends(auth.require_page_access("patients"))],
)
# Saved digital signature (POST/GET/DELETE /me/signature, GET
# /staff/{id}/signature). Registered plainly like staff.py -- "for yourself"
# plus one facility-scoped colleague read; NOT page-gated.
app.include_router(profile.router)
# Public, unauthenticated waiting-room display feed (GET /display/{token}).
# Deliberately NO auth dependency and NOT under require_page_access -- a
# login-less screen device renders it; the token is the only credential and
# what it exposes is low-sensitivity (queue numbers + masked names).
app.include_router(display.router)


@app.get("/")
def root():
    return {"status": "CLARION API running", "docs": "/docs"}
