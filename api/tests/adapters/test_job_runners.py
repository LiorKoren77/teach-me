from __future__ import annotations

import json
import logging

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


def test_inprocess_rolls_back_before_recording_failure_then_commits(db):
    jobs = JobRepository(db)

    def boom(payload):
        try:
            db.execute("SELECT 1/0")
        except Exception:
            pass
        raise RuntimeError("bad")

    runner = InProcessJobRunner({"boom": boom}, jobs=jobs, commit=db.commit, rollback=db.rollback)
    with pytest.raises(RuntimeError, match="bad"):
        runner.enqueue("boom", {})

    db.rollback()
    row = db.execute("SELECT status, error FROM jobs WHERE kind = 'boom'").fetchone()
    assert row["status"] == "failed" and row["error"] == "bad"


def test_inprocess_logs_when_recording_failure_raises(db, caplog):
    jobs = JobRepository(db)

    def boom(payload):
        raise RuntimeError("bad")

    def bad_rollback():
        raise RuntimeError("rollback boom")

    runner = InProcessJobRunner({"boom": boom}, jobs=jobs, commit=db.commit, rollback=bad_rollback)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="bad"):
            runner.enqueue("boom", {})
    assert any("could not record job" in record.message for record in caplog.records)


def test_inprocess_unknown_kind_commits_failure(db):
    jobs = JobRepository(db)
    runner = InProcessJobRunner({}, jobs=jobs, commit=db.commit)
    with pytest.raises(UnknownJobKind):
        runner.enqueue("nope", {})
    db.rollback()
    row = db.execute("SELECT status FROM jobs WHERE kind = 'nope'").fetchone()
    assert row["status"] == "failed"


def test_sqs_sends_message_with_job_id():
    with mock_aws():
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="teachme-test")["QueueUrl"]
        runner = SqsJobRunner(queue_url=queue_url, region="eu-central-1", jobs=None, client=sqs)
        job_id = runner.enqueue("ingest_source", {"source_id": "abc"})
        body = json.loads(sqs.receive_message(QueueUrl=queue_url)["Messages"][0]["Body"])
        assert body == {"job_id": str(job_id), "kind": "ingest_source", "payload": {"source_id": "abc"}}
