"""Shared slowapi Limiter instance.

Deliberately its own module (not defined inline in app/main.py) so any
router that needs to reference it directly -- emergency.py's tighter
per-endpoint limits on the two unauthenticated scan endpoints,
auth_router.py's own explicit `@limiter.limit(...)` decorators on the
password/lockout endpoints that already have their own bespoke,
persisted-in-DB lockout logic (no route in this codebase uses
`@limiter.exempt` -- that design was superseded before this session, see
test_login_rate_limiting.py's own comments) -- can `from ..rate_limit
import limiter` without a circular import against app.main (which itself
imports every router).

`default_limits=["60/minute"]` is meant to apply automatically to every
route that does NOT carry its own `@limiter.limit(...)` decorator and is
NOT `@limiter.exempt`. slowapi's default-limits mechanism does not
distinguish HTTP method at the constructor level (it applies per matched
route regardless of GET vs POST/PATCH) -- rather than hand-roll extra
method-filtering middleware for a distinction that matters little in
practice, this project accepts the default applying to GET routes too:
60/minute per IP is generous enough that legitimate polling patterns in
this app (e.g. GET /emergency/current/{patient_id}, polled by the web
console -- see PatientDetail.jsx) are extremely unlikely to trip it, while
it's still a real backstop against a scripted abuse loop against any
endpoint.

**`SlowAPIMiddleware` (app.main) turned out to be a complete no-op against
this app's installed fastapi/starlette versions -- found live during P5.2
load testing.** Traced it directly: `SlowAPIMiddleware.dispatch()` calls
`slowapi.middleware._find_route_handler(app.routes, request.scope)` to
identify which endpoint matched, and on this stack that call returns
`None` for literally every route, including `/auth/login` -- so
`_should_exempt()` always sees `handler=None` and treats every request as
exempt, and the middleware's own rate check never runs at all, for ANY
route. `default_limits` has therefore never actually been enforced on any
undecorated route (dashboard/patients/pharmacy/reception/... -- most of
the API). The 3 explicitly `@limiter.limit(...)`-decorated auth/emergency/
self-registration/display routes were never affected by this -- their
check runs a completely different way, via the decorator's own wrapper
calling `_check_request_limit(..., in_middleware=False)` directly inside
the endpoint call, which doesn't go through `SlowAPIMiddleware` or
`_find_route_handler` at all. Root-caused no further than confirming
exactly where it breaks (a slowapi 0.1.10 / newer-starlette
incompatibility is the leading suspect, not this app's own code) --
fixing slowapi properly is out of scope here.

`enforce_rate_limits` below reuses that same CONFIRMED-WORKING
`in_middleware=False` path as a FastAPI dependency instead, wired globally
via `FastAPI(dependencies=[Depends(enforce_rate_limits)])` in app.main so
every route gets it without decorating each one by hand. It reads the
matched route off `request.scope["route"]` (populated by Starlette's own
router before dependencies run, so this doesn't need `_find_route_handler`
at all) and calls the exact same internal method the decorator calls,
which already handles `@limiter.exempt` and `override_defaults` correctly
on its own. `app.add_middleware(SlowAPIMiddleware)` is now dead weight
(confirmed: since `handler` is always `None`, it never even reaches its
own `X-RateLimit-*` header injection either -- the decorated routes'
headers come from the decorator's own wrapper, independently) and has
been removed from app.main; `app.add_exception_handler(RateLimitExceeded,
...)` stays, since `enforce_rate_limits` raising that exception still goes
through the normal FastAPI exception-handling path either way.

**Storage backend matters as much as the limit number.** gunicorn runs 4
worker PROCESSES (backend/Dockerfile, matching the On-Prem Architecture
pooling math). slowapi/`limits`' default storage is in-process memory --
each worker then keeps its OWN independent counter for the same key, so
the real aggregate ceiling silently becomes up to ~4x the configured
number, and *which* request gets throttled depends on which worker the
connection happened to land on. Found live during P5.2 load testing: 100
rapid wrong-password POSTs to `/auth/login` (limit "20/minute") only
started 429-ing after ~50+ attempts, not 20 -- the opposite of fail-safe
for exactly the brute-force/credential-spray case Security Audit M1 named.
`storage_uri` below points slowapi at the `redis` container this stack
already provisions (previously unused -- every worker now shares one
counter, closing the gap) when `REDIS_URL` is set, falling back to
in-memory so a plain `python -m uvicorn` / single-worker / no-Redis dev
run needs no setup change.

**`in_memory_fallback_enabled=True` is not optional.** Without it, a Redis
outage doesn't just degrade rate limiting -- it takes down the ENTIRE API.
`enforce_rate_limits` is a GLOBAL FastAPI dependency (every route runs it),
and slowapi's default behavior on a storage error (with this flag off) is
to re-raise -- turning a Redis blip into a 500 on every request site-wide,
including `GET /healthz` (whose own docstring promises liveness probes an
"unauthenticated, instant, always-cheap answer" with no dependency checks)
and the unauthenticated `emergency.py` scan endpoints, the one part of this
"Emergency-first" system explicitly designed to stay reachable no matter
what else is down. voltagent security-auditor caught this as CRITICAL
before it shipped. With the flag on, a storage failure instead falls back
to the pre-Redis in-memory-per-worker behavior (imperfect -- back to the
multi-worker undercounting above -- but functional) for the outage's
duration, then recovers automatically once Redis answers again.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    storage_uri=os.environ.get("REDIS_URL", "memory://"),
    in_memory_fallback_enabled=True,
)


async def enforce_rate_limits(request: Request) -> None:
    """FastAPI dependency, wired globally in app.main -- see the module
    docstring's "SlowAPIMiddleware turned out to be a complete no-op" note
    for why this exists instead of relying on default_limits+middleware.
    Raises slowapi.RateLimitExceeded (handled by the exception handler
    registered in app.main) when the caller is over the limit; returns
    None otherwise. A no-op for a route decorated with `@limiter.exempt`
    or that already ran its own `@limiter.limit(...)` check this request
    (`_check_request_limit` and the `_rate_limiting_complete` guard below
    both already handle that -- see slowapi.extension.Limiter).
    """
    if not limiter.enabled or getattr(request.state, "_rate_limiting_complete", False):
        return
    route = request.scope.get("route")
    limiter._check_request_limit(request, getattr(route, "endpoint", None), in_middleware=False)
    request.state._rate_limiting_complete = True
