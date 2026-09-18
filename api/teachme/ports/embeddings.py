from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    tokens: int


class Embedder(Protocol):
    name: str
    model: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult: ...

    def embed_query(self, text: str) -> EmbeddingResult: ...
