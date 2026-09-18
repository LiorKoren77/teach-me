from __future__ import annotations

import time
from collections.abc import Sequence

from teachme.ports.embeddings import Embedder, EmbeddingResult
from teachme.ports.llm import LLMCapabilities, LLMProvider, StructuredRequest, StructuredResult, T
from teachme.telemetry.usage import UsageRecorder


class RecordingLLM:
    """Wraps any LLMProvider and writes one usage row per call. Adapters stay pure."""

    def __init__(self, inner: LLMProvider, recorder: UsageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder
        self.name = inner.name

    def capabilities(self) -> LLMCapabilities:
        return self._inner.capabilities()

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        started = time.perf_counter()
        result = self._inner.generate_structured(request, schema)
        self._recorder.record_llm(
            purpose=request.purpose,
            provider=self._inner.name,
            model=result.model,
            usage=result.usage,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result


class RecordingEmbedder:
    def __init__(self, inner: Embedder, recorder: UsageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder
        self.name = inner.name
        self.model = inner.model
        self.dimension = inner.dimension

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        return self._timed("embed.documents", lambda: self._inner.embed_documents(texts))

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._timed("embed.query", lambda: self._inner.embed_query(text))

    def _timed(self, purpose: str, call) -> EmbeddingResult:
        started = time.perf_counter()
        result = call()
        self._recorder.record_embedding(
            purpose=purpose,
            provider=self._inner.name,
            model=self._inner.model,
            tokens=result.tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result
