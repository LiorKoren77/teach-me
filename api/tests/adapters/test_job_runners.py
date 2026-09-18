from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from teachme.adapters.job_runner.inprocess import InProcessJobRunner
from teachme.adapters.job_runner.sqs import SqsJobRunner
from teachme.ports.job_runner import UnknownJobKind
from teachme.repositories.jobs import JobRepository


def test_inprocess_runs_handler_synchronously_without_repository():
    seen = []
    runner = InProcessJobRunner({"echo": lambda payload: seen.append(payload)}, jobs=None)
    job_id = runner.enqueue("echo", {"x": 1})
    assert seen == [{"x": 1}] and job_id


def test_inprocess_unknown_kind():
    with pytest.raises(UnknownJobKind):
        InProcessJobRunner({}, jobs=None).enqueue("nope", {})


def test_inprocess_records_status_and_reraises(db):
    jobs = JobRepository(db)

    def boom(payload):
        raise RuntimeError("bad")

    runner = InProcessJobRunner({"ok": lambda p: None, "boom": boom}, jobs=jobs)
    ok_id = runner.enqueue("ok", {})
    assert jobs.get(ok_id)["status"] == "done" and jobs.get(ok_id)["attempts"] == 1
    with pytest.raises(RuntimeError):
        runner.enqueue("boom", {})
    failed = [r for r in db.execute("SELECT status, error FROM jobs WHERE kind = 'boom'").fetchall()]
    assert failed[0]["status"] == "failed" and failed[0]["error"] == "bad"


def test_sqs_sends_message_with_job_id():
    with mock_aws():
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="teachme-test")["QueueUrl"]
        runner = SqsJobRunner(queue_url=queue_url, region="eu-central-1", jobs=None, client=sqs)
        job_id = runner.enqueue("ingest_source", {"source_id": "abc"})
        body = json.loads(sqs.receive_message(QueueUrl=queue_url)["Messages"][0]["Body"])
        assert body == {"job_id": str(job_id), "kind": "ingest_source", "payload": {"source_id": "abc"}}
