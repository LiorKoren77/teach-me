from __future__ import annotations

import threading

import httpx
import pytest

from teachme.adapters.job_runner.vercel_function import VercelFunctionJobRunner
from teachme.repositories.jobs import JobRepository


def immediately(work):
    """A spawn that runs the POST in the calling thread, so a test can assert on its effect."""
    work()


class RecordingClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response or httpx.Response(200, json={"status": "done"})
        self._error = error

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._error is not None:
            raise self._error
        self._response.request = httpx.Request("POST", url)
        return self._response


def make_runner(**overrides):
    base = dict(
        base_url="https://teach-me.vercel.app",
        secret="s3cret",
        jobs=None,
        client=RecordingClient(),
        spawn=immediately,
    )
    base.update(overrides)
    return VercelFunctionJobRunner(**base)


def test_posts_the_job_to_the_run_endpoint_with_the_secret_header():
    client = RecordingClient()
    runner = make_runner(client=client)
    job_id = runner.enqueue("ingest_source", {"source_id": "abc"})

    url, kwargs = client.calls[0]
    assert url == "https://teach-me.vercel.app/api/jobs/run"
    assert kwargs["json"] == {"job_id": str(job_id), "kind": "ingest_source", "payload": {"source_id": "abc"}}
    assert kwargs["headers"] == {"x-job-secret": "s3cret"}


def test_a_trailing_slash_on_the_base_url_does_not_double_up():
    client = RecordingClient()
    make_runner(base_url="https://teach-me.vercel.app/", client=client).enqueue("ingest_source", {})
    assert client.calls[0][0] == "https://teach-me.vercel.app/api/jobs/run"


def test_commits_the_queued_row_before_posting(db):
    jobs = JobRepository(db)
    runner = make_runner(jobs=jobs, commit=db.commit)
    job_id = runner.enqueue("ingest_source", {"source_id": "abc"})

    db.rollback()  # as if the request that enqueued had failed after this point
    assert jobs.get(job_id)["status"] == "queued"


def test_marks_the_job_failed_when_the_post_cannot_connect(db):
    jobs = JobRepository(db)
    client = RecordingClient(error=httpx.ConnectError("nowhere"))
    runner = make_runner(jobs=jobs, client=client, commit=db.commit)
    job_id = runner.enqueue("ingest_source", {"source_id": "abc"})

    db.rollback()
    row = jobs.get(job_id)
    assert row["status"] == "failed" and "ConnectError" in row["error"]


def test_marks_the_job_failed_when_the_endpoint_refuses(db):
    jobs = JobRepository(db)
    client = RecordingClient(response=httpx.Response(401, json={"detail": "no"}))
    runner = make_runner(jobs=jobs, client=client, commit=db.commit)
    job_id = runner.enqueue("ingest_source", {})

    db.rollback()
    assert jobs.get(job_id)["status"] == "failed"


def test_a_read_timeout_is_delivery_not_failure(db):
    """The receiving invocation does the work and answers minutes later; waiting for it is
    exactly what this runner must not do, so a read timeout means accepted, not failed."""
    jobs = JobRepository(db)
    client = RecordingClient(error=httpx.ReadTimeout("still working"))
    runner = make_runner(jobs=jobs, client=client, commit=db.commit)
    job_id = runner.enqueue("ingest_source", {})

    db.rollback()
    assert jobs.get(job_id)["status"] == "queued"


def test_a_failed_post_goes_through_mark_failed_when_one_is_given(db):
    """On Vercel the POST happens after the request's pooled connection is gone, so the failure
    is recorded through a handle that takes a connection of its own."""
    recorded = []
    client = RecordingClient(error=httpx.ConnectError("nowhere"))
    runner = make_runner(jobs=None, client=client, mark_failed=lambda i, e: recorded.append((i, e)))
    job_id = runner.enqueue("ingest_source", {})
    assert recorded[0][0] == job_id and "ConnectError" in recorded[0][1]


def test_enqueue_does_not_wait_for_the_post():
    """The default spawn is a daemon thread: enqueue returns while the POST is still in flight."""
    released = threading.Event()
    posted = threading.Event()

    class BlockingClient:
        def post(self, url, **kwargs):
            posted.set()
            released.wait(5)
            return httpx.Response(200, request=httpx.Request("POST", url))

    runner = VercelFunctionJobRunner(base_url="https://x", secret="s", jobs=None, client=BlockingClient())
    runner.enqueue("ingest_source", {})
    try:
        assert posted.wait(5), "the POST never started"
    finally:
        released.set()


def test_a_broken_failure_recording_is_logged_not_raised(db, caplog):
    def boom(job_id, error):
        raise RuntimeError("no connection")

    client = RecordingClient(error=httpx.ConnectError("nowhere"))
    runner = make_runner(jobs=None, client=client, mark_failed=boom)
    with caplog.at_level("ERROR"):
        runner.enqueue("ingest_source", {})
    assert any("could not record job" in record.message for record in caplog.records)


@pytest.mark.parametrize("missing", ["base_url", "secret"])
def test_refuses_to_be_built_without_a_target_or_a_secret(missing):
    with pytest.raises(ValueError):
        make_runner(**{missing: ""})
