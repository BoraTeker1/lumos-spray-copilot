"""Background jobs: a database-backed queue, a task registry, and one worker process.

Importing this package registers the built-in tasks, so anything that enqueues by name
(the API, the scheduler, a test) can resolve them without importing `tasks` itself.
"""
from app.jobs import queue, registry, schedule, tasks  # noqa: F401
from app.jobs.queue import enqueue
from app.jobs.registry import task

__all__ = ["enqueue", "task", "queue", "registry", "schedule", "tasks"]
