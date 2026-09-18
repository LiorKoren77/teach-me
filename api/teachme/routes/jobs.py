from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from teachme.ingestion.pipeline import INGEST_SOURCE
from teachme.ports.job_runner import JobPayload, UnknownJobKind
from teachme.routes.deps import ScopeDep
from teachme.scope import Scope

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class RunJobRequest(BaseModel):
    """What a job runner posts back to this deployment. Only `job_id` is acted on: `kind` and
    `payload` travel for readability in a log, while the job row itself is what is run, so a body
    that disagrees with the row cannot make this endpoint do something the row does not say."""

    job_id: UUID
    kind: str = Field(default="", max_length=64)
    payload: JobPayload = Field(default_factory=dict)


class RunJobResult(BaseModel):
    """One unit of work, done. `next_job_id` names the job that carries on where this one stopped
    - the rest of an ingestion - and is null when there is nothing left to do."""

    job_id: UUID
    kind: str
    status: str
    next_job_id: UUID | None = None


def _authorize(scope: Scope, given: str | None) -> None:
    """The only guard this route has: no Clerk session, no role. A deployment with no secret
    configured cannot be called at all, rather than being open to everyone."""
    configured = scope.shared.settings.job_runner_secret
    expected = configured.get_secret_value() if configured is not None else ""
    if not expected or not given or not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="invalid job secret")


def _dispatch(scope: Scope, kind: str, payload: JobPayload) -> UUID | None:
    """One unit of work. An ingestion advances by exactly one step and hands the remainder to a
    new job, so a 400-page book is many short invocations instead of one that outlives the
    function's duration limit; the generation kinds are already job-sized."""
    if kind == INGEST_SOURCE:
        if scope.pipeline.run_next_step(UUID(payload["source_id"])):
            return scope.job_runner.enqueue(INGEST_SOURCE, payload)
        return None
    handler = scope.job_handlers.get(kind)
    if handler is None:
        raise UnknownJobKind(kind)
    handler(payload)
    return None


@router.post("/run", response_model=RunJobResult)
def run_job(
    body: RunJobRequest,
    scope: ScopeDep,
    x_job_secret: Annotated[str | None, Header()] = None,
) -> RunJobResult:
    _authorize(scope, x_job_secret)
    job = scope.jobs.get(body.job_id)  # a job id nobody queued is a 404, not a 500
    scope.jobs.set_status(job["id"], "running")
    scope.jobs.increment_attempts(job["id"])
    scope.conn.commit()
    try:
        next_job_id = _dispatch(scope, job["kind"], job["payload"])
    except Exception as exc:
        # The step that failed has already rolled its own work back; this puts the connection in a
        # state where the job row can be written, and commits it before the error propagates.
        scope.conn.rollback()
        scope.jobs.set_status(job["id"], "failed", error=str(exc))
        scope.conn.commit()
        raise
    scope.jobs.set_status(job["id"], "done")
    scope.conn.commit()
    return RunJobResult(job_id=job["id"], kind=job["kind"], status="done", next_job_id=next_job_id)
