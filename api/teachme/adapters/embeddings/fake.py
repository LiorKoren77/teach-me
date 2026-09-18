from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from teachme.ports.embeddings import EmbeddingResult


class FakeEmbedder:
    """Deterministic unit vectors derived from a hash of the text. Same text, same vector."""

    name = "fake"

    def __init__(self, dimension: int = 1024, model: str = "fake-embed") -> None:
        self.dimension = dimension
        self.model = model

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vector(t) for t in texts],
            tokens=sum(max(1, len(t) // 4) for t in texts),
        )

    def embed_query(self, text: str) -> EmbeddingResult:
        return self.embed_documents([text])

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend((b / 127.5) - 1.0 for b in digest)
            counter += 1
        values = values[: self.dimension]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
