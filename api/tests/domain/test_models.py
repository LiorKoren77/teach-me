from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import Chunk, ChunkRecord, SourceStatus


def test_chunk_content_prepends_context():
    chunk = Chunk(context="From chapter 3 on climate.", text="The biosphere is...", page_start=2, page_end=2)
    assert chunk.content == "From chapter 3 on climate.\n\nThe biosphere is..."


def test_source_status_values_are_stable_strings():
    assert SourceStatus.READY == "ready"
    assert [s.value for s in SourceStatus] == [
        "uploaded", "extracting", "chunking", "indexing", "ready", "failed",
    ]


def test_chunk_record_is_hashable_and_carries_model():
    record = ChunkRecord(
        id=uuid4(), source_id=uuid4(), subject_id=uuid4(),
        chunk=Chunk(context="c", text="t", page_start=0, page_end=0),
        embedding=(0.1, 0.2), embedding_model="voyage-4", tokens=("t",),
    )
    assert record.embedding_model == "voyage-4"
    assert hash(record)
