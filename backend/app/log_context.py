"""P5.1 — structured logging context: contextvars-based request/user binding
consumed by main.py's JSON formatter + request-id middleware, and set by
auth.py once a bearer token resolves to a user.

Why contextvars and not threading a request_id/current_user through every
`logger.info(...)` call site: this codebase already has ~50 routers' worth
of ad-hoc log statements, and updating every one to accept and pass those
values would be a huge, error-prone diff for a purely observability-driven
change. A contextvar set once per request (request-id in the request-id
middleware, user/role/facility once auth resolves in
auth.py::_resolve_current_user) makes every subsequent log line in that
request carry them for free via the Filter below, with zero call-site
changes anywhere else in the codebase. Stdlib only (`contextvars` +
`logging.Filter`/`Formatter`) -- no dependency needed for this.

Never put PHI here: request_id/user_id/role/facility are identifiers, not
clinical content, matching the "never log PHI/OTP/token/raw NRIC OCR"
line in healthcare/On-Prem Architecture.md's Observability section.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid

_request_id: "contextvars.ContextVar[str]" = contextvars.ContextVar("request_id", default="-")
_user_id: "contextvars.ContextVar[str]" = contextvars.ContextVar("log_user_id", default="-")
_role: "contextvars.ContextVar[str]" = contextvars.ContextVar("log_role", default="-")
_facility: "contextvars.ContextVar[str]" = contextvars.ContextVar("log_facility", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def bind_request(request_id: str) -> None:
    """Called once, at the very start of the request-id middleware in
    main.py -- before auth (or anything else) runs, so even a request that
    never reaches a route (a CORS rejection, a rate limit, a 401) gets a
    consistent id in its own log lines."""
    _request_id.set(request_id)


def bind_user(user_id: str, role: str, facility: "str | None") -> None:
    """Called once auth.py::_resolve_current_user has a real user, so every
    log statement for the rest of THIS request/task carries who made it."""
    _user_id.set(user_id)
    _role.set(role)
    _facility.set(facility or "-")


def current_request_id() -> str:
    """The active request's id, or "-" outside of a request (e.g. a
    startup-time log line, or a background scan script that never binds
    one). Used by main.py's unhandled-exception handler so the id it shows
    the caller is the SAME id every log line for that request already
    carries, instead of minting a second, unrelated one."""
    return _request_id.get()


class ContextFilter(logging.Filter):
    """Attached to the app's log handler in main.py -- stamps every
    LogRecord with the current request's id/user/role/facility (or "-"
    outside a request). A Filter, not a LoggerAdapter, because it needs to
    apply to every logger in the process (nric_ocr.py, ai_router.py, every
    router's own `logger = logging.getLogger(...)`) without each of them
    switching to a per-request adapter instance they don't have."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.user_id = _user_id.get()
        record.role = _role.get()
        record.facility = _facility.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line -- what Promtail/Loki actually want (P5.1).
    Deliberately flat and small: this is a log line, not an event schema."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "role": getattr(record, "role", "-"),
            "facility": getattr(record, "facility", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str: a stray non-JSON-native arg (e.g. a Decimal/UUID
        # someone %-formats into a log message) must never crash logging
        # itself -- fall back to str() rather than raise mid-request.
        return json.dumps(payload, default=str)
