from __future__ import annotations

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.container import Container
from teachme.ingestion.bundle import BundleReader
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from tests.helpers import make_pdf


def _container(migrated_database, tmp_path, embed_model="fake-embed"):
    settings = Settings(
        _env_file=None,
        database_url=migrated_database,
        llm_provider="fake",
        embeddings_provider="fake",
        reranker_provider="noop",
        file_store="local",
        local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest",
        pages_per_read_batch=2,
        pages_per_chunk_batch=2,
    )
    container = Container(settings)
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


def test_export_writes_bundle_folder(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    reader = BundleReader(LocalFileStore(out), "")
    assert reader.meta().page_count == 3 and len(reader.pages()) == 3
    assert len(reader.chunks()) == 3 and len(reader.embeddings()) == 3
    container.close()


def test_import_reuses_vectors_when_model_matches(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    before = _embed_calls(container)

    target = container.subject_service.get_or_create("Geo copy")
    imported = container.export_import.import_source(target, out)
    assert imported.status.value == "ready" and imported.page_count == 3
    assert container.search.count(target.id) == 3
    assert _embed_calls(container) == before  # no re-embedding
    assert len(container.pages.list(imported.id)) == 3
    container.close()


def test_import_reembeds_when_model_differs(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    container.close()

    other = _container(migrated_database, tmp_path, embed_model="fake-embed-v2")
    target = other.subject_service.get_or_create("Geo v2")
    other.export_import.import_source(target, out)
    records = other.search.list_by_source(other.sources.list_by_subject(target.id)[0].id)
    assert {r.embedding_model for r in records} == {"fake-embed-v2"}
    other.close()
