from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from teachme.domain.models import Grade, PartStatus, QuestionKind
from teachme.services.progress import PartView
from teachme.services.tutorial import RenderedPart


class SubjectView(BaseModel):
    subject_id: UUID
    name: str
    languages: tuple[str, ...]
    parts: list[PartView]


class QuestionView(BaseModel):
    attempt_question_id: UUID
    question_id: UUID
    position: int
    round_no: int
    total_in_round: int
    kind: QuestionKind
    prompt: str
    choices: tuple[str, ...] | None


class RoundResult(BaseModel):
    round_no: int
    score: float
    passed: bool
    status: PartStatus
    rounds_left: int
    weak_section_titles: list[str]


class AnswerResult(BaseModel):
    accepted: bool
    grade: Grade | None
    feedback: str
    rejection_reason: str | None = None
    next_question: QuestionView | None = None
    round_result: RoundResult | None = None


class PartSession(BaseModel):
    part: RenderedPart
    status: PartStatus
    attempt_id: UUID | None
    round_no: int
    current_question: QuestionView | None
    last_round: RoundResult | None
    reexplanation: str | None
