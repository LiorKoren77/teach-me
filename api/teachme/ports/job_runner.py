from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

JobPayload = dict[str, Any]
JobHandler = Callable[[JobPayload], None]


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
