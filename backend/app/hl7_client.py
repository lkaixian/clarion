"""P4.8: outbound MLLP client -- pushes an ORM^O01 order to the configured
lab analyser. Thin, synchronous, best-effort: analyser
connectivity is optional (CLARION_HL7_ANALYSER_HOST unset = disabled), and
this module never decides what a failed push means for the caller -- see
routers/ancillary.py::create_service_request, which catches `Hl7PushError`
and logs rather than failing order creation. The order already exists in
CLARION regardless of whether the analyser happened to be reachable right
now, same "advisory, never blocks the primary workflow" rule as
thumbnail generation / AI features elsewhere in this codebase.
"""
from __future__ import annotations

import os
import socket
from typing import Optional

from . import hl7v2

_DEFAULT_TIMEOUT = 5.0
_DEFAULT_PORT = 2575  # the conventional HL7-over-MLLP port


class Hl7PushError(Exception):
    """The analyser is unset, unreachable, or the connection failed."""


def _host() -> Optional[str]:
    return os.environ.get("CLARION_HL7_ANALYSER_HOST") or None


def _port() -> int:
    try:
        return int(os.environ.get("CLARION_HL7_ANALYSER_PORT", str(_DEFAULT_PORT)))
    except ValueError:
        return _DEFAULT_PORT


def _timeout() -> float:
    try:
        return float(os.environ.get("CLARION_HL7_ANALYSER_TIMEOUT", str(_DEFAULT_TIMEOUT)))
    except ValueError:
        return _DEFAULT_TIMEOUT


def enabled() -> bool:
    return _host() is not None


def push_order(message: str) -> None:
    """Sends one already-built HL7 message over MLLP. Raises `Hl7PushError`
    on any failure -- this function does NOT swallow errors itself, so a
    caller that needs to know (a manual "test connectivity" action, tests)
    still can; it's the caller's job to decide whether a failure here
    should be fatal (see module docstring: for order creation, it never
    is)."""
    host = _host()
    if host is None:
        raise Hl7PushError("CLARION_HL7_ANALYSER_HOST is not set")
    try:
        with socket.create_connection((host, _port()), timeout=_timeout()) as sock:
            sock.sendall(hl7v2.wrap_mllp(message))
            sock.settimeout(_timeout())
            sock.recv(65536)  # the ACK -- not parsed/validated, fire-and-forget
    except OSError as e:
        raise Hl7PushError(str(e)) from e
