from __future__ import annotations

import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from teachme.app import create_app
from teachme.repositories.jobs import JobRepository
from teachme.services.generation_jobs import GenerateUnitJob
from tests.helpers import make_pdf

SECRET = "s3cret"


class RecordingClient:
    """Stands in for the container's httpx client, so a re-enqueued job is recorded rather than
    actually starting another invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.delay = 0.0  # a test that cares whether the POST was waited for sets this

    def post(self, url, **kwargs):
        time.sleep(self.delay)
        self.calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url))

    def close(self) -> None:
        pass


def wait_for(predicate, seconds: float = 5.0):
    """The POST goes out on a daemon thread; nothing else in the request waits for it."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def ingest_job(db, make_container):
    """A subject with one uploaded source and a queued ingest job, behind a self-invoking runner
    whose POST is recorded instead of sent. Built before the app exists, because once the app has
    a pool the container refuses attribute lookups that would use its single CLI connection."""
    container = make_container(
        job_runner="vercel_function",
        job_runner_secret=SECRET,
        self_base_url="https://teach-me.test",
        pages_per_read_batch=3,
        pages_per_chunk_batch=3,
    )
    client = RecordingClient()
    container.__dict__["http_client"] = client
    subject = container.subject_service.get_or_create("Geo", ["en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(4))
    job_id = container.jobs.create("ingest_source", {"source_id": str(source.id)})
    container.conn.commit()

    app = create_app(container)
    with TestClient(app) as http:
        yield http, container, source, job_id, client


def run(http, job_id, *, secret: str | None = SECRET, kind: str = "ingest_source", payload=None):
    headers = {"x-job-secret": secret} if secret is not None else {}
    body = {"job_id": str(job_id), "kind": kind, "payload": payload or {}}
    return http.post("/api/jobs/run", json=body, headers=headers)


def test_a_missing_or_wrong_secret_is_refused(ingest_job):
    http, container, source, job_id, _ = ingest_job
    assert run(http, job_id, secret=None).status_code == 401
    assert run(http, job_id, secret="wrong").status_code == 401
    with container.pool.connection() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row["status"] == "queued"  # nothing ran


def test_a_deployment_without_a_secret_refuses_everyone(db, make_container):
    container = make_container()
    subject = container.subject_service.get_or_create("Geo", ["en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(1))
    job_id = container.jobs.create("ingest_source", {"source_id": str(source.id)})
    container.conn.commit()
    with TestClient(create_app(container)) as http:
        assert run(http, job_id, secret="anything").status_code == 401


def test_a_non_ascii_secret_is_refused_rather_than_crashing(ingest_job):
    """A header nobody could have configured still has to be compared, not raise: `compare_digest`
    refuses two `str`s unless both are ASCII, so the comparison is made on bytes."""
    http, container, source, job_id, _ = ingest_job
    # As a byte string, because that is what reaches a server: Starlette decodes a header as
    # latin-1, so these bytes arrive as a `str` with a character outside ASCII in it.
    assert run(http, job_id, secret="s\u00e9cret".encode("latin-1")).status_code == 401
    with container.pool.connection() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row["status"] == "queued"


def _counts(container) -> tuple[int, int]:
    with container.pool.connection() as conn:
        jobs = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
        usage = conn.execute("SELECT count(*) AS n FROM llm_usage").fetchone()["n"]
    return jobs, usage


def test_a_redelivered_job_is_skipped_rather_than_run_again(ingest_job):
    """At-least-once delivery means the same message arrives twice. The second one must not redo
    the step the first one finished - and must not ask for a retry, so no `next_job_id`."""
    http, container, source, job_id, _ = ingest_job
    assert run(http, job_id).json()["status"] == "done"
    before = _counts(container)

    response = run(http, job_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "skipped" and body["job_id"] == str(job_id)
    assert body["next_job_id"] is None
    assert _counts(container) == before  # no second step, no second job


def test_two_concurrent_deliveries_run_the_job_once(ingest_job):
    """Two invocations receiving the same message at the same moment: the claim is one statement,
    so the second finds the row already `running` and stands down."""
    http, container, source, job_id, _ = ingest_job
    results: list[str] = []
    lock = threading.Lock()

    def deliver() -> None:
        status = run(http, job_id).json()["status"]
        with lock:
            results.append(status)

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert sorted(results) == ["done", "skipped"]
    with container.pool.connection() as conn:
        row = conn.execute("SELECT status, attempts FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row["status"] == "done" and row["attempts"] == 1


def test_an_unknown_job_id_is_404_not_500(ingest_job):
    http, *_ = ingest_job
    missing = "00000000-0000-0000-0000-000000000000"
    response = run(http, missing)
    assert response.status_code == 404 and set(response.json()) == {"detail"}


def test_each_call_runs_one_step_and_re_enqueues_the_rest(ingest_job):
    """Four pages read three at a time: two extraction steps, then chunking, then indexing. One
    read batch per invocation is the point - a whole extraction phase would not fit in one."""
    http, container, source, job_id, client = ingest_job
    statuses = []
    next_id = job_id
    for _ in range(4):
        response = run(http, next_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "done"
        with container.pool.connection() as conn:
            statuses.append(
                conn.execute("SELECT status FROM sources WHERE id = %s", (source.id,)).fetchone()["status"]
            )
        next_id = body["next_job_id"]

    assert statuses == ["extracting", "chunking", "indexing", "ready"]
    assert next_id is None
    assert wait_for(lambda: len(client.calls) == 3)
    url, kwargs = client.calls[0]
    assert url == "https://teach-me.test/api/jobs/run"
    assert kwargs["json"]["kind"] == "ingest_source"
    assert kwargs["json"]["payload"] == {"source_id": str(source.id)}
    assert kwargs["headers"] == {"x-job-secret": SECRET}


def test_the_next_step_is_handed_over_before_the_response(ingest_job):
    """Vercel may freeze the instance the moment the response goes out, so a POST still sitting
    on a daemon thread may never leave it. The re-enqueue from this endpoint goes out inline,
    bounded by the runner's one-second read timeout - nothing here waits for the work itself."""
    http, container, source, job_id, client = ingest_job
    client.delay = 0.3  # a daemon thread would still be inside the POST when the response lands
    response = run(http, job_id)
    assert response.json()["status"] == "done"
    assert len(client.calls) == 1  # already delivered, not left behind on a thread


def test_a_delivery_sweeps_jobs_whose_invocation_died(ingest_job):
    """A function that hits its duration limit writes nothing on its way out, so its row stays
    `running` for ever. Every delivery sweeps first, which both records the truth and makes the
    row claimable again."""
    http, container, source, job_id, _ = ingest_job
    with container.pool.connection() as conn:
        dead = JobRepository(conn).create("ingest_source", {"source_id": str(source.id)})
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = now() - interval '1 hour' WHERE id = %s",
            (dead,),
        )
    assert run(http, job_id).json()["status"] == "done"

    with container.pool.connection() as conn:
        row = conn.execute("SELECT status, error FROM jobs WHERE id = %s", (dead,)).fetchone()
    assert row["status"] == "failed" and row["error"] == "invocation exceeded its duration"


def test_an_unknown_kind_marks_the_job_failed(ingest_job):
    http, container, source, _, _ = ingest_job
    with container.pool.connection() as conn:
        bad = JobRepository(conn).create("nope", {})
    response = run(http, bad, kind="nope")
    assert response.status_code == 400
    with container.pool.connection() as conn:
        row = conn.execute("SELECT status, attempts FROM jobs WHERE id = %s", (bad,)).fetchone()
    assert row["status"] == "failed" and row["attempts"] == 1


def test_it_runs_a_generate_unit_job(db, make_container):
    container = make_container(job_runner_secret=SECRET)
    subject = container.subject_service.get_or_create("Geo", ["en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(4))
    container.pipeline.ingest_source(source.id)
    container.tutorial_service.run_unit(container.tutorial_service.plan_generation(subject)[0])
    unit = container.tutorial_service.plan_part_units(subject, languages=["en"])[0]
    job_id = container.jobs.create("generate_unit", GenerateUnitJob(unit=unit).model_dump(mode="json"))
    container.conn.commit()

    with TestClient(create_app(container)) as http:
        response = run(http, job_id, kind="generate_unit")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "job_id": str(job_id),
            "kind": "generate_unit",
            "status": "done",
            "next_job_id": None,
        }
        with container.pool.connection() as conn:
            row = conn.execute("SELECT status FROM part_content WHERE language = 'en'").fetchone()
    assert row["status"] == "ready"
