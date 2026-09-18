from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from teachme.ports.llm import (
    LLMCapabilities,
    LLMParseError,
    LLMUsage,
    OnDelta,
    StructuredRequest,
    StructuredResult,
    T,
    TextRequest,
    TextResult,
)

Responder = Callable[[StructuredRequest], BaseModel]
TextResponder = Callable[[TextRequest], str]

CHUNK_CHARS = 5

DEFAULT_MEDIA_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "text/plain", "text/markdown"})


class FakeLLM:
    """Deterministic stand-in: one responder per output schema. Records every request.

    `teachme.ingestion.fake_responders.default_responders()` and
    `teachme.generation.fake_responders.default_responders()` provide responders for the
    ingestion and generation schemas respectively, so the whole pipeline runs without an API
    key; see `teachme.container.build_llm` for how the fake stack combines them."""

    name = "fake"

    def __init__(
        self,
        responders: dict[type[BaseModel], Responder] | None = None,
        media_types: frozenset[str] = DEFAULT_MEDIA_TYPES,
        text_responder: TextResponder | None = None,
    ) -> None:
        self._responders = dict(responders or {})
        self._media_types = media_types
        self._text_responder = text_responder
        self.calls: list[StructuredRequest | TextRequest] = []

    def set_responder(self, schema: type[BaseModel], responder: Responder) -> None:
        """Install or replace the responder for one output schema. Tests use this to make a
        single step fail or answer differently without reaching into private state."""
        self._responders[schema] = responder

    def set_text_responder(self, responder: TextResponder) -> None:
        """Install or replace the responder behind `stream_text`."""
        self._text_responder = responder

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(media_types=self._media_types)

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        self.calls.append(request)
        responder = self._responders.get(schema)
        if responder is None:
            raise LLMParseError(f"FakeLLM has no responder for {schema.__name__}")
        output = responder(request)
        if not isinstance(output, schema):
            raise LLMParseError(f"responder for {schema.__name__} returned {type(output).__name__}")
        usage = LLMUsage(input_tokens=1000, output_tokens=200)
        return StructuredResult(output=output, usage=usage, model="fake-model")

    def stream_text(self, request: TextRequest, *, on_delta: OnDelta) -> TextResult:
        self.calls.append(request)
        if self._text_responder is None:
            raise LLMParseError("FakeLLM has no text responder")
        text = self._text_responder(request)
        for start in range(0, len(text), CHUNK_CHARS):
            on_delta(text[start : start + CHUNK_CHARS])
        usage = LLMUsage(input_tokens=500, output_tokens=100)
        return TextResult(text=text, usage=usage, model="fake-model")
