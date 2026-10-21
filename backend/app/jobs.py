"""P1.7b -- generic async job queue.

Backs the ``jobs`` table (``models.Job``). A handler registers itself by
``kind`` (see ``derived.py``'s ``prime_thumbnail`` registration); a caller
enqueues a row instead of calling the heavy function inline, so an upload's
HTTP response no longer waits on it. One background thread per process polls
for pending rows and runs them -- started from ``main.py``'s startup hook.

Deliberately a MariaDB/SQLite table, not Redis/rq/Celery (Redis is
provisioned in this stack, but a PHP CI4 port has neither it nor Celery) --
plain SQL, re-implements as a cron/worker script on the ported stack
unchanged. The claim in :func:`_claim_one` is a single conditional
``UPDATE ... WHERE id = :id AND status = :expected`` -- atomic on both
dialects without needing MariaDB's ``SKIP LOCKED`` or a SQLite-only file
lock (the two techniques this codebase's other cross-process contention
points -- ``main.py``'s ``_schema_lock`` / ``audit.py``'s
``_cross_process_chain_lock`` -- each reach for separately): a concurrent
claimant's own UPDATE only succeeds if the row is still in the expected
state at the instant *its* statement runs, so gunicorn's 4 worker
processes (each running their own copy of the poll loop below, per
``main.py``'s per-process ``start_worker_thread()``) can never both flip
the same row to "running".
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import models
from .database import SessionLocal

logger = logging.getLogger("clarion.jobs")

MAX_ATTEMPTS = 3
_POLL_INTERVAL_SECONDS = 2.0

# A "running" row older than this is presumed abandoned by a process that
# crashed mid-job (OOM/SIGKILL between the claim commit and the result
# commit) and becomes claimable again -- otherwise it would sit invisible
# to every future poll forever, since _claim_one only ever looked at
# "pending" rows.
_STALE_RUNNING_SECONDS = 300

_HANDLERS: dict[str, Callable[[dict], None]] = {}
# Per-kind retry policy. Default = the original behaviour (3 tries, retried on the next
# poll). A kind that talks to the outside world registers a longer, spaced policy so a
# network or gateway outage delays the work instead of failing it for good.
_MAX_ATTEMPTS: dict[str, int] = {}
_RETRY_DELAY: dict[str, int] = {}


class PermanentFailure(Exception):
    """Raised by a handler when retrying cannot help: the job is failed immediately."""


def register(kind: str, handler: Callable[[dict], None], *, max_attempts: int = MAX_ATTEMPTS,
             retry_delay_seconds: int = 0) -> None:
    """Register the function that runs a job of this ``kind``. Call at
    module import time (see ``derived.py``) -- a kind with no handler fails
    every job enqueued under it rather than silently no-op'ing."""
    _HANDLERS[kind] = handler
    _MAX_ATTEMPTS[kind] = max_attempts
    _RETRY_DELAY[kind] = retry_delay_seconds


def enqueue(db, kind: str, payload: dict) -> models.Job:
    """Queue a job and commit it immediately -- the row must be visible to
    the worker thread's own DB session, not just this request's pending
    transaction."""
    job = models.Job(kind=kind, payload=json.dumps(payload))
    db.add(job)
    db.commit()
    return job


def _claimable_filter():
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=_STALE_RUNNING_SECONDS)
    pending = models.Job.status == "pending"
    for kind, delay in _RETRY_DELAY.items():
        if delay:  # a retry (attempts > 0) waits `delay` seconds after its last failure
            pending = pending & ~((models.Job.kind == kind) & (models.Job.attempts > 0)
                                  & (models.Job.updated_at >= now - timedelta(seconds=delay)))
    return pending | (
        (models.Job.status == "running") & (models.Job.updated_at < stale_cutoff)
    )


def _claim_one(db) -> "models.Job | None":
    """Pick the oldest claimable row, then atomically flip it to "running"
    -- the UPDATE re-checks :func:`_claimable_filter` at the instant it
    runs, so a second caller racing on the SAME candidate (another
    process's poll loop; see the module docstring) always finds 0 rows
    matched and returns None instead of double-claiming it."""
    candidate = (
        db.query(models.Job.id)
        .filter(_claimable_filter())
        .order_by(models.Job.created_at)
        .first()
    )
    if candidate is None:
        return None
    claimed = (
        db.query(models.Job)
        .filter(models.Job.id == candidate.id, _claimable_filter())
        .update({"status": "running"}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        return None
    return db.query(models.Job).filter(models.Job.id == candidate.id).first()


def _run_one(db, job: models.Job) -> None:
    handler = _HANDLERS.get(job.kind)
    if handler is None:
        job.status = "failed"
        job.error = f"no handler registered for kind={job.kind!r}"
        db.commit()
        logger.error("job %s: %s", job.id, job.error)
        return
    try:
        handler(json.loads(job.payload))
    except PermanentFailure as exc:
        job.attempts += 1
        job.error = str(exc)[:2000]
        job.status = "failed"
        db.commit()
        logger.error("job %s (%s) failed permanently: %s", job.id, job.kind, exc)
        return
    except Exception as exc:  # noqa: BLE001 - a bad job must never crash the worker loop
        job.attempts += 1
        job.error = str(exc)[:2000]
        job.status = "pending" if job.attempts < _MAX_ATTEMPTS.get(job.kind, MAX_ATTEMPTS) else "failed"
        db.commit()
        logger.warning("job %s (%s) failed attempt %d: %s", job.id, job.kind, job.attempts, exc)
        return
    job.status = "done"
    db.commit()


def run_pending(db) -> bool:
    """Claim and run one pending job. Returns False if the queue was empty."""
    job = _claim_one(db)
    if job is None:
        return False
    _run_one(db, job)
    return True


_stop_event = threading.Event()
_worker_thread: "threading.Thread | None" = None


def _worker_loop() -> None:
    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            ran = run_pending(db)
        except Exception:
            logger.exception("job worker iteration failed")
            ran = False
        finally:
            db.close()
        if not ran:
            _stop_event.wait(_POLL_INTERVAL_SECONDS)


def start_worker_thread() -> None:
    """Idempotent -- safe to call once per process (main.py startup)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="clarion-jobs", daemon=True)
    _worker_thread.start()


def stop_worker_thread() -> None:
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=_POLL_INTERVAL_SECONDS + 1)
