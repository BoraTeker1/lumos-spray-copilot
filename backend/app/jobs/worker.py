"""The worker process: one loop, one database, no orchestration platform.

    python -m app.jobs.worker                 # run until interrupted
    python -m app.jobs.worker --once          # drain what is runnable now and exit
    python -m app.jobs.worker --queues ingest # only this queue

Each tick: enqueue anything the schedule is due for, then claim and run jobs until the
queue is empty, then sleep. A second worker on the same database is safe and is how this
scales — the claim is atomic, so two workers never run the same job concurrently (a
worker that DIES mid-job is a different case, handled by `reclaim_stalled`).

Deliberately not a daemon framework: no supervisor, no plugin system, no distributed
lock service. When this stops being enough, `app/jobs/queue.py` is the seam to replace,
and no handler has to change.
"""
from __future__ import annotations

import argparse
import logging
import signal
import time

from app import clock
from app.database import SessionLocal
from app.jobs import queue, schedule, tasks  # noqa: F401  (importing tasks registers them)

logger = logging.getLogger("lumos.worker")

_should_stop = False


def _handle_signal(signum, frame):  # pragma: no cover - signal path
    global _should_stop
    _should_stop = True
    logger.info("worker: received signal %s, finishing current job then stopping", signum)


def tick(db, queues: tuple[str, ...], drain: bool = True) -> dict:
    """One scheduling+draining pass. Returns a small summary for logs and tests."""
    scheduled = schedule.enqueue_due(db)
    ran, succeeded, failed = 0, 0, 0
    while True:
        job = queue.claim(db, queues=queues)
        if job is None:
            break
        run = queue.run_job(db, job)
        ran += 1
        if run.status == queue.STATUS_SUCCEEDED:
            succeeded += 1
        else:
            failed += 1
            logger.warning("worker: job %s (%s) failed: %s", job.id, job.task_name, run.error)
        if not drain:
            break
    return {
        "scheduled": len(scheduled), "ran": ran,
        "succeeded": succeeded, "failed": failed,
    }


def run_forever(queues: tuple[str, ...], poll_seconds: float = 2.0) -> None:  # pragma: no cover
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    logger.info("worker: started at %s on queues %s", clock.current_datetime(), queues)
    while not _should_stop:
        db = SessionLocal()
        try:
            summary = tick(db, queues)
            if summary["ran"]:
                logger.info("worker: %s", summary)
        except Exception:  # noqa: BLE001 - a loop that dies on one bad tick is useless
            logger.exception("worker: tick failed")
        finally:
            db.close()
        if not _should_stop:
            time.sleep(poll_seconds)
    logger.info("worker: stopped")


def main(argv=None) -> int:  # pragma: no cover - process entry point
    parser = argparse.ArgumentParser(description="Lumos background job worker")
    parser.add_argument("--once", action="store_true", help="drain the queue once and exit")
    parser.add_argument("--queues", default="default", help="comma-separated queue names")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    queues = tuple(q.strip() for q in args.queues.split(",") if q.strip())

    if args.once:
        db = SessionLocal()
        try:
            summary = tick(db, queues)
            logger.info("worker: %s", summary)
        finally:
            db.close()
        return 0

    run_forever(queues, poll_seconds=args.poll_seconds)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
