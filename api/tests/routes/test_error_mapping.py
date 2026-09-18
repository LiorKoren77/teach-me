from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teachme.domain.assessment.scoring import UnmappedQuestion
from teachme.domain.assessment.transitions import IllegalTransition
from teachme.domain.models import AttemptQuestion, PartStatus
from teachme.generation.errors import GenerationError
from teachme.ingestion.errors import SubjectLocked
from teachme.repositories.errors import SubjectNotFound
from teachme.routes.errors import install_error_handlers
from teachme.services.learning import (
    InvalidChoice,
    LearningError,
    NotAllowed,
    QuestionClosed,
    RateLimited,
)

UNMAPPED = AttemptQuestion(id=uuid4(), attempt_id=uuid4(), question_id=uuid4(), position=0)

CASES = [
    (SubjectNotFound(uuid4()), 404),
    (NotAllowed("not your attempt"), 403),
    (RateLimited("too many"), 429),
    (LearningError("no part 9"), 409),
    (QuestionClosed("question is not open for answering"), 409),
    (InvalidChoice("that question has 4 options"), 409),
    (UnmappedQuestion(UNMAPPED), 409),
    (IllegalTransition(PartStatus.PASSED, PartStatus.QUIZZING), 409),
    (GenerationError("not ready"), 409),
    (SubjectLocked("locked"), 409),
]


@pytest.fixture
def client():
    """The error table on its own: one route per refusal, no database and no auth involved."""
    app = FastAPI()
    install_error_handlers(app)

    def route(exc: Exception):
        # A closure, not a default argument: FastAPI would read a defaulted parameter as a query
        # parameter and try to build a model field out of the exception.
        def raise_it() -> None:
            raise exc

        return raise_it

    for index, (exc, _status) in enumerate(CASES):
        app.add_api_route(f"/{index}", route(exc), methods=["GET"])
    return TestClient(app)


@pytest.mark.parametrize("index", range(len(CASES)))
def test_every_refusal_maps_to_its_status_and_our_error_body(client, index):
    exc, status = CASES[index]
    response = client.get(f"/{index}")
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"detail"} and body["detail"] == str(exc)
