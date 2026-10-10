import contextlib
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

# Loaded as early as possible, before anything (email_service in
# particular) reads MAILTRAP_* / other env vars, so a local backend/.env
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
# the console uvicorn is already running in.
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
# the whole app over e.g. "DEBGU" would be a bad trade. Validate first and
# fall back to INFO with a warning printed straight to stderr (the logging
# config itself isn't up yet at this point, so a real logger call here
# would be silently lost).
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if _LOG_LEVEL not in _VALID_LOG_LEVELS:
    print(f"[main] Ignoring invalid LOG_LEVEL={_LOG_LEVEL!r} -- falling back to INFO.")
    _LOG_LEVEL = "INFO"

# P5.1: LOG_FORMAT=json switches every log line to one JSON object (request
# id / user id / role / facility bound via app.log_context, never PHI) --
# what Promtail/Loki actually want. Was previously plain
# `logging.basicConfig(format=...)` with a "single-process local dev/demo
# backend, not a service with log aggregation to wire up" comment -- P5.1
# is exactly that wiring, so this revisits that call. Default stays plain
# text: a JSON stream is unpleasant to read directly in a dev terminal, and
# nothing before this needed structured logs. docker-compose.yml sets
# LOG_FORMAT=json for the real stack.
from . import log_context  # noqa: E402

_LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").strip().lower()
_log_handler = logging.StreamHandler()
_log_handler.addFilter(log_context.ContextFilter())
if _LOG_FORMAT == "json":
    _log_handler.setFormatter(log_context.JsonFormatter())
else:
    if _LOG_FORMAT not in ("text", ""):
        print(f"[main] Ignoring invalid LOG_FORMAT={_LOG_FORMAT!r} -- falling back to text.")
    _log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"
    ))
logging.basicConfig(level=_LOG_LEVEL, handlers=[_log_handler])

import sqlalchemy
from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import inspect

from fastapi import Depends

from . import auth, jobs
from .database import engine, DB_BACKEND
from .rate_limit import limiter, enforce_rate_limits
from .storage import BUCKET_DOCUMENTS, get_object_store
from .routers import auth_router, patients, emergency, ai_router, appointments, admin, staff, self_registration, reception, pharmacy, consultation, display, profile, pdpa, ancillary, pacs, dental, billing, reporting, dashboard, fhir, campus_registry_mock, federation, auth_security

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

# P1.7b: one background worker thread per process, polling the `jobs` table
# (see app/jobs.py). Every router import above already ran its module-level
# jobs.register(...) calls (derived.py's), so a handler is always registered
# before this can claim a row. Safe under gunicorn's multi-worker import --
# each worker gets its own thread, and MariaDB's SKIP LOCKED claim keeps them
# from double-running the same job.
jobs.start_worker_thread()

app = FastAPI(
    title="CLARION API",
    description="Emergency-first, interoperable health record continuity system.",
    version="0.1.0",
    # P5.2: enforce_rate_limits (app/rate_limit.py) applies the shared
    # Limiter's default_limits to every route globally -- see that module's
    # docstring for why this replaced SlowAPIMiddleware (a confirmed no-op
    # against this app's fastapi/starlette versions).
    dependencies=[Depends(enforce_rate_limits)],
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
# instance, the enforce_rate_limits dependency wired above, and
# default-limit rationale). Individual routes opt out via @limiter.exempt
# (the three password/lockout endpoints in auth_router.py that already
# have their own stricter, persisted-in-DB lockout logic) or override with
# their own @limiter.limit(...) (the two unauthenticated emergency-scan
# endpoints in emergency.py, tighter than the 60/minute default).
# app.state.limiter is still set for slowapi's own internals (it reads
# app.state.limiter in a couple of code paths); SlowAPIMiddleware itself is
# NOT registered here -- see rate_limit.py's docstring: it was a confirmed
# no-op on this app's fastapi/starlette versions (_find_route_handler never
# matched any route), so enforce_rate_limits above replaces it entirely.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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


@app.middleware("http")
async def _request_id_middleware(request, call_next):
    """P5.1: bind a request id BEFORE anything else runs (auth, CORS,
    rate-limit, the route itself), so every log line for this request --
    including one from a CORS rejection or a 401 that never reaches a
    route -- carries the same id via app.log_context.ContextFilter, and the
    caller gets it back in X-Request-Id to quote when reporting an issue.
    Registered via @app.middleware AFTER _security_headers_middleware
    above, which in Starlette's stack makes it the LAST added and so the
    OUTERMOST layer -- it runs first on the way in and last on the way out,
    ahead of CORS/SlowAPI (both added earlier via add_middleware)."""
    request_id = log_context.new_request_id()
    log_context.bind_request(request_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
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
    their own registered handlers and never reach here.

    P5.1: the id returned here is now the SAME one _request_id_middleware
    bound for this request (previously a second, unrelated uuid minted
    here) -- every other log line for this request already carries it via
    log_context.ContextFilter, so a user-reported id now finds the whole
    request's log trail, not just this one ERROR line."""
    request_id = log_context.current_request_id()
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
app.include_router(auth_security.router)
app.include_router(
    patients.router,
    dependencies=[Depends(auth.require_page_access("patients"))],
)
app.include_router(emergency.router)
# Federation gates itself per route: staff routes need the patients page, the
# peer route is authenticated by an Ed25519 signature instead of a user.
app.include_router(federation.router)
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
# Saved digital signature (POST/GET/DELETE /me/signature -- own signature only;
# nobody else's image is ever served). NOT page-gated.
app.include_router(profile.router)
# Public, unauthenticated waiting-room display feed (GET /display/{token}).
# Deliberately NO auth dependency and NOT under require_page_access -- a
# login-less screen device renders it; the token is the only credential and
# what it exposes is low-sensitivity (queue numbers + masked names).
app.include_router(display.router)
# PDPA (P2.10): a patient's own consent ledger + data-subject requests, and
# the DPO / records-officer handling workflow. Patient-facing routes -- NOT
# page-gated (like profile.py); staff routes carry their own require_roles.
app.include_router(pdpa.router)
# Ancillary engine (P3.1): Procedure / Laboratory / X-ray / Physiotherapy,
# one shared order -> result -> sign-off pipeline (routers/ancillary.py).
app.include_router(
    ancillary.router,
    dependencies=[Depends(auth.require_page_access("ancillary"))],
)
# PACS / DICOM imaging (P4.7): sits on the X-ray ancillary module's own
# ServiceRequest scoping (routers/pacs.py) -- same page gate, no new page.
app.include_router(
    pacs.router,
    dependencies=[Depends(auth.require_page_access("ancillary"))],
)
# Dental module (P3.2): the tooth-chart engine (routers/dental.py) --
# everything else the clause asks for reuses an existing router unchanged.
app.include_router(
    dental.router,
    dependencies=[Depends(auth.require_page_access("dental"))],
)
# Billing (P3.3): charge master / bills / payments / claims
# (routers/billing.py) -- facility-local only, no cross-facility read mode.
app.include_router(
    billing.router,
    dependencies=[Depends(auth.require_page_access("billing"))],
)
# Reporting (P3.6/P3.7): canned reports + Custom Report Builder + MOH
# notifiable-disease reporting (routers/reporting.py) -- facility-local
# only, same as billing.
app.include_router(
    reporting.router,
    dependencies=[Depends(auth.require_page_access("reporting"))],
)
# Management Dashboard (P3.8): KPI summary + patient-flow forecast +
# operational health score (routers/dashboard.py) -- facility-local only.
app.include_router(
    dashboard.router,
    dependencies=[Depends(auth.require_page_access("dashboard"))],
)
# Read-only FHIR façade (P4.2): re-projects the same clinical
# tables the `patients` page reads -- same gate, no new page.
app.include_router(
    fhir.router,
    dependencies=[Depends(auth.require_page_access("patients"))],
)
# MOCK stand-in for the University's SMP/SMS/e-klinik-panel/Registrar systems (P4.8's
# documented gap, filled in as a demo mock 2026-09-15 -- see
# routers/campus_registry_mock.py's module docstring). Deliberately NOT
# page-gated -- see that router's own docstring for why.
app.include_router(campus_registry_mock.router)


@app.get("/")
def root():
    return {"status": "CLARION API running", "docs": "/docs"}


@app.get("/app/version")
def app_version():
    """Mobile update check. Public (no PHI, nothing per-user): the app calls
    it on launch and compares against its own version. `latest` drives the
    soft "update available" prompt; `min_supported` (optional) drives a
    blocking one. Bump CLARION_APP_LATEST_VERSION when a new APK is
    published to /get-app."""
    return {
        "latest": os.environ.get("CLARION_APP_LATEST_VERSION", "1.6.0"),
        "min_supported": os.environ.get("CLARION_APP_MIN_VERSION", ""),
        "download_url": os.environ.get("CLARION_APP_DOWNLOAD_URL", "/get-app"),
    }


@app.get("/healthz", include_in_schema=False)
def healthz():
    """P5.1 liveness: this process is up and can handle a request at all --
    no dependency checks (that's /readyz below). No auth: this is what the
    container healthcheck (Dockerfile, docker-compose.yml) and an
    orchestrator's liveness probe hit, and both need an unauthenticated,
    instant, always-cheap answer. Replaces the previous placeholder probe
    of GET / (see the Dockerfile/docker-compose.yml comments this closes)."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz(response: Response):
    """P5.1 readiness: can this instance actually serve real traffic right
    now? Checks the two dependencies almost every endpoint needs:

      - database: a real `SELECT 1` round-trip (SQLite or MariaDB alike).
      - object_store: MinIO/local-disk reachability (documents, medicine
        photos, derived thumbnails all need it).

    Deliberately NOT checked: Redis -- docker-compose.yml provisions it
    ("Wiring hints for the ObjectStore / cache work") but no app code
    actually uses it yet, so gating readiness on it would be readiness
    theater. Also not checked: Orthanc/PACS -- a DICOM-viewer outage
    already degrades gracefully per-request (pacs.py's own 503s) without
    needing the whole app pulled from load-balancer rotation over it. Add
    either back here if that ever changes.

    No auth (same reasoning as /healthz -- a probe-friendly endpoint can't
    require a bearer token) and no exception text in the body -- an
    unauthenticated caller only ever sees ok/fail per check, never a
    connection string or stack trace. Also blocked at the edge
    (proxy/Caddyfile's `@backend_diag` -> 404 on `/api/readyz`) since it
    still reveals infra shape (DB/storage up or down) an anonymous internet
    caller has no reason to see -- see /metrics' own comment below for why
    "not under /api" alone doesn't achieve that.
    """
    checks = {"database": _check_database(), "object_store": _check_object_store()}
    ok = all(checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "unavailable", "checks": checks}


_STATUS_TTL_S = 5.0
_status_cache: dict = {"at": 0.0, "body": None}

# Rolling latency history per probe (this process only; ~10 min at the 5 s
# cache), so the status page can say what "normal" looks like for each part.
_STATUS_HISTORY_LEN = 120
_status_history: dict = {}


def _with_baseline(name: str, comp: dict) -> dict:
    """Record an up probe's latency and attach its typical (median) and p95
    over the recent window. Needs >= 5 samples before it claims a baseline."""
    from collections import deque
    hist = _status_history.setdefault(name, deque(maxlen=_STATUS_HISTORY_LEN))
    if comp.get("status") == "up" and comp.get("ms") is not None:
        hist.append(comp["ms"])
    if len(hist) >= 5:
        vals = sorted(hist)
        comp["typical_ms"] = vals[len(vals) // 2]
        comp["p95_ms"] = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
        comp["samples"] = len(vals)
    return comp


def _timed(check) -> dict:
    t0 = time.perf_counter()
    ok = check()
    return {"status": "up", "ms": round((time.perf_counter() - t0) * 1000)} if ok else {"status": "down"}


def _check_cache() -> dict:
    url = os.environ.get("REDIS_URL", "")
    if not url.startswith("redis"):
        return {"status": "disabled"}  # rate limiting is in-process on this node
    def ping() -> bool:
        try:
            import redis
            return bool(redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1).ping())
        except Exception:  # noqa: BLE001 -- any failure means "down", never crash the probe
            return False
    return _timed(ping)


def _check_local_ai() -> dict:
    from .ai import local_llm
    if not local_llm.local_llm_enabled():
        return {"status": "disabled"}
    def ping() -> bool:
        try:
            import httpx
            return httpx.get(local_llm._base_url() + "/api/tags", timeout=1.0).status_code == 200
        except Exception:  # noqa: BLE001
            return False
    return _timed(ping)


def _db_probe(fn) -> bool:
    """Run `fn(db)` on a short-lived session; True unless it raises."""
    from .database import SessionLocal
    db = SessionLocal()
    try:
        fn(db)
        return True
    except Exception:  # noqa: BLE001 -- a failing probe is "down", never a crash
        return False
    finally:
        db.close()


def _api_checks() -> list:
    """The pieces behind "the API", each a cheap read-only probe, so the status
    page can say WHICH part is unhealthy instead of one general answer. Status
    + latency only -- no counts, no row data."""
    from . import models, mpi_client

    def signin(db):
        db.query(models.User.id).limit(1).first()
        auth.create_access_token({"sub": "status-probe", "role": "probe"})

    def jobs_ok(db):
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        if db.query(models.Job.id).filter(models.Job.status == "pending", models.Job.created_at < cutoff).first():
            raise RuntimeError("jobs backlog")  # work has been waiting > 5 min

    probes = [
        ("signin", "Sign-in", signin),
        ("records", "Patient records", lambda db: db.query(models.Patient.id).limit(1).first()),
        ("emergency", "Emergency card lookup", lambda db: db.query(models.EmergencyToken.id).limit(1).first()),
        ("queue", "Queue & appointments", lambda db: db.query(models.QueueTicket.id).limit(1).first()),
        ("jobs", "Background jobs", jobs_ok),
    ]
    out = []
    for cid, label, fn in probes:
        comp = _with_baseline(f"api.{cid}", _timed(lambda fn=fn: _db_probe(fn)))
        out.append({"id": cid, "label": label, **comp})

    if mpi_client.enabled():
        def central() -> bool:
            try:
                import httpx
                return httpx.get(os.environ["MPI_BASE_URL"].rstrip("/") + "/healthz", timeout=1.5).status_code == 200
            except Exception:  # noqa: BLE001
                return False
        comp = _with_baseline("api.federation", _timed(central))
    else:
        comp = {"status": "disabled"}
    out.append({"id": "federation", "label": "Hospital network sync", **comp})
    return out


@app.get("/status", include_in_schema=False)
def public_status():
    """Public component status for the website's status page. Booleans and
    latencies only -- no hostnames, versions, error text or counts. Cached
    for a few seconds per worker so polling can't fan out into dependency
    checks (the local-AI probe makes an outbound call)."""
    now = time.monotonic()
    if _status_cache["body"] is not None and now - _status_cache["at"] < _STATUS_TTL_S:
        return _status_cache["body"]
    t_api = time.perf_counter()
    api_checks = _api_checks()
    api_ms = round((time.perf_counter() - t_api) * 1000)
    api_down = any(c["status"] == "down" for c in api_checks)
    components = {
        # The process answered, so the API is "up"; a failing sub-check makes it "degraded".
        "api": {"status": "degraded" if api_down else "up", "ms": api_ms, "checks": api_checks},
        "database": _with_baseline("database", _timed(_check_database)),
        "object_store": _with_baseline("object_store", _timed(_check_object_store)),
        "cache": _with_baseline("cache", _check_cache()),
        "local_ai": _with_baseline("local_ai", _check_local_ai()),
    }
    # Local AI is optional (every AI feature falls back without it), so it never degrades the whole.
    core = ("api", "database", "object_store", "cache")
    body = {"status": "ok" if all(components[k]["status"] not in ("down", "degraded") for k in core) else "degraded", "components": components}
    _status_cache.update(at=now, body=body)
    _record_status(components)
    return body

_STATUS_RECORD_EVERY_S = 60.0
_status_recorded_at = 0.0


def _record_status(components: dict) -> None:
    """Fold one probe round into today's per-component counters. Throttled to
    one write per minute per process; never raises (status must not break on
    its own bookkeeping)."""
    global _status_recorded_at
    now = time.monotonic()
    if now - _status_recorded_at < _STATUS_RECORD_EVERY_S:
        return
    _status_recorded_at = now
    from datetime import datetime, timezone
    from sqlalchemy.exc import IntegrityError
    from . import models
    from .database import SessionLocal
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        for name, comp in components.items():
            if comp.get("status") == "disabled":
                continue
            bad = 1 if comp.get("status") in ("down", "degraded") else 0
            for _ in range(2):  # insert race between workers -> retry as update
                q = db.query(models.StatusDaily).filter_by(day=day, component=name)
                if q.update({"total": models.StatusDaily.total + 1, "bad": models.StatusDaily.bad + bad}):
                    break
                try:
                    db.add(models.StatusDaily(day=day, component=name, total=1, bad=bad))
                    db.flush()
                    break
                except IntegrityError:
                    db.rollback()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


@app.get("/status/history", include_in_schema=False)
def public_status_history(days: int = 90):
    """Per-day sample counts for the status page's uptime bars. Public;
    aggregates only. `days` is clamped to 1..90."""
    from datetime import datetime, timedelta, timezone
    from . import models
    from .database import SessionLocal
    days = max(1, min(days, 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        rows = db.query(models.StatusDaily).filter(models.StatusDaily.day >= since).all()
    finally:
        db.close()
    out: dict = {}
    for r in rows:
        out.setdefault(r.component, {})[r.day] = {"total": r.total, "bad": r.bad}
    return {"days": days, "components": out}


@app.on_event("startup")
def _start_status_sampler() -> None:
    """Sample health once a minute even when nobody has the status page open,
    so the 90-day bars reflect real uptime rather than visitor traffic."""
    if os.environ.get("CLARION_STATUS_SAMPLER", "1") != "1":
        return
    import threading

    def loop() -> None:
        while True:
            time.sleep(_STATUS_RECORD_EVERY_S)
            try:
                public_status()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=loop, name="status-sampler", daemon=True).start()



def _check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 -- any failure means "not ready", never crash the probe
        return False


def _check_object_store() -> bool:
    try:
        # exists() on a key that (almost certainly) doesn't exist returns
        # False without raising -- only a real backend/connection failure
        # raises ObjectStoreError, which is exactly what this wants to
        # detect. Never creates or reads real data.
        get_object_store().exists(BUCKET_DOCUMENTS, "__readyz_probe__")
        return True
    except Exception:  # noqa: BLE001 -- any failure means "not ready", never crash the probe
        return False


# P5.1: Prometheus metrics at /metrics -- meant for the internal/
# observability Docker network only (where Prometheus itself scrapes it).
# NOTE (review finding, 2026-09-15): "/metrics isn't under /api" does NOT by
# itself keep this off the public site -- proxy/Caddyfile's
# `handle_path /api/*` strips the /api prefix and forwards WHATEVER remains
# verbatim, so a bare GET /api/metrics would reach this route exactly like
# any real API route, same as GET /api/readyz would reach /readyz below.
# The actual block is at the edge: proxy/Caddyfile has an explicit
# `@backend_diag path /api/metrics /api/readyz` -> 404 BEFORE its
# `handle_path /api/*` catch-all. include_in_schema=False keeps this out of
# /docs (it's not part of the API contract) -- unrelated to the edge block.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
