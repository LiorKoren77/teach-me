from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import boto3

from teachme.ports.job_runner import JobPayload
from teachme.repositories.jobs import JobRepository


class SqsJobRunner:
    """Enqueue only. A worker that receives messages and calls the handlers is part of the AWS
    move (spec section 9), not of this stage."""

    name = "sqs"

    def __init__(
        self, queue_url: str, region: str, jobs: JobRepository | None, client: Any | None = None
    ) -> None:
        self._queue_url = queue_url
        self._jobs = jobs
        self._client = client or boto3.client("sqs", region_name=region)

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        body = json.dumps({"job_id": str(job_id), "kind": kind, "payload": payload})
        self._client.send_message(QueueUrl=self._queue_url, MessageBody=body)
        return job_id
