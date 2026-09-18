from __future__ import annotations

import json
import signal
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from teachme.adapters.job_runner.sqs_worker import SqsWorker
from teachme.services.job_execution import run_job
from tests.helpers import make_pdf

runner = CliRunner()


@pytest.fixture
def queue():
    """A queue whose messages become visible again at once, so a test can see what a failure
    left behind instead of waiting out a visibility timeout."""
    with mock_aws():
        client = boto3.client("sqs", region_name="eu-central-1")
        url = client.create_queue(QueueName="teachme-worker-test", Attributes={"VisibilityTimeout": "0"})[
            "QueueUrl"
        ]
        yield client, url


@pytest.fixture
def worker_cli(db, queue, make_container, monkeypatch):
    """The CLI, its container wired to the mocked queue, over a subject with one source
    registered but not yet ingested."""
    import teachme.cli.main as main

    client, url = queue
    container = make_container(
        job_runner="sqs", sqs_queue_url=url, pages_per_read_batch=2, pages_per_chunk_batch=2
    )
    monkeypatch.setattr(main, "build_container", lambda *a, **kw: container)
    monkeypatch.setattr(container, "close", lambda: None)
    subject = container.subject_service.get_or_create("Geo", ["en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(3))
    container.conn.commit()
    return main.app, container, client, url, source


def messages_in(client, url) -> list[dict]:
    received = client.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
    return [json.loads(message["Body"]) for message in received]


def test_worker_once_drains_the_queue_and_finishes_the_ingestion(worker_cli):
    """The same messages `/api/jobs/run` would be posted, consumed by the worker instead: one
    pipeline step per message, each re-enqueuing the remainder, until the source is ready."""
    app, container, client, url, source = worker_cli
    job_id = container.scope.job_runner.enqueue("ingest_source", {"source_id": str(source.id)})
    assert len(messages_in(client, url)) == 1

    result = runner.invoke(app, ["worker", "--once"])
    assert result.exit_code == 0, result.output

    container.conn.rollback()
    assert container.jobs.get(job_id)["status"] == "done"
    assert container.sources.get(source.id).status.value == "ready"
    assert messages_in(client, url) == []


def test_worker_once_on_an_empty_queue_exits_cleanly(worker_cli):
    app, *_ = worker_cli
    result = runner.invoke(app, ["worker", "--once"])
    assert result.exit_code == 0, result.output
    assert "0 " in result.output


def test_a_failing_job_is_marked_failed_and_its_message_left_for_redelivery(worker_cli):
    """Nothing is deleted on failure: the message comes back, and the job row is `failed`, which
    is the one non-terminal status `claim` will take again."""
    app, container, client, url, source = worker_cli
    job_id = container.scope.job_runner.enqueue("no_such_kind", {})

    worker = SqsWorker(
        queue_url=url,
        region="eu-central-1",
        run_job=lambda job: run_job(container.scope, job),
        client=client,
        wait_time_seconds=0,
        max_messages=1,
    )
    assert worker.run() == 1

    container.conn.rollback()
    row = container.jobs.get(job_id)
    assert row["status"] == "failed" and "no_such_kind" in row["error"]
    assert [body["job_id"] for body in messages_in(client, url)] == [str(job_id)]


def test_a_redelivered_message_for_a_finished_job_is_skipped_and_deleted(worker_cli):
    """At-least-once means the same message can arrive twice. The second delivery claims
    nothing - `done` is not claimable - and the message is deleted rather than retried."""
    app, container, client, url, source = worker_cli
    job_id = container.jobs.create("ingest_source", {"source_id": str(source.id)})
    container.jobs.set_status(job_id, "done")
    container.conn.commit()
    container.scope.job_runner.deliver(job_id, "ingest_source", {"source_id": str(source.id)})

    seen = []
    worker = SqsWorker(
        queue_url=url,
        region="eu-central-1",
        run_job=lambda job: seen.append(job) or run_job(container.scope, job),
        client=client,
        wait_time_seconds=0,
        max_messages=1,
    )
    assert worker.run() == 1
    assert seen == [job_id]
    container.conn.rollback()
    assert container.sources.get(source.id).status.value == "uploaded"  # nothing ran
    assert messages_in(client, url) == []


def test_a_message_naming_a_job_that_is_not_there_is_dropped(worker_cli):
    """A job row deleted under the queue leaves a message nothing can ever run: it is logged and
    deleted, rather than redelivered until the queue gives up on it."""
    app, container, client, url, source = worker_cli
    client.send_message(
        QueueUrl=url, MessageBody=json.dumps({"job_id": str(uuid4()), "kind": "ingest_source"})
    )
    worker = SqsWorker(
        queue_url=url,
        region="eu-central-1",
        run_job=lambda job: run_job(container.scope, job),
        client=client,
        wait_time_seconds=0,
        max_messages=1,
    )
    assert worker.run() == 1
    assert messages_in(client, url) == []


def test_the_worker_stops_on_a_sigterm(worker_cli):
    """A deployment scaling the worker down sends SIGTERM; the message in hand is finished and
    the loop then ends, instead of the process dying with a job half written."""
    app, container, client, url, source = worker_cli
    container.scope.job_runner.enqueue("no_such_kind", {})

    def sigterm(job):
        signal.raise_signal(signal.SIGTERM)

    worker = SqsWorker(
        queue_url=url,
        region="eu-central-1",
        run_job=sigterm,
        client=client,
        wait_time_seconds=0,
    )
    # Without the signal this loops for ever: `run()` outside `--once` polls until told to stop.
    assert worker.run() == 1
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL  # the handler is put back
