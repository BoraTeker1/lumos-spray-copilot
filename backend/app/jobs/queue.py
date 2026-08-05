"""The queue itself: enqueue, claim, complete, fail, retry, dead-letter.

The database IS the queue. `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL lets any
number of workers claim disjoint jobs without coordination; SQLite has no SKIP LOCKED
but serialises writers anyway, so the same claim is implemented there as a guarded
conditional update whose row count tells us whether we won the race.

Three properties this module is responsible for, because nothing above it can recover
if they are wrong:

* **Idempotent enqueue.** A scheduler that fires twice, a retried webhook, or an
  operator clicking a button again must not produce two jobs. `idempotency_key` is
  unique across live jobs (partial index), and `enqueue` returns the existing job
  instead of raising.
* **At-least-once delivery, never exactly-once.** A worker that dies mid-task leaves a
  job locked; `reclaim_stalled` returns it to pending after a timeout. That means a
  handler CAN run twice on the same payload, and every handler is written accordingly.
* **Bounded retries with backoff.** A failing job retries with exponential delay up to
  `max_attempts`, then becomes `dead` and stops consuming worker time. Dead is a state
  an operator sees, not a silent drop.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app import clock, models
from app.database import IS_POSTGRES
from app.jobs import registry

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

LIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)

# Retry backoff: 30s, 60s, 120s, 240s ... capped. Deliberately short at the start —
# most failures in ingestion are a provider blipping, not a bug.
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600

# How long a claimed job may stay locked before another worker may take it. Must exceed
# the longest expected handler runtime, or two workers will run the same job on purpose.
STALLED_AFTER_SECONDS = 900


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def find_live_by_key(db, idempotency_key: str) -> models.Job | None:
    """The pending/running job carrying this key, if any.

    LIVE only. A key names a unit of work that can legitimately recur — "today's
    weather sync" is the same key tomorrow — so a finished job must not block the next
    one. Callers whose key already names a unique occurrence (the scheduler embeds the
    time bucket) want `exists_with_key` instead.
    """
    return db.execute(
        select(models.Job).where(
            models.Job.idempotency_key == idempotency_key,
            models.Job.status.in_(LIVE_STATUSES),
        )
    ).scalars().first()


def exists_with_key(db, idempotency_key: str) -> bool:
    """Has a job with this key EVER been enqueued, in any status?

    The scheduler's question. Its keys embed the time bucket, so a succeeded heartbeat
    must still suppress the next tick inside the same bucket — otherwise a five-minute
    schedule fires on every two-second poll.
    """
    return db.execute(
        select(models.Job.id).where(models.Job.idempotency_key == idempotency_key).limit(1)
    ).first() is not None


def enqueue(
    db, task_name: str, payload: dict | None = None, *,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    queue: str | None = None,
    priority: int | None = None,
    max_attempts: int | None = None,
    source_key: str | None = None,
    now: datetime | None = None,
) -> models.Job:
    """Enqueue a job, or return the live job that already carries this idempotency key.

    Defaults for queue/priority/max_attempts come from the task registration, so a
    caller only overrides when this particular enqueue is unusual.
    """
    now = now or clock.current_datetime()
    definition = registry.resolve(task_name)

    if idempotency_key:
        existing = find_live_by_key(db, idempotency_key)
        if existing is not None:
            return existing

    job = models.Job(
        queue=queue or definition.queue,
        task_name=task_name,
        payload=payload or {},
        idempotency_key=idempotency_key,
        status=STATUS_PENDING,
        priority=definition.priority if priority is None else priority,
        run_at=run_at or now,
        attempts=0,
        max_attempts=definition.max_attempts if max_attempts is None else max_attempts,
        source_key=source_key,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Another process won the race between our check and this insert. The partial
        # unique index is the real guarantee; this branch just makes losing the race
        # look like the idempotent no-op it is.
        db.rollback()
        if idempotency_key:
            existing = find_live_by_key(db, idempotency_key)
            if existing is not None:
                return existing
        raise
    db.refresh(job)
    return job


def claim(db, queues: tuple[str, ...] = ("default",), now: datetime | None = None,
          claimed_by: str | None = None) -> models.Job | None:
    """Take the next runnable job, or None. Safe to call from many workers at once."""
    now = now or clock.current_datetime()
    holder = claimed_by or worker_id()

    if IS_POSTGRES:
        row = db.execute(
            select(models.Job)
            .where(
                models.Job.status == STATUS_PENDING,
                models.Job.run_at <= now,
                models.Job.queue.in_(queues),
            )
            .order_by(models.Job.priority, models.Job.run_at, models.Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalars().first()
        if row is None:
            return None
        row.status = STATUS_RUNNING
        row.locked_at = now
        row.locked_by = holder
        row.attempts += 1
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return row

    # SQLite (and any backend without SKIP LOCKED): read a candidate, then claim it with
    # a conditional UPDATE. The rowcount is the arbiter — if another worker took it
    # first, the WHERE no longer matches and we simply look again.
    for _ in range(5):
        candidate = db.execute(
            select(models.Job)
            .where(
                models.Job.status == STATUS_PENDING,
                models.Job.run_at <= now,
                models.Job.queue.in_(queues),
            )
            .order_by(models.Job.priority, models.Job.run_at, models.Job.id)
            .limit(1)
        ).scalars().first()
        if candidate is None:
            return None
        result = db.execute(
            update(models.Job)
            .where(models.Job.id == candidate.id, models.Job.status == STATUS_PENDING)
            .values(
                status=STATUS_RUNNING, locked_at=now, locked_by=holder,
                attempts=models.Job.attempts + 1, updated_at=now,
            )
        )
        db.commit()
        if result.rowcount:
            db.refresh(candidate)
            return candidate
    return None


def start_run(db, job: models.Job, now: datetime | None = None) -> models.JobRun:
    """Open the append-only record for this attempt."""
    now = now or clock.current_datetime()
    run = models.JobRun(
        job_id=job.id, attempt=job.attempts, worker_id=job.locked_by,
        started_at=now, status=STATUS_RUNNING,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def complete(db, job: models.Job, run: models.JobRun, result: dict | None = None,
             now: datetime | None = None) -> models.Job:
    now = now or clock.current_datetime()
    run.status = STATUS_SUCCEEDED
    run.finished_at = now
    run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
    run.result = result or {}
    job.status = STATUS_SUCCEEDED
    job.finished_at = now
    job.locked_at = None
    job.locked_by = None
    job.last_error = None
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return job


def fail(db, job: models.Job, run: models.JobRun, error: str,
         now: datetime | None = None) -> models.Job:
    """Record a failed attempt, then either schedule a retry or dead-letter the job."""
    now = now or clock.current_datetime()
    run.status = STATUS_FAILED
    run.finished_at = now
    run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
    run.error = error[:4000]

    job.last_error = error[:4000]
    job.locked_at = None
    job.locked_by = None
    job.updated_at = now
    if job.attempts >= job.max_attempts:
        job.status = STATUS_DEAD
        job.finished_at = now
    else:
        job.status = STATUS_PENDING
        job.run_at = now + timedelta(seconds=retry_delay_seconds(job.attempts))
    db.commit()
    db.refresh(job)
    return job


def retry_delay_seconds(attempts: int) -> int:
    """Exponential backoff, capped. `attempts` is the number already made."""
    delay = RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1))
    return min(delay, RETRY_MAX_SECONDS)


def reclaim_stalled(db, now: datetime | None = None,
                    stalled_after_seconds: int = STALLED_AFTER_SECONDS) -> int:
    """Return jobs whose worker died back to pending. Returns how many were reclaimed.

    This is the mechanism that makes delivery at-least-once rather than at-most-once. A
    reclaimed job WILL run again having possibly already done its work, which is exactly
    why handlers must be idempotent.
    """
    now = now or clock.current_datetime()
    cutoff = now - timedelta(seconds=stalled_after_seconds)
    result = db.execute(
        update(models.Job)
        .where(models.Job.status == STATUS_RUNNING, models.Job.locked_at < cutoff)
        .values(status=STATUS_PENDING, locked_at=None, locked_by=None, updated_at=now)
    )
    db.commit()
    return int(result.rowcount or 0)


def run_job(db, job: models.Job, now: datetime | None = None) -> models.JobRun:
    """Execute one claimed job end to end, recording the attempt either way."""
    now = now or clock.current_datetime()
    run = start_run(db, job, now=now)
    try:
        definition = registry.resolve(job.task_name)
        result = definition.handler(db, job.payload or {})
    except Exception as exc:  # noqa: BLE001 - a handler may raise anything
        db.rollback()
        # Re-attach: the rollback may have expired these instances.
        job = db.get(models.Job, job.id)
        run = db.get(models.JobRun, run.id)
        fail(db, job, run, f"{type(exc).__name__}: {exc}", now=clock.current_datetime())
        return run
    complete(db, job, run, result if isinstance(result, dict) else None,
             now=clock.current_datetime())
    return run


def stats(db) -> dict:
    """Counts by status and queue, for the operator console."""
    jobs = db.execute(select(models.Job)).scalars().all()
    by_status: dict[str, int] = {}
    by_queue: dict[str, int] = {}
    for job in jobs:
        by_status[job.status] = by_status.get(job.status, 0) + 1
        by_queue[job.queue] = by_queue.get(job.queue, 0) + 1
    return {
        "total": len(jobs),
        "by_status": by_status,
        "by_queue": by_queue,
        "dead": by_status.get(STATUS_DEAD, 0),
        "registered_tasks": sorted(registry.registered()),
    }
