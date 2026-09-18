from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from teachme.domain.models import Chunk, ChunkRecord
from teachme.domain.text.normalize import tokenize
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder

EMBED_BATCH = 128


def index_chunks(
    embedder: Embedder,
    search: ChunkSearch,
    source_id: UUID,
    subject_id: UUID,
    chunks: Sequence[Chunk],
    language_code: str | None,
) -> list[ChunkRecord]:
    """Embed and write chunks, replacing whatever the source had before. Returns the records
    so the bundle can store the vectors."""
    records: list[ChunkRecord] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vectors = embedder.embed_documents([c.content for c in batch]).vectors
        for chunk, vector in zip(batch, vectors, strict=True):
            records.append(
                ChunkRecord(
                    id=uuid4(),
                    source_id=source_id,
                    subject_id=subject_id,
                    chunk=chunk,
                    embedding=tuple(vector),
                    embedding_model=embedder.model,
                    tokens=tuple(tokenize(chunk.content, language_code or "")),
                )
            )
    search.delete_by_source(source_id)
    search.upsert(records)
    return records
