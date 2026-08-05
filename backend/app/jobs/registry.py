"""The task registry: names that a queued job can resolve to a function.

A job stores a task NAME, never a callable or a pickle. That is what lets a job survive
a deploy: the row enqueued by yesterday's process is run by today's code, and a task
that no longer exists fails loudly with a message an operator can act on instead of
raising an unpickling error nobody can read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class TaskError(RuntimeError):
    """Raised when a task cannot be resolved or is registered twice."""


@dataclass(frozen=True)
class TaskDef:
    name: str
    handler: Callable
    queue: str
    max_attempts: int
    priority: int
    description: str


_REGISTRY: dict[str, TaskDef] = {}


def task(
    name: str, *, queue: str = "default", max_attempts: int = 5,
    priority: int = 100, description: str = "",
):
    """Register a job handler under `name`.

    The handler is called as `handler(db, payload)` and may return a JSON-serialisable
    dict, which is recorded on the JobRun. Raising is how a handler reports failure;
    the queue decides whether that becomes a retry or a dead letter.

    Handlers must be IDEMPOTENT. The queue guarantees at-least-once delivery, never
    exactly-once: a worker that dies between doing the work and recording success will
    hand the same job to another worker. Every handler is written on the assumption that
    it may run twice on the same payload, which for ingestion means keying on
    (source, window, content hash) rather than appending blindly.
    """
    def decorator(handler: Callable) -> Callable:
        if name in _REGISTRY and _REGISTRY[name].handler is not handler:
            raise TaskError(f"task {name!r} is already registered")
        _REGISTRY[name] = TaskDef(
            name=name, handler=handler, queue=queue, max_attempts=max_attempts,
            priority=priority, description=description or (handler.__doc__ or "").strip(),
        )
        return handler
    return decorator


def resolve(name: str) -> TaskDef:
    if name not in _REGISTRY:
        raise TaskError(
            f"no task registered under {name!r} — either the job predates a rename or "
            f"its module was never imported (see app/jobs/tasks.py)"
        )
    return _REGISTRY[name]


def registered() -> dict[str, TaskDef]:
    return dict(_REGISTRY)


def is_registered(name: str) -> bool:
    return name in _REGISTRY


def _reset_for_tests() -> None:
    _REGISTRY.clear()
