from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from teachme.ingestion.pipeline import INGEST_SOURCE
from teachme.ports.job_runner import UnknownJobKind
from teachme.repositories.jobs import ClaimedJob

if TYPE_CHECKING:
    from teachme.scope import Scope


@dataclass(frozen=True)
class JobOutcome:
    """One unit of work, done. `next_job_id` names the job that carries on where this one stopped
    - the rest of an ingestion - and is None when there is nothing left to do. `status` is
    "skipped" for a delivery that found the job already claimed or finished, which is not a
    failure and not something to retry: the claim that won it is doing the work."""

    job_id: UUID
    kind: str
    status: Literal["done", "skipped"]
    next_job_id: UUID | None = None


def dispatch(scope: Scope, claimed: ClaimedJob) -> UUID | None:
    """One unit of work. An ingestion advances by exactly one step and hands the remainder to a
    new job, so a 400-page book is many short invocations instead of one that outlives the
    function's duration limit; the generation kinds are already job-sized.

    The hand-over is inline - the one place in the app where it has to be. Vercel may freeze this
    instance the moment the response goes out, so a POST left on a daemon thread would take the
    rest of the ingestion with it. It costs the runner's one-second read timeout, not the step
    the next invocation is about to run."""
    if claimed.kind == INGEST_SOURCE:
        if scope.pipeline.run_next_step(UUID(claimed.payload["source_id"])):
            return scope.job_runner.enqueue_inline(INGEST_SOURCE, claimed.payload)
        return None
    handler = scope.job_handlers.get(claimed.kind)
    if handler is None:
        raise UnknownJobKind(claimed.kind)
    handler(claimed.payload, claimed.id)
    return None


def run_job(scope: Scope, job_id: UUID) -> JobOutcome:
    """Claim one job, run one unit of it, and record what happened. What every executor does with
    a delivery, whoever delivered it: `/api/jobs/run` for the vercel_function runner and the SQS
    worker for the queue. They differ in how the job reaches them and in what they do with the
    message afterwards, never in how it is run.

    Raises `JobNotFound` for an id nobody queued, and re-raises whatever the step raised once the
    job row is marked failed - `failed` being the status a later delivery can claim again."""
    job = scope.jobs.get(job_id)
    claimed = scope.jobs.claim(job_id)
    scope.conn.commit()
    if claimed is None:
        return JobOutcome(job_id=job["id"], kind=job["kind"], status="skipped")
    try:
        next_job_id = dispatch(scope, claimed)
    except Exception as exc:
        # The step that failed has already rolled its own work back; this puts the connection in a
        # state where the job row can be written, and commits it before the error propagates.
        scope.conn.rollback()
        scope.jobs.set_status(claimed.id, "failed", error=str(exc))
        scope.conn.commit()
        raise
    scope.jobs.set_status(claimed.id, "done")
    scope.conn.commit()
    return JobOutcome(job_id=claimed.id, kind=claimed.kind, status="done", next_job_id=next_job_id)
