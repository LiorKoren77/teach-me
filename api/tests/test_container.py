from __future__ import annotations

import psycopg
import pytest

from teachme.container import ConfigurationError
from teachme.domain.models import SourceStatus
from teachme.ingestion.detect_language import DetectedLanguage
from tests.helpers import make_pdf


def test_container_builds_fake_stack_and_is_ready(make_container):
    container = make_container()
    container.check_ready()
    assert container.llm.name == "fake" and container.embedder.model == "fake-embed"
    assert container.files.name == "local" and container.job_runner.name == "inprocess"
    assert [s.name for s in container.bundle_stores] == ["local:digest/", "local"]
    assert container.pipeline is container.pipeline  # cached


def test_s3_without_bucket_is_a_configuration_error(make_container):
    container = make_container(file_store="s3")
    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        _ = container.files


def test_check_ready_surfaces_configuration_errors(make_container):
    container = make_container(file_store="s3")
    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        container.check_ready()


def test_check_ready_leaves_the_connection_idle(make_container):
    container = make_container()
    container.check_ready()
    assert container.conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_dimension_mismatch_is_a_configuration_error(make_container, monkeypatch):
    container = make_container()
    monkeypatch.setattr(container.embedder, "dimension", 8)
    with pytest.raises(ConfigurationError, match="dimension"):
        container.check_ready()


def test_usage_rows_survive_a_failed_pipeline_step(db, make_container):
    """Telemetry runs on its own autocommit connection, so the rollback that unwinds a failed
    step leaves the rows describing what was already paid for."""
    container = make_container()
    subject = container.subject_service.get_or_create("Geo", ["en"])
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(2))

    def boom(request):
        raise RuntimeError("language service down")

    container.llm.inner.set_responder(DetectedLanguage, boom)
    with pytest.raises(RuntimeError):
        container.pipeline.ingest_source(source.id)

    assert container.sources.get(source.id).status == SourceStatus.FAILED
    purposes = {row["purpose"] for row in container.usage_repo.summarize(subject_id=subject.id)}
    assert "ingest.read_pages" in purposes
