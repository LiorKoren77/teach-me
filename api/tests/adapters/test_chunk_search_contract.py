from __future__ import annotations

import math
from uuid import uuid4

import pytest

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.domain.models import Chunk, ChunkRecord
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository

DIM = 1024


def _unit(index: int) -> tuple[float, ...]:
    vec = [0.0] * DIM
    vec[index] = 1.0
    return tuple(vec)


def _mix(a: int, b: int) -> tuple[float, ...]:
    vec = [0.0] * DIM
    vec[a] = vec[b] = 1 / math.sqrt(2)
    return tuple(vec)


@pytest.fixture(params=["memory", "pgvector"])
def search_env(request):
    if request.param == "memory":
        subject_id, source_id, other_source = uuid4(), uuid4(), uuid4()
        yield InMemoryChunkSearch(dimension=DIM), subject_id, source_id, other_source
    else:
        db = request.getfixturevalue("db")
        subject = SubjectRepository(db).create(f"S-{uuid4()}", ["en"])
        sources = SourceRepository(db)
        a = sources.create(subject.id, "a.pdf", "application/pdf", "k1", 1)
        b = sources.create(subject.id, "b.pdf", "application/pdf", "k2", 1)
        yield PgVectorChunkSearch(db), subject.id, a.id, b.id


def _record(subject_id, source_id, text, tokens, embedding):
    return ChunkRecord(
        id=uuid4(), source_id=source_id, subject_id=subject_id,
        chunk=Chunk(context="ctx", text=text, page_start=0, page_end=1),
        embedding=embedding, embedding_model="fake-embed", tokens=tuple(tokens),
    )


def test_dimension(search_env):
    search, *_ = search_env
    assert search.dimension() == DIM


def test_upsert_dense_lexical_delete(search_env):
    search, subject_id, source_id, other_source = search_env
    r1 = _record(subject_id, source_id, "the biosphere", ["biosphere"], _unit(0))
    r2 = _record(subject_id, source_id, "the atmosphere", ["atmosphere"], _unit(1))
    r3 = _record(subject_id, other_source, "biosphere and atmosphere", ["biosphere", "atmosphere"], _mix(0, 1))
    search.upsert([r1, r2, r3])
    assert search.count(subject_id) == 3

    dense = search.dense(subject_id, _unit(0), k=2)
    assert [h.chunk_id for h in dense] == [r1.id, r3.id]
    assert dense[0].score > dense[1].score
    assert dense[0].content == "ctx\n\nthe biosphere"

    lexical = search.lexical(subject_id, ["atmosphere"], k=5)
    assert {h.chunk_id for h in lexical} == {r2.id, r3.id}
    assert search.lexical(subject_id, [], k=5) == []

    listed = search.list_by_source(source_id)
    assert {r.id for r in listed} == {r1.id, r2.id}
    assert listed[0].embedding_model == "fake-embed" and len(listed[0].embedding) == DIM

    search.delete_by_source(source_id)
    assert search.count(subject_id) == 1


def test_upsert_is_idempotent_on_id(search_env):
    search, subject_id, source_id, _ = search_env
    record = _record(subject_id, source_id, "v1", ["v1"], _unit(2))
    search.upsert([record])
    updated = ChunkRecord(
        id=record.id, source_id=source_id, subject_id=subject_id,
        chunk=Chunk(context="ctx", text="v2", page_start=0, page_end=0),
        embedding=_unit(3), embedding_model="fake-embed", tokens=("v2",),
    )
    search.upsert([updated])
    assert search.count(subject_id) == 1
    assert search.list_by_source(source_id)[0].chunk.text == "v2"
