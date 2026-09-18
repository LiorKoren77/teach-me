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
        queue-backed runners return after the message is accepted.
        """
        ...
