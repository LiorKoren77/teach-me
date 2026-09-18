from __future__ import annotations

import json
import logging
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import boto3

from teachme.repositories.errors import JobNotFound

log = logging.getLogger(__name__)

RunJob = Callable[[UUID], Any]


class SqsWorker:
    """The other end of `SqsJobRunner`: long-polls the queue and runs each message through the
    same per-job execution `/api/jobs/run` uses, so a deployment on AWS runs exactly what a
    deployment on Vercel runs - one pipeline step per message, each re-enqueuing the remainder.

    What is a worker's own is what happens to the *message*. A message whose job ran (or was
    already finished by an earlier delivery) is deleted; one whose job raised is left alone, so
    the queue redelivers it after its visibility timeout and the `failed` row it left behind is
    claimed again. The job is never deleted from the queue to hide a failure.

    `run_job` is passed in rather than handlers and repositories: claiming, dispatching and
    recording a job is one function shared with the HTTP route, and it needs the whole scope."""

    name = "sqs-worker"

    def __init__(
        self,
        queue_url: str,
        region: str,
        *,
        run_job: RunJob,
        client: Any | None = None,
        wait_time_seconds: int = 20,
        batch_size: int = 1,
        max_messages: int | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._run_job = run_job
        self._client = client or boto3.client("sqs", region_name=region)
        self._wait_time_seconds = wait_time_seconds
        self._batch_size = batch_size
        self._max_messages = max_messages
        self._stopping = False

    def stop(self) -> None:
        """Finish the message in hand, then end the loop."""
        self._stopping = True

    def run(self, *, once: bool = False) -> int:
        """Consume until told to stop, and say how many messages were handled.

        `once` drains what is already queued and returns - what an operator command and a test
        want - so it ends on the first empty poll instead of waiting for more. It still follows a
        job's own hand-overs: the step that re-enqueues the rest of an ingestion puts its message
        on the queue before this asks for the next one."""
        handled = 0
        wait = min(self._wait_time_seconds, 1) if once else self._wait_time_seconds
        with self._until_terminated():
            while not self._stopping:
                messages = self._receive(wait)
                if not messages:
                    if once:
                        break
                    continue
                for message in messages:
                    self._handle(message)
                    handled += 1
                    if self._max_messages is not None and handled >= self._max_messages:
                        return handled
                    if self._stopping:
                        break
        return handled

    # ----------------------------------------------------------------------------------------
    @contextmanager
    def _until_terminated(self) -> Iterator[None]:
        """SIGTERM ends the loop cleanly instead of killing the process mid-job. Installing a
        handler only works on the main thread; anywhere else the loop is simply left to `stop`."""
        try:
            previous = signal.signal(signal.SIGTERM, lambda *_: self.stop())
        except ValueError:
            yield
            return
        try:
            yield
        finally:
            signal.signal(signal.SIGTERM, previous)

    def _receive(self, wait_time_seconds: int) -> list[dict[str, Any]]:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._batch_size,
            WaitTimeSeconds=wait_time_seconds,
        )
        return response.get("Messages", [])

    def _handle(self, message: dict[str, Any]) -> None:
        job_id = _job_id_of(message)
        if job_id is None:
            log.error("dropping an SQS message with no readable job id: %s", message.get("MessageId"))
            self._delete(message)
            return
        try:
            outcome = self._run_job(job_id)
        except JobNotFound:
            # The row is gone - a deleted source, a truncated table - so nothing will ever run
            # this message. Redelivering it until the queue gives up would only delay the rest.
            log.error("dropping SQS message for job %s: no such job row", job_id)
            self._delete(message)
            return
        except Exception:
            # The job row is already `failed` (the shared execution writes it before re-raising),
            # and `failed` is claimable, so leaving the message to be redelivered is the retry.
            log.exception("job %s failed; leaving its message for redelivery", job_id)
            return
        log.info("job %s %s", job_id, getattr(outcome, "status", "done"))
        self._delete(message)

    def _delete(self, message: dict[str, Any]) -> None:
        self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message["ReceiptHandle"])


def _job_id_of(message: dict[str, Any]) -> UUID | None:
    """`SqsJobRunner` writes the body; anything else in the queue is not ours to run."""
    try:
        return UUID(json.loads(message["Body"])["job_id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None
