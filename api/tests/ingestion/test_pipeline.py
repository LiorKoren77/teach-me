from __future__ import annotations

import pytest

from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import SourceStatus, SubjectState
from teachme.ingestion.bundle import BundleReader, bundle_slug
from teachme.ingestion.contextualize import ChunksOut
from teachme.ingestion.detect_language import DetectedLanguage
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.fake_responders import default_responders
from teachme.ingestion.pipeline import IngestionPipeline, PipelineDeps
from teachme.repositories.figures import FigureRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from teachme.telemetry.prices import PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder
from tests.helpers import make_pdf


@pytest.fixture
def env(db):
    settings = Settings(
        _env_file=None,
        llm_provider="fake",
        embeddings_provider="fake",
        pages_per_read_batch=2,
        pages_per_chunk_batch=2,
    )
    files = InMemoryFileStore()
    recorder = UsageRecorder(UsageRepository(db), PriceTable())
    fake_llm = FakeLLM(default_responders())
    deps = PipelineDeps(
        conn=db,
        settings=settings,
        llm=RecordingLLM(fake_llm, recorder),
        embedder=RecordingEmbedder(FakeEmbedder(dimension=1024), recorder),
        search=PgVectorChunkSearch(db),
        files=files,
        bundle_stores=[PrefixedFileStore(files, "digest/")],
        subjects=SubjectRepository(db),
        sources=SourceRepository(db),
        pages=PageRepository(db),
        figures=FigureRepository(db),
    )
    subject = deps.subjects.create("Geo", ["en"])
    pdf = make_pdf(5)
    files.put("sources/x/ch1.pdf", pdf, "application/pdf")
    source = deps.sources.create(subject.id, "ch1.pdf", "application/pdf", "sources/x/ch1.pdf", len(pdf))
    db.commit()
    return deps, subject, source, fake_llm


def test_full_run_ends_ready_with_pages_chunks_bundle_and_usage(env):
    deps, subject, source, _ = env
    result = IngestionPipeline(deps).ingest_source(source.id)
    assert result.status == SourceStatus.READY and result.page_count == 5 and result.vision_pages == 5
    assert result.detected_language == "en"
    assert len(deps.pages.list(source.id)) == 5
    assert len(deps.figures.list(source.id)) == 3  # one per read batch of 2,2,1
    assert deps.search.count(subject.id) == 5

    reader = BundleReader(
        deps.bundle_stores[0],
        f"{bundle_slug('Geo', subject.id)}/{bundle_slug('ch1.pdf', source.id)}",
    )
    assert reader.meta().page_count == 5 and reader.meta().embedding_model == "fake-embed"
    assert len(reader.pages()) == 5 and len(reader.chunks()) == 5 and len(reader.embeddings()) == 5

    usage = UsageRepository(deps.conn).summarize(subject_id=subject.id)
    purposes = {row["purpose"] for row in usage}
    assert {
        "ingest.read_pages",
        "ingest.detect_language",
        "ingest.contextualize",
        "embed.documents",
    } <= purposes
    assert all(
        row["source_id"] == source.id
        for row in deps.conn.execute("SELECT source_id FROM llm_usage").fetchall()
    )


def test_failure_records_resume_point_and_rerun_skips_extraction(env):
    deps, subject, source, fake_llm = env
    calls = {"n": 0}
    good = default_responders()[ChunksOut]

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("upstream hiccup")
        return good(request)

    fake_llm.set_responder(ChunksOut, flaky)
    pipeline = IngestionPipeline(deps)
    with pytest.raises(RuntimeError):
        pipeline.ingest_source(source.id)
    failed = deps.sources.get(source.id)
    assert failed.status == SourceStatus.FAILED and failed.resume_status == SourceStatus.CHUNKING
    assert "upstream hiccup" in failed.error
    read_calls_before = sum(1 for r in fake_llm.calls if r.purpose == "ingest.read_pages")

    result = pipeline.ingest_source(source.id)
    assert result.status == SourceStatus.READY
    read_calls_after = sum(1 for r in fake_llm.calls if r.purpose == "ingest.read_pages")
    assert read_calls_after == read_calls_before  # pages were reused, not re-read


def test_extraction_failure_rolls_back_partial_writes_before_marking_failed(env):
    deps, subject, source, fake_llm = env

    def boom(request):
        raise RuntimeError("language service down")

    fake_llm.set_responder(DetectedLanguage, boom)
    pipeline = IngestionPipeline(deps)
    with pytest.raises(RuntimeError):
        pipeline.ingest_source(source.id)

    failed = deps.sources.get(source.id)
    assert failed.status == SourceStatus.FAILED and failed.resume_status == SourceStatus.EXTRACTING
    assert deps.pages.list(source.id) == []

    fake_llm.set_responder(DetectedLanguage, default_responders()[DetectedLanguage])
    result = pipeline.ingest_source(source.id)
    assert result.status == SourceStatus.READY


def test_published_subject_is_locked(env):
    deps, subject, source, _ = env
    deps.subjects.set_state(subject.id, SubjectState.PUBLISHED)
    deps.conn.commit()
    with pytest.raises(SubjectLocked):
        IngestionPipeline(deps).ingest_source(source.id)
