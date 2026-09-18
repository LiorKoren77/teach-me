from __future__ import annotations

from uuid import UUID, uuid4

from teachme.ports.job_runner import JobHandler, JobPayload, UnknownJobKind
from teachme.repositories.jobs import JobRepository


class InProcessJobRunner:
    """Runs the handler in the calling thread. Used by the CLI and by tests.
    With a JobRepository it records queued -> running -> done|failed; without one it just runs."""

    name = "inprocess"

    def __init__(self, handlers: dict[str, JobHandler], jobs: JobRepository | None) -> None:
        self._handlers = handlers
        self._jobs = jobs

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        handler = self._handlers.get(kind)
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        if handler is None:
            if self._jobs:
                self._jobs.set_status(job_id, "failed", error=f"unknown job kind {kind!r}")
            raise UnknownJobKind(kind)
        if self._jobs:
            self._jobs.set_status(job_id, "running")
            self._jobs.increment_attempts(job_id)
        try:
            handler(payload)
        except Exception as exc:
            if self._jobs:
                self._jobs.set_status(job_id, "failed", error=str(exc))
            raise
        if self._jobs:
            self._jobs.set_status(job_id, "done")
        return job_id
