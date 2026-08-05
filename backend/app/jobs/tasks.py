"""Built-in tasks.

Kept deliberately tiny in Phase 0. `heartbeat` exists to prove the whole loop —
schedule, enqueue, claim, run, record — works end to end before any real workload
depends on it. `reclaim_stalled_jobs` is the self-maintenance task that makes
at-least-once delivery actually deliver.

Ingestion, feature recomputation, and monitoring tasks arrive in Phases 1-3 and register
themselves the same way.
"""
from __future__ import annotations

from app import clock
from app.jobs import queue
from app.jobs.registry import task


@task(
    "system.heartbeat",
    max_attempts=1,
    priority=200,
    description="No-op liveness check: proves the scheduler and worker loop are running.",
)
def heartbeat(db, payload: dict) -> dict:
    """Record that the worker loop is alive. Does nothing else, on purpose."""
    return {"observed_at": clock.current_datetime().isoformat(), "note": payload.get("note")}


@task(
    "system.reclaim_stalled",
    max_attempts=1,
    priority=10,
    description="Return jobs whose worker died back to the pending queue.",
)
def reclaim_stalled_jobs(db, payload: dict) -> dict:
    """Self-maintenance: without this, a worker crash silently strands its job."""
    reclaimed = queue.reclaim_stalled(db)
    return {"reclaimed": reclaimed}
