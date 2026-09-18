from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from teachme.domain.models import ChunkHit, ChunkRecord


class InMemoryChunkSearch:
    name = "memory"

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension
        self._records: dict[UUID, ChunkRecord] = {}

    def dimension(self) -> int:
        return self._dimension

    def upsert(self, records: Sequence[ChunkRecord]) -> None:
        for record in records:
            if len(record.embedding) != self._dimension:
                raise ValueError(
                    f"embedding has {len(record.embedding)} dims, store expects {self._dimension}"
                )
            self._records[record.id] = record

    def delete_by_source(self, source_id: UUID) -> None:
        self._records = {k: v for k, v in self._records.items() if v.source_id != source_id}

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]:
        return [r for r in self._records.values() if r.source_id == source_id]

    def count(self, subject_id: UUID) -> int:
        return sum(1 for r in self._records.values() if r.subject_id == subject_id)

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]:
        scored = [
            (_cosine(vector, r.embedding), r) for r in self._records.values() if r.subject_id == subject_id
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [_hit(r, score) for score, r in scored[:k]]

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]:
        wanted = set(tokens)
        if not wanted:
            return []
        scored = []
        for r in self._records.values():
            if r.subject_id != subject_id:
                continue
            overlap = len(wanted & set(r.tokens))
            if overlap:
                scored.append((overlap / len(wanted), r))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [_hit(r, score) for score, r in scored[:k]]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _hit(record: ChunkRecord, score: float) -> ChunkHit:
    return ChunkHit(
        chunk_id=record.id,
        source_id=record.source_id,
        content=record.chunk.content,
        page_start=record.chunk.page_start,
        page_end=record.chunk.page_end,
        score=score,
    )
