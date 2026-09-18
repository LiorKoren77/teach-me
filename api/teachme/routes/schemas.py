from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from teachme.domain.models import Source, Subject
from teachme.repositories.admin_actions import AdminActionRow
from teachme.services.tutorial import TutorialStatus


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


class StudentSource(BaseModel):
    """What a student may know about a source: enough to caption a page reference, and nothing
    the admin list reserves - no id, no file key, no ingestion status, no error text."""

    filename: str
    media_type: str
    page_count: int | None


class AdminSubject(BaseModel):
    id: UUID
    name: str
    state: str
    languages: tuple[str, ...]
    current_outline_version: int | None

    @classmethod
    def of(cls, subject: Subject) -> AdminSubject:
        return cls(
            id=subject.id,
            name=subject.name,
            state=subject.state.value,
            languages=subject.languages,
            current_outline_version=subject.current_outline_version,
        )


class AdminSource(BaseModel):
    id: UUID
    filename: str
    media_type: str
    status: str
    page_count: int | None
    detected_language: str | None
    error: str | None

    @classmethod
    def of(cls, source: Source) -> AdminSource:
        return cls(
            id=source.id,
            filename=source.filename,
            media_type=source.media_type,
            status=source.status.value,
            page_count=source.page_count,
            detected_language=source.detected_language,
            error=source.error,
        )


class AdminUpload(AdminSource):
    """An accepted upload: the registered source, plus the ingestion job now queued for it. The
    pane follows the source's own status rather than this job, because ingestion is resumable and
    may take several jobs to finish."""

    job_id: UUID

    @classmethod
    def of_job(cls, source: Source, job_id: UUID) -> AdminUpload:
        return cls(**AdminSource.of(source).model_dump(), job_id=job_id)


class AdminJobRef(BaseModel):
    """All an action that only starts work has to say."""

    job_id: UUID


class AdminJob(BaseModel):
    id: UUID
    kind: str
    status: str
    attempts: int
    error: str | None


class AdminCapabilities(BaseModel):
    """What this deployment's file picker may offer: a property of the configured LLM adapter and
    of ALLOWED_UPLOAD_TYPES, so it is asked for rather than hard-coded in the client."""

    accepted_media_types: list[str]
    max_upload_bytes: int


class AdminLanguageStatus(BaseModel):
    language: str
    parts_ready: int
    parts_total: int
    questions: int
    complete: bool
    failed: list[int]


class AdminSubjectStatus(BaseModel):
    """`TutorialService.status` as the admin pane reads it - the same numbers
    `teachme tutorial status` prints. `publishable_version` names the version `publish` would
    actually select, which may be older than the one detailed here."""

    state: str
    outline_version: int | None
    published_version: int | None
    parts_total: int
    languages: list[AdminLanguageStatus]
    publishable: bool
    publishable_version: int | None

    @classmethod
    def of(cls, status: TutorialStatus) -> AdminSubjectStatus:
        return cls(
            state=status.state.value,
            outline_version=status.outline_version,
            published_version=status.published_version,
            parts_total=status.parts,
            languages=[
                AdminLanguageStatus(
                    language=lang.language,
                    parts_ready=lang.parts_ready,
                    parts_total=lang.parts_total,
                    questions=lang.questions,
                    complete=lang.complete,
                    failed=list(lang.failed),
                )
                for lang in status.languages
            ],
            publishable=status.publishable,
            publishable_version=status.publishable_version,
        )


class AdminAction(BaseModel):
    """One line of the admin audit trail: who did what to which subject, and when."""

    id: UUID
    user_id: str
    action: str
    subject_id: UUID | None
    source_id: UUID | None
    detail: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, row: AdminActionRow) -> AdminAction:
        return cls(**vars(row))
