from __future__ import annotations

from uuid import uuid4

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.reranker.noop import NoopReranker
from teachme.domain.models import Chunk, ChunkRecord
from teachme.domain.text.normalize import tokenize
from teachme.retrieval.hybrid import HybridSearch


def _record(subject_id, text, embedder):
    return ChunkRecord(
        id=uuid4(),
        source_id=uuid4(),
        subject_id=subject_id,
        chunk=Chunk(context="ctx", text=text, page_start=0, page_end=0),
        embedding=tuple(embedder.embed_documents([f"ctx\n\n{text}"]).vectors[0]),
        embedding_model=embedder.model,
        tokens=tuple(tokenize(text, "en")),
    )


def test_hybrid_returns_lexical_match_even_when_dense_misses():
    embedder = FakeEmbedder(dimension=32)
    search = InMemoryChunkSearch(dimension=32)
    subject_id = uuid4()
    target = _record(subject_id, "The atmosphere protects the biosphere", embedder)
    search.upsert([target] + [_record(subject_id, f"filler text number {i}", embedder) for i in range(5)])

    hybrid = HybridSearch(embedder, search, NoopReranker(), candidates=10, final_k=3)
    hits = hybrid.search(subject_id, "what protects the biosphere?", language_code="en")
    assert hits and hits[0].chunk_id == target.id
    assert len(hits) <= 3


def test_hybrid_empty_subject():
    embedder = FakeEmbedder(dimension=8)
    hybrid = HybridSearch(embedder, InMemoryChunkSearch(dimension=8), NoopReranker())
    assert hybrid.search(uuid4(), "anything", language_code="he") == []
