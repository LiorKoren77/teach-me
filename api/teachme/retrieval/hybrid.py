from __future__ import annotations

from uuid import UUID

from teachme.domain.models import ChunkHit
from teachme.domain.retrieval.fusion import reciprocal_rank_fusion
from teachme.domain.text.normalize import tokenize
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder
from teachme.ports.reranker import Reranker


class HybridSearch:
    """dense + lexical -> reciprocal rank fusion -> rerank -> top k.

    Anthropic's contextual-retrieval measurements: 150 candidates reranked to 20 beats 5 or 10."""

    def __init__(
        self,
        embedder: Embedder,
        search: ChunkSearch,
        reranker: Reranker,
        candidates: int = 150,
        final_k: int = 20,
    ) -> None:
        self._embedder = embedder
        self._search = search
        self._reranker = reranker
        self._candidates = candidates
        self._final_k = final_k

    def search(
        self, subject_id: UUID, query: str, language_code: str, k: int | None = None
    ) -> list[ChunkHit]:
        k = self._final_k if k is None else k
        vector = self._embedder.embed_query(query).vectors[0]
        dense = self._search.dense(subject_id, vector, self._candidates)
        lexical = self._search.lexical(subject_id, tokenize(query, language_code), self._candidates)
        fused = reciprocal_rank_fusion([dense, lexical])[: self._candidates]
        if not fused:
            return []
        order = self._reranker.rerank(query, [hit.content for hit in fused], top_k=k)
        return [fused[index] for index in order if 0 <= index < len(fused)][:k]
