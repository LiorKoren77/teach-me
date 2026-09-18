from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ErrorResponse(BaseModel):
    """Every refusal this API makes, in one shape. `detail` is a message written here, never the
    text of an unexpected exception: internals do not leave the process."""

    detail: str


class SubjectSummary(BaseModel):
    id: UUID
    name: str
    languages: tuple[str, ...]
    parts_total: int
    parts_passed: int


class StartPartRequest(BaseModel):
    language: str = Field(min_length=2, max_length=2)


class AnswerRequest(BaseModel):
    attempt_question_id: UUID
    answer_text: str | None = Field(default=None, max_length=20000)
    answer_choice: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_of(self) -> AnswerRequest:
        if (self.answer_text is None) == (self.answer_choice is None):
            raise ValueError("send exactly one of answer_text or answer_choice")
        return self


class ReexplainDelta(BaseModel):
    """One `delta` event: raw model text, glossary placeholders still in it."""

    text: str


class ReexplainDone(BaseModel):
    """The final `done` event: the whole re-explanation, rendered for the reader's language.

    `truncated` says the model stopped at its token ceiling, so the text ends mid-thought."""

    text: str
    truncated: bool
    round_no: int


class AdminSubject(BaseModel):
    id: UUID
    name: str
    state: str
    languages: tuple[str, ...]
    current_outline_version: int | None


class AdminSource(BaseModel):
    id: UUID
    filename: str
    media_type: str
    status: str
    page_count: int | None
    detected_language: str | None
    error: str | None
