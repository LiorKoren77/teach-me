from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        """Indices into `documents`, best first, at most top_k."""
        ...
