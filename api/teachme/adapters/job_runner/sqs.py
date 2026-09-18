from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import boto3

from teachme.ports.job_runner import JobPayload
from teachme.repositories.jobs import JobRepository


class SqsJobRunner:
    """Enqueue only: `SqsWorker` (same package, `teachme worker`) is what receives these
    messages and runs them.

    commit, when given, is called right after the job row is created (and durably recorded) and
    before the message is sent - a crash or rollback after that point still leaves the queued job
    row behind. If sending fails, the job is marked failed and that is committed too, before the
    exception is re-raised."""

    name = "sqs"

    def __init__(
        self,
        queue_url: str,
        region: str,
        jobs: JobRepository | None,
        client: Any | None = None,
        commit: Callable[[], None] | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._jobs = jobs
        self._client = client or boto3.client("sqs", region_name=region)
        self._commit = commit

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        if self._commit:
            self._commit()
        self.deliver(job_id, kind, payload)
        return job_id

    # Sending to SQS is already synchronous: the message is accepted before this returns.
    enqueue_inline = enqueue

    def deliver(self, job_id: UUID, kind: str, payload: JobPayload) -> None:
        body = json.dumps({"job_id": str(job_id), "kind": kind, "payload": payload})
        try:
            self._client.send_message(QueueUrl=self._queue_url, MessageBody=body)
        except Exception as exc:
            if self._jobs:
                self._jobs.set_status(job_id, "failed", error=str(exc))
                if self._commit:
                    self._commit()
            raise
