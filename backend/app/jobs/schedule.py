"""Periodic work: what should be enqueued, how often, and how not to double-fire.

There is no cron daemon and no APScheduler here. The worker calls `enqueue_due` on every
tick, and each schedule's idempotency key contains the time bucket it belongs to — so a
tick that fires twice, a worker that restarts, or two workers running at once all
produce exactly one job per bucket. The dedupe lives in the same transaction as the
insert, which a separate scheduler process could not guarantee.

Bucketing is deliberately coarse (the interval itself). A five-minute schedule produces
at most one job per five-minute wall-clock bucket, never "one every five minutes since
the process started" — the latter drifts and double-fires across restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app import clock
from app.jobs import queue


@dataclass(frozen=True)
class Schedule:
    task_name: str
    every_seconds: int
    payload: dict | None = None
    source_key: str | None = None


# Phase 0 schedules. Real ingestion, feature, and monitoring schedules land in later
# phases; this list is what proves the loop works.
SCHEDULES: tuple[Schedule, ...] = (
    Schedule("system.heartbeat", every_seconds=300, payload={"note": "scheduled"}),
    Schedule("system.reclaim_stalled", every_seconds=300),
)


def bucket_key(schedule: Schedule, now: datetime) -> str:
    """A stable key naming the time bucket this firing belongs to."""
    epoch_seconds = int(now.timestamp())
    bucket = epoch_seconds // max(1, schedule.every_seconds)
    return f"schedule:{schedule.task_name}:{schedule.every_seconds}:{bucket}"


def enqueue_due(db, now: datetime | None = None, schedules=None) -> list:
    """Enqueue one job per schedule per time bucket. Idempotent within a bucket."""
    now = now or clock.current_datetime()
    enqueued = []
    for schedule in (schedules if schedules is not None else SCHEDULES):
        key = bucket_key(schedule, now)
        # ANY status, not just live: a heartbeat that already ran and succeeded inside
        # this bucket must still suppress the next tick, or a five-minute schedule fires
        # on every two-second poll. The key already names the occurrence, so it is never
        # legitimately reused.
        if queue.exists_with_key(db, key):
            continue
        enqueued.append(queue.enqueue(
            db, schedule.task_name, schedule.payload or {},
            idempotency_key=key, source_key=schedule.source_key, now=now,
        ))
    return enqueued
