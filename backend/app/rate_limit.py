"""Shared slowapi Limiter instance.

Deliberately its own module (not defined inline in app/main.py) so any
router that needs to reference it directly -- emergency.py's tighter
per-endpoint limits on the two unauthenticated scan endpoints,
auth_router.py's `@limiter.exempt` on the three routes that already have
their own bespoke, persisted-in-DB lockout logic -- can `from
..rate_limit import limiter` without a circular import against app.main
(which itself imports every router).

`default_limits=["60/minute"]` is applied automatically (via
SlowAPIMiddleware, wired up in app.main) to every route that does NOT
carry its own `@limiter.limit(...)` decorator and is NOT `@limiter.exempt`.
slowapi's default-limits mechanism does not distinguish HTTP method at the
constructor level (it applies per matched route regardless of GET vs
POST/PATCH) -- rather than hand-roll extra method-filtering middleware for
a distinction that matters little in practice, this project accepts the
default applying to GET routes too: 60/minute per IP is generous enough
that legitimate polling patterns in this app (e.g. GET
/emergency/current/{patient_id}, polled by the web console -- see
PatientDetail.jsx) are extremely unlikely to trip it, while it's still a
real backstop against a scripted abuse loop against any endpoint.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
