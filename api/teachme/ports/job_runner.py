from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

JobPayload = dict[str, Any]
# The job's own id travels with the payload: a handler that has to survive being delivered twice
# records what it decided on that row, and reads it back on the second delivery.
JobHandler = Callable[[JobPayload, UUID], None]


class UnknownJobKind(Exception):
    pass


class JobRunner(Protocol):
    name: str

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        """Record the job and hand it to the executor. Returns the job id.

        The in-process runner executes synchronously and re-raises handler errors;
        queue-backed runners return after the message is accepted. The hand-over itself may
        outlive this call - `vercel_function` posts on a thread nobody waits for - which is what
        keeps an upload from waiting on it.
        """
        ...

    def enqueue_inline(self, kind: str, payload: JobPayload) -> UUID:
        """`enqueue`, but the hand-over is finished before this returns.

        For a caller that cannot be sure it will still be running afterwards: a serverless
        instance may be frozen the moment its response goes out, and a POST still on a thread
        then never leaves it. The price is the hand-over's own timeout, not the job's duration.
        """
        ...

    def deliver(self, job_id: UUID, kind: str, payload: JobPayload) -> None:
        """Hand a job row that already exists to the executor, inline. What a re-delivery is:
        `enqueue` is this plus the row."""
        ...
