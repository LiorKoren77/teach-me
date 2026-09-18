from __future__ import annotations

import pytest

from teachme.container import ConfigurationError, Container
from teachme.domain.models import SourceStatus
from teachme.ingestion.detect_language import DetectedLanguage
from teachme.settings import Settings
from tests.helpers import make_pdf


def _settings(migrated_database, tmp_path, **overrides):
    base = dict(
        database_url=migrated_database,
        llm_provider="fake",
        embeddings_provider="fake",
        reranker_provider="noop",
        file_store="local",
        local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_container_builds_fake_stack_and_is_ready(migrated_database, tmp_path):
    container = Container(_settings(migrated_database, tmp_path))
    container.check_ready()
    assert container.llm.name == "fake" and container.embedder.model == "fake-embed"
    assert container.files.name == "local" and container.job_runner.name == "inprocess"
    assert [s.name for s in container.bundle_stores] == ["local:digest/", "local"]
    assert container.pipeline is container.pipeline  # cached
    container.close()


def test_s3_without_bucket_is_a_configuration_error(migrated_database, tmp_path):
    container = Container(_settings(migrated_database, tmp_path, file_store="s3"))
    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        _ = container.files


def test_dimension_mismatch_is_a_configuration_error(migrated_database, tmp_path, monkeypatch):
    container = Container(_settings(migrated_database, tmp_path))
    monkeypatch.setattr(container.embedder, "dimension", 8)
    with pytest.raises(ConfigurationError, match="dimension"):
        container.check_ready()


def test_usage_rows_survive_a_failed_pipeline_step(db, migrated_database, tmp_path):
    """Telemetry runs on its own autocommit connection, so the rollback that unwinds a failed
    step leaves the rows describing what was already paid for."""
    container = Container(_settings(migrated_database, tmp_path))
    try:
        subject = container.subject_service.get_or_create("Geo", ["en"])
        source = container.source_service.register(subject, "ch1.pdf", make_pdf(2))

        def boom(request):
            raise RuntimeError("language service down")

        container.llm._inner.set_responder(DetectedLanguage, boom)
        with pytest.raises(RuntimeError):
            container.pipeline.ingest_source(source.id)

        assert container.sources.get(source.id).status == SourceStatus.FAILED
        purposes = {row["purpose"] for row in container.usage_repo.summarize(subject_id=subject.id)}
        assert "ingest.read_pages" in purposes
    finally:
        container.close()
