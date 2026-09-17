from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class Source(BaseModel):
    """Mutable: status changes as the pipeline advances."""

    id: UUID
    subject_id: UUID
    filename: str
    media_type: str
    file_key: str
    size: int
    status: SourceStatus
    page_count: int | None = None
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
