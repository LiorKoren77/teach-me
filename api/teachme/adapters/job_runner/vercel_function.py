from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx

from teachme.ports.job_runner import JobPayload
from teachme.repositories.jobs import JobRepository

log = logging.getLogger(__name__)

# The POST only has to be accepted, not answered: the invocation that receives it does the work
# and may take minutes. Connecting must succeed - a wrong base url or a refused secret is a real
# failure - but reading need not: a read timeout means the request was delivered and is still
# being served, which is the normal case rather than an error.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, write=5.0, read=1.0, pool=5.0)


def daemon_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class VercelFunctionJobRunner:
    """Hands a job to another invocation of this same deployment.

    A serverless function has no worker to hand work to, so it calls itself: the job row is
    created and committed here, then `POST {base_url}/api/jobs/run` starts a second invocation
    that performs one unit of work and enqueues the next. The POST goes out on a daemon thread
    and is never waited for, so the request that uploaded a file returns immediately.

    `mark_failed` records a POST that never landed. It exists because by then this request's
    pooled connection may already be back in the pool and serving someone else, so the failure
    needs a connection of its own; without one, `jobs` is used directly, which is right for the
    CLI and for tests where enqueue is synchronous."""

    name = "vercel_function"

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        jobs: JobRepository | None,
        client: Any | None = None,
        commit: Callable[[], None] | None = None,
        mark_failed: Callable[[UUID, str], None] | None = None,
        spawn: Callable[[Callable[[], None]], None] = daemon_thread,
        timeout: Any = DEFAULT_TIMEOUT,
    ) -> None:
        if not base_url:
            raise ValueError("vercel_function job runner needs a base url to call itself back on")
        if not secret:
            raise ValueError("vercel_function job runner needs a shared secret")
        self._url = f"{base_url.rstrip('/')}/api/jobs/run"
        self._secret = secret
        self._jobs = jobs
        self._client = client or httpx.Client()
        self._commit = commit
        self._mark_failed = mark_failed
        self._spawn = spawn
        self._timeout = timeout

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        if self._commit:
            self._commit()
        body = {"job_id": str(job_id), "kind": kind, "payload": payload}
        self._spawn(lambda: self._post(job_id, body))
        return job_id

    def _post(self, job_id: UUID, body: dict[str, Any]) -> None:
        try:
            response = self._client.post(
                self._url, json=body, headers={"x-job-secret": self._secret}, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.ReadTimeout:
            return
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.warning("could not hand job %s to %s: %s", job_id, self._url, error)
            self._record_failure(job_id, error)

    def _record_failure(self, job_id: UUID, error: str) -> None:
        try:
            if self._mark_failed is not None:
                self._mark_failed(job_id, error)
            elif self._jobs is not None:
                self._jobs.set_status(job_id, "failed", error=error)
                if self._commit:
                    self._commit()
        except Exception:
            log.exception("could not record job %s as failed", job_id)
