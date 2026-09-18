from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from teachme.domain.models import ChunkHit, ChunkRecord


class ChunkSearch(Protocol):
    name: str

    def dimension(self) -> int:
        """Vector width the store accepts. The container checks it against the embedder."""
        ...

    def upsert(self, records: Sequence[ChunkRecord]) -> None: ...

    def delete_by_source(self, source_id: UUID) -> None: ...

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]: ...

    def count(self, subject_id: UUID) -> int: ...

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]: ...

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]: ...
