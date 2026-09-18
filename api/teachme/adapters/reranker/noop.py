from __future__ import annotations

from collections.abc import Sequence


class NoopReranker:
    """Keeps the fused order. For local runs without a Voyage key."""

    name = "noop"

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        return list(range(min(top_k, len(documents))))
