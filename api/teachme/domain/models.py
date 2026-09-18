from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teachme.domain.glossary.render import Frequency


class SubjectState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class SourceStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class Frozen(BaseModel):
    """Immutable, hashable value object. All domain records except Source derive from it."""

    model_config = ConfigDict(frozen=True)


class Subject(Frozen):
    id: UUID
    name: str
    state: SubjectState
    languages: tuple[str, ...]
    created_by: str | None = None
    pass_threshold: int = 50
    max_rounds: int = 3
    questions_per_round: int = 5
    bank_size_per_part: int = 25
    gloss_frequency: Frequency = "first"
    current_outline_version: int | None = None


class Source(BaseModel):
    """Mutable: status changes as the pipeline advances."""

    id: UUID
    subject_id: UUID
    filename: str
    media_type: str
    file_key: str
    size: int = Field(ge=0)
    status: SourceStatus
    page_count: int | None = Field(default=None, ge=0)
    vision_pages: int | None = None
    detected_language: str | None = None
    error: str | None = None
    resume_status: SourceStatus | None = None


class Page(Frozen):
    page_index: int = Field(ge=0, description="0-based position in the source")
    printed_number: str | None = Field(default=None, description="the number printed on the page, if any")
    text: str = Field(description="Markdown, figure blocks included")


class Figure(Frozen):
    page_index: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    kind: str
    caption: str
    description: str


class Chunk(Frozen):
    context: str
    text: str
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)

    @property
    def content(self) -> str:
        """What gets embedded and indexed: the situating context first."""
        return f"{self.context}\n\n{self.text}"

    @model_validator(mode="after")
    def _page_range_is_ordered(self) -> Chunk:
        if self.page_end < self.page_start:
            raise ValueError(f"page_end ({self.page_end}) must not be before page_start ({self.page_start})")
        return self


class ChunkRecord(Frozen):
    id: UUID
    source_id: UUID
    subject_id: UUID
    chunk: Chunk
    embedding: tuple[float, ...]
    embedding_model: str
    tokens: tuple[str, ...]


class ChunkHit(Frozen):
    chunk_id: UUID
    source_id: UUID
    content: str
    page_start: int
    page_end: int
    score: float


class ContentStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class QuestionKind(StrEnum):
    FREE_TEXT = "free_text"
    MULTIPLE_CHOICE = "multiple_choice"


class Outline(Frozen):
    id: UUID
    subject_id: UUID
    version: int
    model: str


class _PageRange(Frozen):
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> _PageRange:
        if self.page_end < self.page_start:
            raise ValueError("page_end must not precede page_start")
        return self


class Part(_PageRange):
    id: UUID
    outline_id: UUID
    position: int = Field(ge=0)
    title: str


class Section(_PageRange):
    id: UUID
    part_id: UUID
    position: int = Field(ge=0)
    title: str = ""


class GlossaryTerm(Frozen):
    id: UUID
    outline_id: UUID
    slug: str
    source_term: str
    definition: str
    pages: tuple[int, ...]


class GlossaryTranslation(Frozen):
    term_id: UUID
    language: str
    term: str


class PartContent(Frozen):
    part_id: UUID
    language: str
    title: str
    body: str  # Markdown with {{term:slug|words}} placeholders
    key_points: tuple[str, ...]
    status: ContentStatus
    model: str
    error: str | None = None


class SectionContent(Frozen):
    section_id: UUID
    language: str
    title: str
    summary: str


class Question(Frozen):
    id: UUID
    section_id: UUID
    language: str
    kind: QuestionKind
    prompt: str
    expected_answer: str
    rubric: tuple[str, ...]
    key_terms: tuple[str, ...]
    exact_values: tuple[str, ...]
    choices: tuple[str, ...] | None = None
    correct_choice: int | None = None
    position: int = 0

    @model_validator(mode="after")
    def _choices_match_kind(self) -> Question:
        if self.kind == QuestionKind.MULTIPLE_CHOICE:
            if not self.choices or len(self.choices) < 2:
                raise ValueError("multiple choice needs at least two choices")
            if self.correct_choice is None or not 0 <= self.correct_choice < len(self.choices):
                raise ValueError("correct_choice must index into choices")
        elif self.choices is not None or self.correct_choice is not None:
            raise ValueError("free text questions carry no choices")
        return self


class PartStatus(StrEnum):
    NOT_STARTED = "not_started"
    LEARNING = "learning"
    QUIZZING = "quizzing"
    REINFORCING = "reinforcing"
    PASSED = "passed"
    STALLED = "stalled"


class AttemptStatus(StrEnum):
    ACTIVE = "active"
    PASSED = "passed"
    FAILED = "failed"


class Grade(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    OFF_TOPIC = "off_topic"
    JUNK = "junk"


class RelevanceBand(StrEnum):
    JUNK = "junk"
    LOW = "low"
    UNCERTAIN = "uncertain"
    HIGH = "high"


class Route(StrEnum):
    REJECT_JUNK = "reject_junk"
    CHECK = "check"  # Haiku relevance check before grading
    GRADER = "grader"
    REJECT_OFF_TOPIC = "reject_off_topic"
    CODE = "code"  # multiple choice graded in code


_POINTS = {
    Grade.CORRECT: 1.0,
    Grade.PARTIAL: 0.5,
    Grade.INCORRECT: 0.0,
    Grade.OFF_TOPIC: 0.0,
    Grade.JUNK: 0.0,
}


class PartProgress(Frozen):
    id: UUID
    user_id: str
    subject_id: UUID
    part_id: UUID
    outline_version: int = Field(ge=0)
    status: PartStatus
    best_score: float | None = Field(default=None, ge=0, le=1, description="best round score, a fraction")
    rounds_used: int = Field(default=0, ge=0)


class Attempt(Frozen):
    id: UUID
    user_id: str
    part_id: UUID
    language: str
    status: AttemptStatus
    round_no: int = Field(default=0, ge=0, description="0 until the first round is sampled")


class AttemptQuestion(Frozen):
    id: UUID
    attempt_id: UUID
    question_id: UUID
    position: int = Field(ge=0)
    round_no: int = Field(default=1, ge=0)
    answer_text: str | None = None
    answer_choice: int | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    relevance_band: RelevanceBand | None = None
    route: Route | None = None
    check_verdict: str | None = None
    grade: Grade | None = None
    rubric_covered: tuple[int, ...] = ()
    missed_concepts: tuple[str, ...] = ()
    feedback: str | None = None
    rejections: int = 0

    @property
    def points(self) -> float | None:
        return None if self.grade is None else _POINTS[self.grade]


class Reexplanation(Frozen):
    id: UUID
    attempt_id: UUID
    round_no: int
    section_ids: tuple[UUID, ...]
    language: str
    body: str
    model: str
