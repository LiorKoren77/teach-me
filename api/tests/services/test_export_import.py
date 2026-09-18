from __future__ import annotations

import json
from uuid import UUID

import pytest

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.domain.models import Chunk, ChunkRecord, SubjectState
from teachme.ingestion.bundle import BundleReader, bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.repositories.usage import UsageRepository
from tests.helpers import make_pdf


def _container(make_container, embed_model="fake-embed"):
    container = make_container(pages_per_read_batch=2, pages_per_chunk_batch=2)
    if embed_model != "fake-embed":
        container.__dict__["embedder"] = FakeEmbedder(model=embed_model)
    return container


def _ingested(container, name="Geo"):
    subject = container.subject_service.get_or_create(name)
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(3))
    container.pipeline.ingest_source(source.id)
    return subject, source


def _embed_calls(container):
    rows = UsageRepository(container.conn).summarize()
    return sum(r["calls"] for r in rows if r["purpose"] == "embed.documents")


def test_export_writes_bundle_folder(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    reader = BundleReader(LocalFileStore(out), "")
    assert reader.meta().page_count == 3 and len(reader.pages()) == 3
    assert len(reader.chunks()) == 3 and len(reader.embeddings()) == 3


def test_import_reuses_vectors_when_model_matches(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    before = _embed_calls(container)

    target = container.subject_service.get_or_create("Geo copy")
    imported = container.export_import.import_source(target, out)
    assert imported.status.value == "ready" and imported.page_count == 3
    assert container.search.count(target.id) == 3
    assert _embed_calls(container) == before  # no re-embedding
    assert len(container.pages.list(imported.id)) == 3


def test_export_chunk_order_is_stable_across_runs(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)

    # Two extra chunks tied on the same page range as the existing page-0 chunk, inserted with
    # ids on opposite ends of the id space and in an order that contradicts id order - this pins
    # down the tie-break that ORDER BY page_start, page_end alone leaves unspecified.
    vector = container.embedder.embed_documents(["tie"]).vectors[0]
    tied = [
        ChunkRecord(
            id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            source_id=source.id,
            subject_id=subject.id,
            chunk=Chunk(context="ctx", text="tied-high", page_start=0, page_end=0),
            embedding=vector,
            embedding_model=container.embedder.model,
            tokens=("tied-high",),
        ),
        ChunkRecord(
            id=UUID("00000000-0000-0000-0000-000000000000"),
            source_id=source.id,
            subject_id=subject.id,
            chunk=Chunk(context="ctx", text="tied-low", page_start=0, page_end=0),
            embedding=vector,
            embedding_model=container.embedder.model,
            tokens=("tied-low",),
        ),
    ]
    container.search.upsert(tied)

    out1 = container.export_import.export_source(source.id, tmp_path / "export1")
    out2 = container.export_import.export_source(source.id, tmp_path / "export2")
    bytes1 = (out1 / "chunks.jsonl").read_bytes()
    bytes2 = (out2 / "chunks.jsonl").read_bytes()
    assert bytes1 == bytes2

    rows = [json.loads(line) for line in bytes1.decode().splitlines()]
    page_zero_texts = [row["text"] for row in rows if row["page_start"] == 0]
    assert page_zero_texts[0] == "tied-low"
    assert page_zero_texts[-1] == "tied-high"


def test_import_replaces_existing_import_of_same_bundle(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")

    target = container.subject_service.get_or_create("Geo copy")
    first = container.export_import.import_source(target, out)
    second = container.export_import.import_source(target, out)

    assert first.id == second.id
    assert len(container.sources.list_by_subject(target.id)) == 1
    assert container.search.count(target.id) == 3


def test_import_into_published_subject_is_locked(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")

    target = container.subject_service.get_or_create("Geo copy")
    container.subject_service.set_state(target, SubjectState.PUBLISHED)
    target = container.subject_service.require(target.name)

    with pytest.raises(SubjectLocked):
        container.export_import.import_source(target, out)


def test_import_rolls_back_and_skips_bundle_mirror_on_failure(db, make_container, tmp_path, monkeypatch):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")

    target = container.subject_service.get_or_create("Geo copy")

    def boom(records):
        raise RuntimeError("boom")

    monkeypatch.setattr(container.search, "upsert", boom)

    with pytest.raises(RuntimeError):
        container.export_import.import_source(target, out)

    assert container.sources.list_by_subject(target.id) == []
    subject_slug = bundle_slug(target.name, target.id)
    assert not (tmp_path / "digest" / subject_slug).exists()


def test_import_reembeds_when_model_differs(db, make_container, tmp_path):
    container = _container(make_container)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    container.close()

    other = _container(make_container, embed_model="fake-embed-v2")
    target = other.subject_service.get_or_create("Geo v2")
    other.export_import.import_source(target, out)
    records = other.search.list_by_source(other.sources.list_by_subject(target.id)[0].id)
    assert {r.embedding_model for r in records} == {"fake-embed-v2"}
