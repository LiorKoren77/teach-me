from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import ChunkHit
from teachme.domain.retrieval.fusion import reciprocal_rank_fusion


def hit(chunk_id, score=1.0):
    return ChunkHit(
        chunk_id=chunk_id, source_id=uuid4(), content=str(chunk_id), page_start=0, page_end=0, score=score
    )


def test_item_in_both_lists_ranks_first():
    a, b, c = uuid4(), uuid4(), uuid4()
    dense = [hit(a), hit(b)]
    lexical = [hit(c), hit(a)]
    fused = reciprocal_rank_fusion([dense, lexical])
    assert [h.chunk_id for h in fused] == [a, c, b] or [h.chunk_id for h in fused][0] == a
    assert fused[0].chunk_id == a


def test_dedupes_and_keeps_first_seen_hit_object():
    a = uuid4()
    first = hit(a, score=0.9)
    fused = reciprocal_rank_fusion([[first], [hit(a, score=0.1)]])
    assert len(fused) == 1 and fused[0] is first


def test_empty_rankings():
    assert reciprocal_rank_fusion([[], []]) == []
