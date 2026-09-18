from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from teachme.app import create_app
from teachme.auth.clerk import UserContext, current_user
from tests.helpers import make_pdf

PDF = ("ch1.pdf", make_pdf(2), "application/pdf")


@pytest.fixture
def make_admin(db, make_container):
    """An admin client over a subject, optionally with sources already ingested and published.

    Everything the container does directly happens before `create_app`: once the app has opened a
    pool, the container refuses attribute lookups that would put a request on its CLI connection."""
    clients = []

    def factory(*, sources=(), publish=False, **settings):
        container = make_container(pages_per_read_batch=3, pages_per_chunk_batch=3, **settings)
        subject = container.subject_service.get_or_create("Geo", ["en"])
        for filename, data in sources:
            source = container.source_service.register(subject, filename, data)
            container.pipeline.ingest_source(source.id)
        if publish:
            container.tutorial_service.generate(subject)
            subject = container.tutorial_service.publish(subject)

        app = create_app(container)
        user = {"id": "admin_1", "role": "admin"}
        app.dependency_overrides[current_user] = lambda: UserContext(user_id=user["id"], role=user["role"])
        entered = TestClient(app)
        clients.append(entered)
        return entered.__enter__(), container, subject, user

    yield factory
    for entered in clients:
        entered.__exit__(None, None, None)


def upload(client, subject, file=PDF):
    return client.post(f"/api/admin/subjects/{subject.id}/sources", files={"file": file})


def test_capabilities_describe_what_the_file_picker_may_offer(make_admin):
    client, *_ = make_admin()
    body = client.get("/api/admin/capabilities").json()
    assert "application/pdf" in body["accepted_media_types"]
    assert body["accepted_media_types"] == sorted(body["accepted_media_types"])
    assert body["max_upload_bytes"] == 50 * 1024 * 1024


def test_an_upload_registers_the_source_and_queues_its_ingestion(make_admin):
    client, _, subject, _ = make_admin()
    response = upload(client, subject)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "ch1.pdf" and body["media_type"] == "application/pdf"
    # The response reads the source back after the job was handed over, so it says what actually
    # happened: "ready" behind the in-process runner, "uploaded" behind a queued one.
    assert body["status"] == "ready"

    job = client.get(f"/api/admin/jobs/{body['job_id']}").json()
    assert job["id"] == body["job_id"] and job["kind"] == "ingest_source"
    assert job["status"] == "done" and job["attempts"] == 1 and job["error"] is None

    listed = client.get(f"/api/admin/subjects/{subject.id}/sources").json()
    assert [s["status"] for s in listed] == ["ready"]
    assert listed[0]["page_count"] == 2 and listed[0]["id"] == body["id"]


def test_a_type_the_deployment_cannot_read_is_415(make_admin):
    client, _, subject, _ = make_admin()
    response = upload(client, subject, file=("notes.zip", b"PK\x03\x04", "application/zip"))
    assert response.status_code == 415
    assert set(response.json()) == {"detail"} and "application/zip" in response.json()["detail"]


def test_a_body_over_the_limit_is_413_before_it_is_stored(make_admin):
    client, container, subject, _ = make_admin(max_upload_bytes=512)
    response = upload(client, subject)
    assert response.status_code == 413 and set(response.json()) == {"detail"}
    assert client.get(f"/api/admin/subjects/{subject.id}/sources").json() == []


def test_an_unknown_job_is_404(make_admin):
    client, *_ = make_admin()
    assert client.get("/api/admin/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_a_source_can_be_reingested_and_deleted(make_admin):
    client, _, subject, _ = make_admin(sources=[("ch1.pdf", make_pdf(2))])
    source_id = client.get(f"/api/admin/subjects/{subject.id}/sources").json()[0]["id"]

    job_id = client.post(f"/api/admin/sources/{source_id}/reingest").json()["job_id"]
    assert client.get(f"/api/admin/jobs/{job_id}").json()["status"] == "done"
    assert client.get(f"/api/admin/subjects/{subject.id}/sources").json()[0]["status"] == "ready"

    deleted = client.delete(f"/api/admin/sources/{source_id}")
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(f"/api/admin/subjects/{subject.id}/sources").json() == []
    assert client.delete(f"/api/admin/sources/{source_id}").status_code == 404


def test_generate_then_status_then_publish_and_unpublish(make_admin):
    client, _, subject, _ = make_admin(sources=[("ch1.pdf", make_pdf(4))])
    job_id = client.post(f"/api/admin/subjects/{subject.id}/generate").json()["job_id"]
    job = client.get(f"/api/admin/jobs/{job_id}").json()
    assert job["kind"] == "generate_subject" and job["status"] == "done"

    status = client.get(f"/api/admin/subjects/{subject.id}/status").json()
    assert status["state"] == "draft" and status["published_version"] is None
    assert status["outline_version"] == 1 and status["parts_total"] >= 2
    assert status["publishable"] is True and status["publishable_version"] == 1
    language = status["languages"][0]
    assert language["language"] == "en" and language["complete"] is True
    assert language["parts_ready"] == language["parts_total"] == status["parts_total"]
    assert language["questions"] > 0 and language["failed"] == []

    published = client.post(f"/api/admin/subjects/{subject.id}/publish").json()
    assert published["state"] == "published" and published["current_outline_version"] == 1
    assert client.get(f"/api/admin/subjects/{subject.id}/status").json()["published_version"] == 1

    assert client.post(f"/api/admin/subjects/{subject.id}/unpublish").json()["state"] == "draft"


def test_a_published_subject_is_locked_but_still_lists_its_sources(make_admin):
    client, _, subject, _ = make_admin(sources=[("ch1.pdf", make_pdf(4))], publish=True)
    listed = client.get(f"/api/admin/subjects/{subject.id}/sources").json()
    assert [s["filename"] for s in listed] == ["ch1.pdf"]

    assert upload(client, subject).status_code == 409
    assert client.delete(f"/api/admin/sources/{listed[0]['id']}").status_code == 409
    assert client.post(f"/api/admin/sources/{listed[0]['id']}/reingest").status_code == 409
    assert client.post(f"/api/admin/subjects/{subject.id}/generate").status_code == 409


def test_a_student_is_refused_every_admin_route(make_admin):
    client, _, subject, user = make_admin(sources=[("ch1.pdf", make_pdf(2))])
    source_id = client.get(f"/api/admin/subjects/{subject.id}/sources").json()[0]["id"]
    user["role"] = "student"
    subject_path = f"/api/admin/subjects/{subject.id}"
    calls = [
        client.get("/api/admin/capabilities"),
        upload(client, subject),
        client.delete(f"/api/admin/sources/{source_id}"),
        client.post(f"/api/admin/sources/{source_id}/reingest"),
        client.get("/api/admin/jobs/00000000-0000-0000-0000-000000000000"),
        client.post(f"{subject_path}/generate"),
        client.post(f"{subject_path}/publish"),
        client.post(f"{subject_path}/unpublish"),
        client.get(f"{subject_path}/status"),
    ]
    assert [response.status_code for response in calls] == [403] * len(calls)
    user["role"] = "admin"
    assert client.get(f"{subject_path}/sources").json()[0]["status"] == "ready"


def test_generate_is_refused_before_a_job_exists_when_nothing_is_ready(make_admin):
    """The route plans the run while the admin is still on the line, so an unready subject is a
    409 they can act on rather than a job that fails somewhere behind them."""
    client, container, subject, _ = make_admin()
    response = client.post(f"/api/admin/subjects/{subject.id}/generate")
    assert response.status_code == 409 and "no sources" in response.json()["detail"]
    with container.pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
