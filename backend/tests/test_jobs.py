"""P1.7b — app/jobs.py: the generic async job queue's claim/dispatch/retry
logic (the background worker THREAD itself is not exercised here — these
drive run_pending() directly, deterministically, one call at a time)."""
import pytest

from app import jobs, models


@pytest.fixture(autouse=True)
def _clean_handlers(db_session):
    """jobs.register() is normally called once at import time (derived.py);
    tests that register their own throwaway kind must not leak it into
    other tests or fight over prime_thumbnail's real handler.

    Also drains any pending rows left by OTHER test files (e.g. a medicine-
    photo or document-upload test enqueues a real prime_thumbnail job, and
    with the background worker stopped for this whole session — see
    conftest.py — nothing else ever claims it). _claim_one orders by
    created_at, so a leftover row would otherwise be exactly what the next
    run_pending() call here claims instead of this test's own job."""
    while jobs.run_pending(db_session):
        pass
    before = dict(jobs._HANDLERS)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(before)


def _job_row(db_session, job_id):
    return db_session.query(models.Job).filter_by(id=job_id).first()


def test_enqueue_and_run_pending_success(db_session):
    seen = []
    jobs.register("test_ok", lambda payload: seen.append(payload))

    job = jobs.enqueue(db_session, "test_ok", {"x": 1})
    assert job.status == "pending"

    assert jobs.run_pending(db_session) is True
    assert seen == [{"x": 1}]
    assert _job_row(db_session, job.id).status == "done"

    # queue now empty
    assert jobs.run_pending(db_session) is False


def test_missing_handler_fails_immediately(db_session):
    job = jobs.enqueue(db_session, "no_such_kind", {})
    jobs.run_pending(db_session)
    row = _job_row(db_session, job.id)
    assert row.status == "failed"
    assert "no handler" in row.error


def test_failing_handler_retries_then_fails(db_session):
    def _boom(payload):
        raise ValueError("nope")

    jobs.register("test_fail", _boom)
    job = jobs.enqueue(db_session, "test_fail", {})

    for expected_attempts in range(1, jobs.MAX_ATTEMPTS + 1):
        # a "pending" job (attempts < MAX_ATTEMPTS) must be re-claimable —
        # re-enqueue isn't needed, the same row goes back to pending.
        db_session.refresh(job)
        assert job.status == "pending"
        jobs.run_pending(db_session)
        db_session.refresh(job)
        assert job.attempts == expected_attempts
        assert "nope" in job.error

    assert job.status == "failed"


def test_payload_round_trips_through_json(db_session):
    seen = []
    jobs.register("test_payload", lambda payload: seen.append(payload))
    jobs.enqueue(db_session, "test_payload", {"bucket": "b", "key": "k/1.jpg", "sha256": None})
    jobs.run_pending(db_session)
    assert seen == [{"bucket": "b", "key": "k/1.jpg", "sha256": None}]


def test_claim_is_exclusive_not_repeatable(db_session):
    """A row already flipped to "running" must not be claimable again --
    this is the actual race two gunicorn worker processes could otherwise
    hit (voltagent security review, 2026-09-16): both poll the same oldest
    pending row at once, and only one of their claim UPDATEs may win."""
    jobs.register("test_exclusive", lambda payload: None)
    job = jobs.enqueue(db_session, "test_exclusive", {})

    first = jobs._claim_one(db_session)
    assert first is not None and first.id == job.id

    second = jobs._claim_one(db_session)
    assert second is None  # already "running" -- not claimable a second time


def test_stale_running_job_is_reclaimed(db_session):
    """A row stuck in "running" (its worker process crashed mid-job) must
    become claimable again once it's old enough to presume abandoned --
    otherwise it is invisible to every future poll forever."""
    from datetime import datetime, timedelta, timezone

    jobs.register("test_stale", lambda payload: None)
    job = jobs.enqueue(db_session, "test_stale", {})
    jobs._claim_one(db_session)  # -> running

    row = _job_row(db_session, job.id)
    assert row.status == "running"
    row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=jobs._STALE_RUNNING_SECONDS + 1)
    db_session.commit()

    reclaimed = jobs._claim_one(db_session)
    assert reclaimed is not None and reclaimed.id == job.id


def test_prime_thumbnail_kind_is_registered_at_import_time():
    # app.derived is imported transitively by app.main (via routers) well
    # before this test runs — its module-level jobs.register() call must
    # have already run.
    assert "prime_thumbnail" in jobs._HANDLERS
