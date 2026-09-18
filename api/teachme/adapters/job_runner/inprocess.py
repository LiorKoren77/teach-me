from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from teachme.ports.job_runner import JobHandler, JobPayload, UnknownJobKind
from teachme.repositories.jobs import JobRepository


class InProcessJobRunner:
    """Runs the handler in the calling thread. Used by the CLI and by tests.
    With a JobRepository it records queued -> running -> done|failed; without one it just runs.
    commit/rollback let a caller that shares one connection between the job repository and the
    handler keep job-status writes durable, and recover from a handler that leaves the
    connection's transaction aborted."""

    name = "inprocess"

    def __init__(
        self,
        handlers: dict[str, JobHandler],
        jobs: JobRepository | None,
        commit: Callable[[], None] | None = None,
        rollback: Callable[[], None] | None = None,
    ) -> None:
        self._handlers = handlers
        self._jobs = jobs
        self._commit = commit
        self._rollback = rollback

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
            if self._commit:
                self._commit()
        try:
            handler(payload)
        except Exception as exc:
            if self._jobs:
                try:
                    if self._rollback:
                        self._rollback()
                    self._jobs.set_status(job_id, "failed", error=str(exc))
                    if self._commit:
                        self._commit()
                except Exception:
                    pass
            raise
        if self._jobs:
            self._jobs.set_status(job_id, "done")
            if self._commit:
                self._commit()
        return job_id
