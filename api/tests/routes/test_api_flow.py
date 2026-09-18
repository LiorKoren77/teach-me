from __future__ import annotations

import json
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from teachme.app import create_app
from teachme.auth.clerk import UserContext, current_user
from teachme.grading.grader import GradeOut
from teachme.grading.relevance_check import RelevanceVerdict
from tests.helpers import make_pdf

ANSWER = "The ozone layer of the atmosphere absorbs radiation, protecting the biosphere."


@pytest.fixture
def api(db, make_container):
    container = make_container(pages_per_read_batch=3, pages_per_chunk_batch=3, max_answers_per_minute=1000)
    subject = container.subject_service.get_or_create("Geo", ["he", "en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(6))
    container.pipeline.ingest_source(source.id)
    container.tutorial_service.generate(subject)
    subject = container.tutorial_service.publish(subject)
    fake = container.llm.inner
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="on_topic"))
    fake.set_responder(
        GradeOut,
        lambda req: GradeOut(verdict="correct", rubric_covered=[0], missed_concepts=[], feedback="good"),
    )
    fake.set_text_responder(lambda req: "## Again\n\nexplained {{term:biosphere|x}}")

    app = create_app(container)
    user = {"id": "user_1", "role": "student"}
    app.dependency_overrides[current_user] = lambda: UserContext(user_id=user["id"], role=user["role"])
    with TestClient(app) as client:
        yield client, subject, user, fake


def test_health_and_subject_list(api):
    client, subject, *_ = api
    assert client.get("/api/health").json()["status"] == "ok"
    subjects = client.get("/api/subjects").json()
    assert subjects[0]["name"] == "Geo"
    assert subjects[0]["parts_total"] >= 2 and subjects[0]["parts_passed"] == 0


def test_learning_flow_over_http(api):
    client, subject, user, fake = api
    view = client.get(f"/api/subjects/{subject.id}").json()
    assert view["parts"][0]["locked"] is False

    session = client.post(f"/api/subjects/{subject.id}/parts/0/start", json={"language": "he"}).json()
    assert session["status"] == "learning" and "{{term:" not in session["part"]["body"]
    attempt_id = session["attempt_id"]

    question = client.post(f"/api/attempts/{attempt_id}/round").json()
    assert question["round_no"] == 1
    result = None
    while question is not None:
        if question["kind"] == "multiple_choice":
            body = {"attempt_question_id": question["attempt_question_id"], "answer_choice": 1}
        else:
            body = {"attempt_question_id": question["attempt_question_id"], "answer_text": ANSWER}
        res = client.post(f"/api/attempts/{attempt_id}/answer", json=body)
        assert res.status_code == 200, res.text
        payload = res.json()
        question, result = payload["next_question"], payload["round_result"]
    assert result["passed"] is True and result["status"] == "passed"
    assert client.get(f"/api/subjects/{subject.id}").json()["parts"][1]["locked"] is False


def test_bad_requests_are_refused_without_reaching_the_service(api):
    client, subject, *_ = api
    session = client.post(f"/api/subjects/{subject.id}/parts/0/start", json={"language": "he"}).json()
    attempt_id = session["attempt_id"]
    question = client.post(f"/api/attempts/{attempt_id}/round").json()
    aq = question["attempt_question_id"]
    # neither answer, and both answers, are validation errors
    assert (
        client.post(f"/api/attempts/{attempt_id}/answer", json={"attempt_question_id": aq}).status_code == 422
    )
    both = {"attempt_question_id": aq, "answer_text": ANSWER, "answer_choice": 1}
    assert client.post(f"/api/attempts/{attempt_id}/answer", json=both).status_code == 422
    # a language the subject does not teach, and an unknown part, are refused by the service
    assert (
        client.post(f"/api/subjects/{subject.id}/parts/0/start", json={"language": "pt"}).status_code == 403
    )
    assert (
        client.post(f"/api/subjects/{subject.id}/parts/9/start", json={"language": "he"}).status_code == 409
    )
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/subjects/{missing}").status_code == 404
    assert client.post(f"/api/attempts/{missing}/round").status_code == 404
    body = client.get(f"/api/subjects/{missing}").json()
    assert set(body) == {"detail"} and "Traceback" not in body["detail"]


def test_reexplain_stream_and_errors(api):
    client, subject, user, fake = api
    fake.set_responder(
        GradeOut,
        lambda req: GradeOut(verdict="incorrect", rubric_covered=[], missed_concepts=["m"], feedback="no"),
    )
    session = client.post(f"/api/subjects/{subject.id}/parts/0/start", json={"language": "he"}).json()
    attempt_id = session["attempt_id"]
    question = client.post(f"/api/attempts/{attempt_id}/round").json()
    while question is not None:
        body = {"attempt_question_id": question["attempt_question_id"]}
        body |= (
            {"answer_choice": 0}
            if question["kind"] == "multiple_choice"
            else {"answer_text": "wrong but on topic answer about the atmosphere"}
        )
        question = client.post(f"/api/attempts/{attempt_id}/answer", json=body).json()["next_question"]

    events: list[str] = []
    done = None
    with client.stream("GET", f"/api/attempts/{attempt_id}/reexplain") as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:") and events and events[-1] == "done":
                done = json.loads(line[5:].strip())
    assert "delta" in events and events[-1] == "done"
    assert done is not None and "{{term:" not in done["text"] and "explained" in done["text"]
    assert done["truncated"] is False

    # the stream released its pooled connection: nothing is waiting, nothing is in use
    container = client.app.state.container
    stats = container.pool.get_stats()
    assert stats.get("requests_waiting", 0) == 0 and stats["pool_size"] == stats["pool_available"]
    # and the row was committed before the stream ended, on another connection entirely
    assert container.attempts.latest_reexplanation(UUID(attempt_id)) is not None

    # a client that gives up in the middle of a stream releases the connection just the same
    with client.stream("GET", f"/api/attempts/{attempt_id}/reexplain") as second:
        assert next(second.iter_lines()) != ""
    for _ in range(100):
        stats = container.pool.get_stats()
        if stats["pool_size"] == stats["pool_available"]:
            break
        time.sleep(0.05)
    assert stats["pool_size"] == stats["pool_available"]

    # a different user cannot touch this attempt
    user["id"] = "intruder"
    assert client.post(f"/api/attempts/{attempt_id}/round").status_code == 403
    assert client.get(f"/api/attempts/{attempt_id}/reexplain").status_code == 403
    user["id"] = "user_1"

    assert client.get("/api/admin/subjects").status_code == 403  # a student is not an admin
    user["role"] = "admin"
    admin = client.get("/api/admin/subjects").json()
    assert admin[0]["state"] == "published"
    sources = client.get(f"/api/admin/subjects/{subject.id}/sources").json()
    assert sources[0]["status"] == "ready"
    assert client.get(f"/api/admin/usage?subject_id={subject.id}").status_code == 200


def test_an_unauthenticated_request_is_refused(db, make_container):
    """No dependency override, no Clerk JWKS url: the guard refuses instead of trusting anyone."""
    app = create_app(make_container())
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/subjects").status_code == 503


def test_the_rate_limit_answers_429(api):
    client, subject, *_ = api
    session = client.post(f"/api/subjects/{subject.id}/parts/0/start", json={"language": "he"}).json()
    attempt_id = session["attempt_id"]
    question = client.post(f"/api/attempts/{attempt_id}/round").json()
    client.app.state.container.settings.max_answers_per_minute = 0
    res = client.post(
        f"/api/attempts/{attempt_id}/answer",
        json={"attempt_question_id": question["attempt_question_id"], "answer_text": ANSWER},
    )
    assert res.status_code == 429 and res.json()["detail"].startswith("rate limit")
