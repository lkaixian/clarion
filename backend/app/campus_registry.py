"""the University external-system integration adapter (the tender /
: "Integrate with SMP, SMS, e-klinik panel; new-patient eligibility
checks via the Registrar's system").

SMP/SMS/e-klinik-panel/the Registrar system are campus-internal systems this
environment has zero real spec, schema, or credentials for -- fabricating a
real integration against them would mean inventing the University's own internal data
shapes, the same call P4.4 made to skip a real MIMS integration (see
`healthcare/Implementation Roadmap.md`'s P4.8 changelog, 2026-09-14, which
left this a documented gap for exactly that reason).

What IS built, asked for explicitly (2026-09-15, "build a working mock
first, will show in the exhibition"): a real HTTP adapter boundary talking
to a genuine, clearly-labeled MOCK registry
(`routers/campus_registry_mock.py`) standing in for all four systems, so the
demo shows the actual integration point -- a live network call, a real
UI flow, a real advisory result -- working end-to-end. Swapping in the real
systems later is a `CAMPUS_REGISTRY_BASE_URL` env var change, zero code
change here.

Advisory only, same discipline as every AI feature in this codebase: a
down/slow/misbehaving registry must never block patient registration, so
every failure path returns a structured "unavailable" result instead of
raising.
"""
import os
from urllib.parse import quote

import httpx

# The demo mock lives in-process (routers/campus_registry_mock.py, mounted at
# /mock-campus-registry) -- no separate service to stand up/keep alive for something
# that exists only to be swapped out once real campus endpoints exist.
DEFAULT_BASE_URL = "http://127.0.0.1:8000/mock-campus-registry"
DEFAULT_TIMEOUT = 3.0


async def check_eligibility(nric: str, *, base_url: "str | None" = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Look up `nric` against the configured the University registry (the mock by
    default; point `CAMPUS_REGISTRY_BASE_URL` at a real endpoint once one
    exists). Always returns a dict, never raises -- callers render
    `available=False` as "couldn't check, proceed manually" rather than a
    hard error."""
    base = base_url or os.environ.get("CAMPUS_REGISTRY_BASE_URL", DEFAULT_BASE_URL)
    # Code review 2026-09-15: a raw f-string into the URL let a control
    # character in `nric` (tab/newline/NUL -- Starlette's default `str` path
    # converter doesn't reject these, only "/") raise httpx.InvalidURL,
    # which is NOT an httpx.HTTPError subclass -- reproduced live as an
    # unhandled 500, violating this function's own "never raises" contract.
    # quote() both encodes it safely and makes InvalidURL unreachable here.
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base.rstrip('/')}/eligibility/{quote(nric, safe='')}")
    except httpx.HTTPError as exc:
        return {"available": False, "eligible": None, "detail": f"the University registry unreachable: {exc}"}

    if resp.status_code == 404:
        return {"available": True, "eligible": False, "source": None, "detail": "Not found in the University registry"}
    if resp.status_code != 200:
        return {"available": False, "eligible": None, "detail": f"the University registry returned HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except ValueError:
        return {"available": False, "eligible": None, "detail": "the University registry returned a non-JSON response"}
    data["available"] = True
    return data
