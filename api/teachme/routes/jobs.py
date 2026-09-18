from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from teachme.ports.job_runner import JobPayload
from teachme.routes.deps import ScopeDep
from teachme.scope import Scope
from teachme.services.job_execution import run_job as run_one_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class RunJobRequest(BaseModel):
    """What a job runner posts back to this deployment. Only `job_id` is acted on: `kind` and
    `payload` travel for readability in a log, while the job row itself is what is run, so a body
    that disagrees with the row cannot make this endpoint do something the row does not say."""

    job_id: UUID
    kind: str = Field(default="", max_length=64)
    payload: JobPayload = Field(default_factory=dict)


class RunJobResult(BaseModel):
    """`JobOutcome` on the wire. See `teachme.services.job_execution`."""

    job_id: UUID
    kind: str
    status: str
    next_job_id: UUID | None = None


def _authorize(scope: Scope, given: str | None) -> None:
    """The only guard this route has: no Clerk session, no role. A deployment with no secret
    configured cannot be called at all, rather than being open to everyone."""
    configured = scope.shared.settings.job_runner_secret
    expected = configured.get_secret_value() if configured is not None else ""
    # Compared as bytes: `compare_digest` refuses two `str`s unless both are ASCII, and a header
    # is whatever the caller sent, so comparing strings would turn a wrong secret into a 500.
    if not expected or not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid job secret")


@router.post("/run", response_model=RunJobResult)
def run_job(
    body: RunJobRequest,
    scope: ScopeDep,
    x_job_secret: Annotated[str | None, Header()] = None,
) -> RunJobResult:
    _authorize(scope, x_job_secret)
    # Jobs whose invocation died mid-step are still `running` and nothing will ever write them
    # again. Sweeping here, on the one endpoint a job runner is guaranteed to call, is what turns
    # them back into rows a delivery can claim.
    scope.jobs.fail_stale_running(scope.shared.settings.job_stale_after_seconds)
    scope.conn.commit()
    # Claiming, running and recording the job is shared with the SQS worker: what this endpoint
    # adds is the secret, the sweep and the response shape. A job id nobody queued is a 404.
    outcome = run_one_job(scope, body.job_id)
    return RunJobResult(**vars(outcome))
