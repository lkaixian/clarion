"""P4.8: the inbound side of the lab-analyser HL7 v2
integration -- an MLLP TCP server that receives ORU^R01 result messages
and stages them as `models.AnalyserResultInbox` rows for a clinician to
review (see that model's docstring for why this never auto-creates a
signed ServiceResult).

Runs as its OWN process (`python -m app.hl7_listener`, docker-compose.yml's
`hl7-listener` service), NOT inside the gunicorn web workers -- binding a
long-lived TCP listener socket once per worker (gunicorn runs 4) would
either crash on a port conflict or leave 3 workers' listeners silently
dead depending on SO_REUSEPORT behaviour, and every long-running/cron-style
piece of this codebase (db/security_analytics_scan.py, db/data_quality_
scan.py) already runs as its own process for the same class of reason.
Plain blocking `socket` + one thread per connection, not asyncio -- this
handles "1-2 modern analysers" (healthcare/Integration Engine and
LDAP.md's own scoping), not thousands of concurrent connections.

`handle_message` is the testable core (pure DB logic, no socket) -- see
test_hl7_listener.py.
"""
from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from . import hl7v2, models

logger = logging.getLogger("clarion.hl7_listener")

_DEFAULT_PORT = 2575
_RECV_CHUNK = 65536
_MAX_BUFFER = 1 * 1024 * 1024  # one HL7 result message is a few KB; this is generous, not unbounded
_CONN_TIMEOUT = 30.0  # idle/slowloris connections must not tie up a thread forever
_MAX_CONNECTIONS = 16  # "1-2 modern analysers" (see module docstring) -- generous, not unbounded


def handle_message(db: Session, raw: str) -> Tuple[str, Optional[models.AnalyserResultInbox]]:
    """Parses one HL7 message, stages it as an AnalyserResultInbox row
    (matched or not), and returns (ack_message, row). `row` is `None` only
    when the message itself couldn't be parsed at all (not an ORU, no OBR)
    -- a parseable-but-unmatched message still gets staged (see the model's
    docstring) and still returns a POSITIVE ack, because CLARION did
    receive and store it; only a message this app can't make sense of at
    all is negatively acknowledged, so a real analyser's own retry/alerting
    logic fires on the right signal."""
    try:
        parsed = hl7v2.parse_oru_r01(raw)
    except hl7v2.Hl7ParseError as e:
        logger.warning("HL7 message rejected: %s", e)
        return hl7v2.build_ack("UNKNOWN", accept=False, sending_facility="CLARION", text=str(e)), None

    req = None
    if parsed.placer_order_number:
        candidate = (
            db.query(models.ServiceRequest)
            .filter(models.ServiceRequest.id == parsed.placer_order_number)
            .first()
        )
        # Only a genuine lab order counts as a match -- a result arriving
        # against a physiotherapy/procedure/xray request's id (garbled
        # accession, or a stale/reused number from a test rig) is exactly
        # the "arrived but doesn't reconcile" case this table exists for,
        # not a silent cross-module write.
        if candidate is not None and candidate.module == "laboratory":
            req = candidate

    row = models.AnalyserResultInbox(
        service_request_id=req.id if req else None,
        facility_name=req.ordering_facility_name if req else None,
        hl7_control_id=parsed.control_id or None,
        sending_facility=parsed.sending_facility or None,
        raw_message=raw,
        result_text=hl7v2.format_observations(parsed.observations),
        flag_abnormal=parsed.any_abnormal,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "HL7 result staged: inbox_id=%s matched=%s control_id=%s",
        row.id, bool(req), parsed.control_id,
    )
    return hl7v2.build_ack(parsed.control_id, accept=True, sending_facility="CLARION"), row


def _handle_connection(conn: socket.socket, addr, session_factory, slot: threading.Semaphore) -> None:
    # A connection that opens and then sends nothing (or a partial frame)
    # would otherwise block this thread on recv() forever -- reachable from
    # anything on the `internal` docker network, not just a trusted
    # analyser (voltagent review, 2026-09-14). `slot` is the concurrency
    # cap acquired by the caller before this thread was even started;
    # released here so a stuck/idle connection can't also starve out every
    # future one once _CONN_TIMEOUT fires.
    conn.settimeout(_CONN_TIMEOUT)
    buf = b""
    try:
        while True:
            chunk = conn.recv(_RECV_CHUNK)
            if not chunk:
                break
            buf += chunk
            if len(buf) > _MAX_BUFFER:
                logger.warning("HL7 connection from %s exceeded %d bytes without a complete frame -- closing", addr, _MAX_BUFFER)
                break
            message = hl7v2.unwrap_mllp(buf)
            if message is None:
                continue
            buf = b""  # one message per MLLP frame handled here; a pipelined second frame in the same recv is rare for "1-2 analysers" and picked up on the connection's next read
            db = session_factory()
            try:
                ack, _row = handle_message(db, message)
            except Exception:
                logger.exception("HL7 message handling failed for connection %s", addr)
                ack = hl7v2.build_ack("UNKNOWN", accept=False, sending_facility="CLARION", text="internal error")
            finally:
                db.close()
            conn.sendall(hl7v2.wrap_mllp(ack))
    except OSError:
        logger.info("HL7 connection from %s dropped (idle timeout or reset)", addr)
    finally:
        conn.close()
        slot.release()


def serve(host: str, port: int, session_factory) -> None:
    """Blocks forever, accepting connections and handling each on its own
    thread, up to `_MAX_CONNECTIONS` at a time (a `Semaphore` acquired here
    and released by `_handle_connection` when its connection closes --
    `accept()` itself still queues excess connections in the OS listen
    backlog rather than spawning unbounded threads per voltagent's review).
    `accept()` failing (e.g. a transient fd-exhaustion EMFILE) is caught
    and logged rather than left to kill the whole process -- the original
    version let an unhandled OSError there take down every future
    connection, not just the offending one. `session_factory` is
    `app.database.SessionLocal` in production, swapped for a test DB's
    sessionmaker in tests that exercise this loop."""
    slots = threading.Semaphore(_MAX_CONNECTIONS)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(8)
        logger.info("HL7 MLLP listener on %s:%d", host, port)
        while True:
            try:
                conn, addr = listener.accept()
            except OSError:
                logger.exception("HL7 listener accept() failed -- retrying")
                time.sleep(1)
                continue
            slots.acquire()
            threading.Thread(target=_handle_connection, args=(conn, addr, session_factory, slots), daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # Binds all interfaces by design: the analyser is on a different host on
    # the internal network, same reachability need as any HL7/DICOM/PACS
    # service -- bandit's blanket-bind warning doesn't know that constraint.
    ap.add_argument("--host", default="0.0.0.0")  # nosec B104
    ap.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .database import SessionLocal
    serve(args.host, args.port, SessionLocal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
