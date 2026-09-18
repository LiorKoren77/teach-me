from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high"]


class LLMError(Exception):
    """Base for failures the adapter could not resolve."""


class LLMRefused(LLMError):
    """The model declined the request (stop_reason refusal)."""


class LLMOutputTruncated(LLMError):
    """Output hit max_tokens; the caller should split the input or raise the limit."""


class LLMParseError(LLMError):
    """The response did not parse into the requested schema."""


@dataclass(frozen=True)
class LLMCapabilities:
    media_types: frozenset[str]


@dataclass(frozen=True)
class ContentPart:
    kind: Literal["text", "document", "image"]
    text: str | None = None
    data: bytes | None = None
    media_type: str | None = None

    @staticmethod
    def of_text(value: str) -> ContentPart:
        return ContentPart(kind="text", text=value)

    @staticmethod
    def of_document(data: bytes, media_type: str) -> ContentPart:
        return ContentPart(kind="document", data=data, media_type=media_type)

    @staticmethod
    def of_image(data: bytes, media_type: str) -> ContentPart:
        return ContentPart(kind="image", data=data, media_type=media_type)


@dataclass(frozen=True)
class StructuredRequest:
    purpose: str  # telemetry tag, e.g. "ingest.read_pages"
    model: str
    system: str
    parts: tuple[ContentPart, ...]
    max_tokens: int = 16000
    effort: Effort = "medium"


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    output: T
    usage: LLMUsage
    model: str


class LLMProvider(Protocol):
    name: str

    def capabilities(self) -> LLMCapabilities: ...

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]: ...
