from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from teachme.domain.models import ChunkHit


def reciprocal_rank_fusion(rankings: Sequence[Sequence[ChunkHit]], k: int = 60) -> list[ChunkHit]:
    """Fuse ranked lists by summing 1/(k+rank). Needs no score calibration, which matters
    because a cosine similarity and a text-search rank are not on comparable scales."""
    scores: dict[UUID, float] = {}
    first_seen: dict[UUID, ChunkHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            first_seen.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [first_seen[chunk_id] for chunk_id in order]
