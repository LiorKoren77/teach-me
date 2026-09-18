from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from teachme.auth.clerk import CurrentUser
from teachme.routes.deps import ScopeDep
from teachme.routes.schemas import AnswerRequest, ReexplainDelta, ReexplainDone, StartPartRequest
from teachme.scope import Scope
from teachme.services.learning import LearningError
from teachme.services.learning_views import AnswerResult, PartSession, QuestionView

router = APIRouter(prefix="/api", tags=["learning"])


@router.post("/subjects/{subject_id}/parts/{position}/start", response_model=PartSession)
def start_part(
    subject_id: UUID, position: int, body: StartPartRequest, user: CurrentUser, scope: ScopeDep
) -> PartSession:
    return scope.learning_service.start_part(
        user.user_id, scope.subjects.get(subject_id), position, body.language
    )


@router.post("/attempts/{attempt_id}/round", response_model=QuestionView)
def begin_round(attempt_id: UUID, user: CurrentUser, scope: ScopeDep) -> QuestionView:
    return scope.learning_service.begin_round(user.user_id, attempt_id)


@router.post("/attempts/{attempt_id}/answer", response_model=AnswerResult)
def submit_answer(attempt_id: UUID, body: AnswerRequest, user: CurrentUser, scope: ScopeDep) -> AnswerResult:
    return scope.learning_service.submit_answer(
        user.user_id,
        attempt_id,
        body.attempt_question_id,
        answer_text=body.answer_text,
        answer_choice=body.answer_choice,
    )


def _reexplain_events(scope: Scope, user_id: str, attempt_id: UUID) -> list[dict[str, str]]:
    """Generate, persist and commit the re-explanation, then describe it as SSE events.

    The model call and the write happen here, while the request still holds its connection and
    while an exception can still become a status code: once the response has started, a refusal
    could only arrive as a broken stream. The deltas are replayed from the buffer the generator
    filled, which is what the client receives as `delta` events."""
    deltas: list[str] = []
    stored = scope.learning_service.reexplain(user_id, attempt_id, on_delta=deltas.append)
    if stored is None:
        raise LearningError("the failed round left no sections to re-explain")
    attempt = scope.attempts.get(attempt_id)
    part = scope.outlines.get_part(attempt.part_id)
    subject = scope.subjects.get(scope.outlines.get(part.outline_id).subject_id)
    rendered = scope.learning_service.render_text(subject, attempt.language, stored.body)
    events = [{"event": "delta", "data": ReexplainDelta(text=text).model_dump_json()} for text in deltas]
    done = ReexplainDone(text=rendered, truncated=stored.truncated, round_no=stored.round_no)
    events.append({"event": "done", "data": done.model_dump_json()})
    return events


@router.get("/attempts/{attempt_id}/reexplain")
def reexplain(attempt_id: UUID, user: CurrentUser, scope: ScopeDep) -> EventSourceResponse:
    """Server-sent events: `delta` events carry the text as the model produced it, placeholders
    included; the final `done` event carries the rendered text to replace the pane with."""
    events = _reexplain_events(scope, user.user_id, attempt_id)

    def stream() -> Iterator[dict[str, str]]:
        yield from events

    return EventSourceResponse(stream())
