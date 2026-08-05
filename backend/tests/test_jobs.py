"""Job-queue tests: idempotency, retries, dead-lettering, and stall recovery.

These are the properties every later phase's ingestion, feature recomputation, and
monitoring depends on. If enqueue is not idempotent, a scheduler blip double-counts a
weather window; if a stalled job is never reclaimed, a worker crash silently strands
work and a feed goes quiet without anyone being told.
"""
from datetime import timedelta

import pytest

from app import clock, models
from app.database import SessionLocal
from app.jobs import queue, registry, schedule, worker
from app.jobs.registry import TaskError


@pytest.fixture()
def db(client):
    """A session on the freshly created test schema."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def probe():
    """A registered task whose behaviour each test controls."""
    calls = []
    state = {"raise_times": 0}

    def handler(db, payload):
        calls.append(payload)
        if state["raise_times"] > 0:
            state["raise_times"] -= 1
            raise RuntimeError("provider unavailable")
        return {"handled": len(calls)}

    registry._REGISTRY.pop("test.probe", None)
    registry.task("test.probe", max_attempts=3)(handler)
    yield {"calls": calls, "state": state}
    registry._REGISTRY.pop("test.probe", None)


# ------------------------------------------------------------------- enqueueing

def test_enqueue_creates_a_pending_job_with_registry_defaults(db, probe):
    job = queue.enqueue(db, "test.probe", {"x": 1})
    assert job.status == queue.STATUS_PENDING
    assert job.attempts == 0
    assert job.max_attempts == 3          # from the registration, not a literal
    assert job.payload == {"x": 1}


def test_enqueue_is_idempotent_within_a_live_key(db, probe):
    """A scheduler that fires twice must not produce two jobs."""
    first = queue.enqueue(db, "test.probe", {"n": 1}, idempotency_key="weather:2026-07-28T10")
    second = queue.enqueue(db, "test.probe", {"n": 2}, idempotency_key="weather:2026-07-28T10")
    assert first.id == second.id
    assert second.payload == {"n": 1}     # the original wins; the duplicate is dropped
    assert db.query(models.Job).count() == 1


def test_an_idempotency_key_is_reusable_once_the_job_is_finished(db, probe):
    """A key names a unit of work, not a job forever — tomorrow's window reuses it."""
    first = queue.enqueue(db, "test.probe", {}, idempotency_key="daily")
    job = queue.claim(db)
    queue.run_job(db, job)
    assert db.get(models.Job, first.id).status == queue.STATUS_SUCCEEDED

    second = queue.enqueue(db, "test.probe", {}, idempotency_key="daily")
    assert second.id != first.id


def test_unregistered_task_cannot_be_enqueued(db):
    """Fail at enqueue time, where the caller can see it — not later in a worker."""
    with pytest.raises(TaskError):
        queue.enqueue(db, "test.does_not_exist", {})


# ---------------------------------------------------------------------- claiming

def test_claim_returns_nothing_when_the_queue_is_empty(db):
    assert queue.claim(db) is None


def test_claim_respects_run_at(db, probe):
    later = clock.current_datetime() + timedelta(hours=1)
    queue.enqueue(db, "test.probe", {}, run_at=later)
    assert queue.claim(db) is None
    assert queue.claim(db, now=later) is not None


def test_claim_orders_by_priority_then_run_at(db, probe):
    registry._REGISTRY.pop("test.urgent", None)
    registry.task("test.urgent", priority=1)(lambda db, payload: {})
    queue.enqueue(db, "test.probe", {"which": "normal"})
    queue.enqueue(db, "test.urgent", {"which": "urgent"})

    claimed = queue.claim(db)
    assert claimed.task_name == "test.urgent"
    registry._REGISTRY.pop("test.urgent", None)


def test_claiming_marks_running_and_increments_attempts(db, probe):
    queue.enqueue(db, "test.probe", {})
    job = queue.claim(db)
    assert job.status == queue.STATUS_RUNNING
    assert job.attempts == 1
    assert job.locked_by
    # A second claim finds nothing: the job is no longer pending.
    assert queue.claim(db) is None


def test_a_job_is_claimed_by_exactly_one_worker(db, probe):
    """The atomicity that makes two workers on one database safe."""
    queue.enqueue(db, "test.probe", {})
    other = SessionLocal()
    try:
        first = queue.claim(db, claimed_by="worker-a")
        second = queue.claim(other, claimed_by="worker-b")
        assert first is not None
        assert second is None
    finally:
        other.close()


# ------------------------------------------------------------------- execution

def test_running_a_job_records_an_append_only_run(db, probe):
    queue.enqueue(db, "test.probe", {"hello": "world"})
    job = queue.claim(db)
    run = queue.run_job(db, job)

    assert run.status == queue.STATUS_SUCCEEDED
    assert run.attempt == 1
    assert run.result == {"handled": 1}
    assert run.duration_ms is not None
    assert db.get(models.Job, job.id).status == queue.STATUS_SUCCEEDED
    assert probe["calls"] == [{"hello": "world"}]


def test_a_failing_job_retries_with_backoff_then_dies(db, probe):
    """Bounded retries: a permanently broken job must stop consuming worker time."""
    probe["state"]["raise_times"] = 99
    queue.enqueue(db, "test.probe", {})

    attempts_seen = []
    for _ in range(3):
        job = queue.claim(db, now=clock.current_datetime() + timedelta(hours=2))
        assert job is not None
        run = queue.run_job(db, job)
        attempts_seen.append(run.attempt)
        assert run.status == queue.STATUS_FAILED

    final = db.query(models.Job).one()
    assert attempts_seen == [1, 2, 3]
    assert final.attempts == 3 == final.max_attempts
    assert final.status == queue.STATUS_DEAD
    assert "provider unavailable" in final.last_error
    # Dead means dead: no further claims, even far in the future.
    assert queue.claim(db, now=clock.current_datetime() + timedelta(days=7)) is None
    # Every attempt is preserved, so "did this feed struggle" is answerable.
    assert db.query(models.JobRun).count() == 3


def test_backoff_grows_and_is_capped():
    assert queue.retry_delay_seconds(1) == 30
    assert queue.retry_delay_seconds(2) == 60
    assert queue.retry_delay_seconds(3) == 120
    assert queue.retry_delay_seconds(50) == queue.RETRY_MAX_SECONDS


def test_a_job_that_fails_then_succeeds_ends_succeeded(db, probe):
    probe["state"]["raise_times"] = 1
    queue.enqueue(db, "test.probe", {})

    first = queue.claim(db)
    assert queue.run_job(db, first).status == queue.STATUS_FAILED

    second = queue.claim(db, now=clock.current_datetime() + timedelta(hours=1))
    assert queue.run_job(db, second).status == queue.STATUS_SUCCEEDED

    assert db.query(models.Job).one().status == queue.STATUS_SUCCEEDED
    assert [r.status for r in db.query(models.JobRun).order_by(models.JobRun.id)] == [
        queue.STATUS_FAILED, queue.STATUS_SUCCEEDED,
    ]


def test_a_handler_exception_does_not_poison_the_session(db, probe):
    """A raising handler must leave the session usable for the failure record itself."""
    probe["state"]["raise_times"] = 1
    queue.enqueue(db, "test.probe", {})
    job = queue.claim(db)
    queue.run_job(db, job)
    # The session still works afterwards.
    assert db.query(models.Job).count() == 1


# --------------------------------------------------------------- stall recovery

def test_stalled_jobs_are_reclaimed_after_the_timeout(db, probe):
    """The mechanism that makes delivery at-least-once rather than at-most-once."""
    queue.enqueue(db, "test.probe", {})
    job = queue.claim(db)
    assert job.status == queue.STATUS_RUNNING

    # The worker died. Nothing marks the job either way.
    much_later = clock.current_datetime() + timedelta(seconds=queue.STALLED_AFTER_SECONDS + 60)
    assert queue.reclaim_stalled(db, now=much_later) == 1

    reclaimed = db.get(models.Job, job.id)
    assert reclaimed.status == queue.STATUS_PENDING
    assert reclaimed.locked_by is None
    assert queue.claim(db, now=much_later) is not None


def test_a_healthy_running_job_is_not_reclaimed(db, probe):
    queue.enqueue(db, "test.probe", {})
    queue.claim(db)
    assert queue.reclaim_stalled(db) == 0


# ------------------------------------------------------------------- scheduling

def test_schedule_enqueues_one_job_per_time_bucket(db):
    """A tick that fires twice in the same bucket must not double-enqueue."""
    now = clock.current_datetime()
    first = schedule.enqueue_due(db, now=now)
    second = schedule.enqueue_due(db, now=now)

    assert len(first) == len(schedule.SCHEDULES)
    assert second == []
    assert db.query(models.Job).count() == len(schedule.SCHEDULES)


def test_a_succeeded_job_still_suppresses_its_own_bucket(db):
    """The bug this guards: a five-minute schedule firing on every two-second poll.

    Once the heartbeat has run and SUCCEEDED, its idempotency key is no longer live —
    so a live-only dedupe would happily enqueue another one, and another, for the rest
    of the bucket. The scheduler's key names an occurrence, so it must dedupe against
    terminal jobs too.
    """
    now = clock.current_datetime()
    schedule.enqueue_due(db, now=now)
    for job in db.query(models.Job).all():
        job.status = queue.STATUS_SUCCEEDED
    db.commit()

    assert schedule.enqueue_due(db, now=now) == []
    assert db.query(models.Job).count() == len(schedule.SCHEDULES)


def test_a_later_bucket_enqueues_again(db):
    now = clock.current_datetime()
    schedule.enqueue_due(db, now=now)
    later = now + timedelta(seconds=schedule.SCHEDULES[0].every_seconds * 2)
    assert schedule.enqueue_due(db, now=later)


def test_bucket_key_is_stable_within_a_bucket_and_changes_across_them():
    sched = schedule.Schedule("system.heartbeat", every_seconds=300)
    now = clock.current_datetime()
    assert schedule.bucket_key(sched, now) == schedule.bucket_key(sched, now + timedelta(seconds=1))
    assert schedule.bucket_key(sched, now) != schedule.bucket_key(sched, now + timedelta(seconds=600))


# ---------------------------------------------------------------------- worker

def test_worker_tick_schedules_and_drains(db):
    """The end-to-end Phase 0 proof: schedule -> enqueue -> claim -> run -> record."""
    summary = worker.tick(db, queues=("default",))

    assert summary["scheduled"] == len(schedule.SCHEDULES)
    assert summary["ran"] == len(schedule.SCHEDULES)
    assert summary["failed"] == 0
    assert db.query(models.Job).filter(models.Job.status == queue.STATUS_SUCCEEDED).count() == (
        len(schedule.SCHEDULES)
    )
    heartbeat = db.query(models.JobRun).join(models.Job).filter(
        models.Job.task_name == "system.heartbeat"
    ).one()
    assert "observed_at" in heartbeat.result


def test_worker_tick_on_an_empty_queue_is_harmless(db):
    worker.tick(db, queues=("default",))
    summary = worker.tick(db, queues=("default",))
    assert summary["ran"] == 0


def test_stats_reports_what_an_operator_needs(db, probe):
    queue.enqueue(db, "test.probe", {})
    stats = queue.stats(db)
    assert stats["total"] == 1
    assert stats["by_status"][queue.STATUS_PENDING] == 1
    assert "test.probe" in stats["registered_tasks"]


# -------------------------------------------------------------------- endpoint

def test_internal_jobs_endpoint_reports_queue_health(client):
    """Operator visibility. `dead` is the number that matters: work that silently
    stopped happening rather than visibly failing."""
    response = client.get("/internal/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["total"] == 0
    assert body["jobs"] == []
    assert "system.heartbeat" in body["stats"]["registered_tasks"]

    session = SessionLocal()
    try:
        worker.tick(session, queues=("default",))
    finally:
        session.close()

    body = client.get("/internal/jobs").json()
    assert body["stats"]["by_status"]["succeeded"] == len(schedule.SCHEDULES)
    assert body["stats"]["dead"] == 0
    heartbeat = [j for j in body["jobs"] if j["task_name"] == "system.heartbeat"][0]
    assert heartbeat["attempts"] == 1
    assert heartbeat["runs"][0]["status"] == "succeeded"


def test_internal_jobs_is_covered_by_the_operator_key_interlock(client, monkeypatch):
    """Under /internal by construction, so the path-prefix middleware guards it.

    Asserted behaviourally rather than by inspecting the route: the guarantee is that a
    route added under /internal is protected without anyone remembering to protect it.
    """
    from app import operator_key

    monkeypatch.setenv(operator_key.ENV_VAR, "secret-key")
    assert client.get("/internal/jobs").status_code == 403
    assert client.get(
        "/internal/jobs", headers={operator_key.KEY_HEADER: "secret-key"}
    ).status_code == 200
