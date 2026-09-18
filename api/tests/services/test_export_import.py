from __future__ import annotations

import pytest

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.domain.models import SubjectState
from teachme.ingestion.bundle import BundleReader
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
