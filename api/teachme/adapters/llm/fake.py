from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from teachme.ports.llm import (
    LLMCapabilities,
    LLMParseError,
    LLMUsage,
    StructuredRequest,
    StructuredResult,
    T,
)

Responder = Callable[[StructuredRequest], BaseModel]

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
    ) -> None:
        self._responders = dict(responders or {})
        self._media_types = media_types
        self.calls: list[StructuredRequest] = []

    def set_responder(self, schema: type[BaseModel], responder: Responder) -> None:
        """Install or replace the responder for one output schema. Tests use this to make a
        single step fail or answer differently without reaching into private state."""
        self._responders[schema] = responder

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
