from __future__ import annotations

import math
from types import SimpleNamespace

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.embeddings.voyage import VoyageEmbedder
from teachme.adapters.reranker.noop import NoopReranker
from teachme.adapters.reranker.voyage import VoyageReranker


class _VoyageStub:
    def __init__(self):
        self.embed_calls = []

    def embed(self, texts, model, input_type, output_dimension=None):
        self.embed_calls.append((list(texts), model, input_type, output_dimension))
        return SimpleNamespace(embeddings=[[0.0] * 4 for _ in texts], total_tokens=7 * len(texts))

    def rerank(self, query, documents, model, top_k):
        order = sorted(range(len(documents)), key=lambda i: len(documents[i]), reverse=True)[:top_k]
        return SimpleNamespace(results=[SimpleNamespace(index=i, relevance_score=1.0) for i in order])


def test_fake_embedder_is_deterministic_unit_length():
    emb = FakeEmbedder(dimension=16)
    a = emb.embed_documents(["hello"]).vectors[0]
    b = emb.embed_documents(["hello"]).vectors[0]
    assert a == b and len(a) == 16
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)
    assert emb.embed_query("hello").vectors[0] == a
    assert emb.embed_documents(["x", "y"]).tokens > 0


def test_voyage_embedder_batches_and_sums_tokens():
    stub = _VoyageStub()
    emb = VoyageEmbedder(model="voyage-4", dimension=4, client=stub, batch_size=2)
    result = emb.embed_documents(["a", "b", "c"])
    assert len(result.vectors) == 3 and result.tokens == 21
    assert [len(call[0]) for call in stub.embed_calls] == [2, 1]
    assert stub.embed_calls[0][2] == "document"
    assert all(call[3] == emb.dimension for call in stub.embed_calls)
    emb.embed_query("q")
    assert stub.embed_calls[-1][2] == "query"


def test_voyage_reranker_returns_indices():
    reranker = VoyageReranker(model="rerank-2.5", client=_VoyageStub())
    assert reranker.rerank("q", ["aa", "a", "aaa"], top_k=2) == [2, 0]


def test_noop_reranker_keeps_order():
    assert NoopReranker().rerank("q", ["a", "b", "c"], top_k=2) == [0, 1]
    assert NoopReranker().rerank("q", [], top_k=2) == []
