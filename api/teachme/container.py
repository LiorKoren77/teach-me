from __future__ import annotations

from functools import cached_property
from uuid import UUID

import psycopg

from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import ensure_schema_current
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.adapters.job_runner.inprocess import InProcessJobRunner
from teachme.adapters.llm.fake import FakeLLM
from teachme.adapters.reranker.noop import NoopReranker
from teachme.generation.fake_responders import default_responders as generation_responders
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
from teachme.ingestion.pipeline import IngestionPipeline, PipelineDeps
from teachme.ports.embeddings import Embedder
from teachme.ports.file_store import FileStore
from teachme.ports.job_runner import JobPayload, JobRunner
from teachme.ports.llm import LLMProvider
from teachme.ports.reranker import Reranker
from teachme.repositories.figures import FigureRepository
from teachme.repositories.jobs import JobRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository
from teachme.retrieval.hybrid import HybridSearch
from teachme.services.export_import import ExportImportService
from teachme.services.sources import SourceService
from teachme.services.subjects import SubjectService
from teachme.services.usage import UsageService
from teachme.settings import Settings
from teachme.telemetry.prices import PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder


class ConfigurationError(Exception):
    pass


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None else None


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from teachme.adapters.llm.anthropic import AnthropicLLM

        return AnthropicLLM(api_key=_secret(settings.anthropic_api_key))
    return FakeLLM({**ingestion_responders(), **generation_responders()})


def build_embedder(settings: Settings) -> Embedder:
    if settings.embeddings_provider == "voyage":
        from teachme.adapters.embeddings.voyage import VoyageEmbedder

        return VoyageEmbedder(model=settings.embedding_model, api_key=_secret(settings.voyage_api_key))
    return FakeEmbedder()


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker_provider == "voyage":
        from teachme.adapters.reranker.voyage import VoyageReranker

        return VoyageReranker(model=settings.rerank_model, api_key=_secret(settings.voyage_api_key))
    return NoopReranker()


def build_file_store(settings: Settings) -> FileStore:
    if settings.file_store == "local":
        return LocalFileStore(settings.local_files_dir)
    if settings.file_store == "vercel_blob":
        from teachme.adapters.file_store.vercel_blob import VercelBlobFileStore

        return VercelBlobFileStore(prefix=settings.blob_prefix, token=_secret(settings.blob_read_write_token))
    if not settings.s3_bucket:
        raise ConfigurationError("FILE_STORE=s3 requires S3_BUCKET")
    from teachme.adapters.file_store.s3 import S3FileStore

    return S3FileStore(bucket=settings.s3_bucket, region=settings.aws_region)


class Container:
    """Builds every adapter, repository and service once from Settings. The only place that
    knows which concrete class stands behind each port."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # infrastructure -------------------------------------------------------------------------
    @cached_property
    def conn(self) -> psycopg.Connection:
        return connect(self.settings.database_url)

    @cached_property
    def usage_conn(self) -> psycopg.Connection:
        """Telemetry writes here, on its own autocommit connection: a usage row records money
        already spent, so it must not be rolled back with the pipeline step that failed."""
        return connect(self.settings.database_url, autocommit=True)

    @cached_property
    def prices(self) -> PriceTable:
        return PriceTable()

    @cached_property
    def usage_recorder(self) -> UsageRecorder:
        return UsageRecorder(self.usage_repo, self.prices)

    @cached_property
    def llm(self) -> LLMProvider:
        return RecordingLLM(build_llm(self.settings), self.usage_recorder)

    @cached_property
    def embedder(self) -> Embedder:
        return RecordingEmbedder(build_embedder(self.settings), self.usage_recorder)

    @cached_property
    def reranker(self) -> Reranker:
        return build_reranker(self.settings)

    @cached_property
    def files(self) -> FileStore:
        return build_file_store(self.settings)

    @cached_property
    def bundle_stores(self) -> list[FileStore]:
        stores: list[FileStore] = [PrefixedFileStore(self.files, "digest/")]
        if self.settings.write_local_bundle:
            stores.append(LocalFileStore(self.settings.digest_dir))
        return stores

    @cached_property
    def search(self) -> PgVectorChunkSearch:
        return PgVectorChunkSearch(self.conn)

    # repositories ---------------------------------------------------------------------------
    @cached_property
    def subjects(self) -> SubjectRepository:
        return SubjectRepository(self.conn)

    @cached_property
    def sources(self) -> SourceRepository:
        return SourceRepository(self.conn)

    @cached_property
    def pages(self) -> PageRepository:
        return PageRepository(self.conn)

    @cached_property
    def figures(self) -> FigureRepository:
        return FigureRepository(self.conn)

    @cached_property
    def jobs(self) -> JobRepository:
        return JobRepository(self.conn)

    @cached_property
    def usage_repo(self) -> UsageRepository:
        return UsageRepository(self.usage_conn)

    # pipeline, jobs, services ---------------------------------------------------------------
    @cached_property
    def pipeline_deps(self) -> PipelineDeps:
        return PipelineDeps(
            conn=self.conn,
            settings=self.settings,
            llm=self.llm,
            embedder=self.embedder,
            search=self.search,
            files=self.files,
            bundle_stores=self.bundle_stores,
            subjects=self.subjects,
            sources=self.sources,
            pages=self.pages,
            figures=self.figures,
        )

    @cached_property
    def pipeline(self) -> IngestionPipeline:
        return IngestionPipeline(self.pipeline_deps)

    def _ingest_job(self, payload: JobPayload) -> None:
        self.pipeline.ingest_source(UUID(payload["source_id"]))

    @cached_property
    def job_runner(self) -> JobRunner:
        if self.settings.job_runner == "sqs":
            if not self.settings.sqs_queue_url:
                raise ConfigurationError("JOB_RUNNER=sqs requires SQS_QUEUE_URL")
            from teachme.adapters.job_runner.sqs import SqsJobRunner

            return SqsJobRunner(
                self.settings.sqs_queue_url,
                self.settings.aws_region,
                jobs=self.jobs,
                commit=self.conn.commit,
            )
        return InProcessJobRunner(
            {"ingest_source": self._ingest_job},
            jobs=self.jobs,
            commit=self.conn.commit,
            rollback=self.conn.rollback,
        )

    @cached_property
    def subject_service(self) -> SubjectService:
        return SubjectService(self.conn, self.subjects, self.settings)

    @cached_property
    def source_service(self) -> SourceService:
        return SourceService(
            self.conn, self.settings, self.llm, self.files, self.search, self.sources, self.subjects
        )

    @cached_property
    def usage_service(self) -> UsageService:
        return UsageService(self.usage_repo)

    @cached_property
    def export_import(self) -> ExportImportService:
        return ExportImportService(self.pipeline_deps)

    @cached_property
    def hybrid_search(self) -> HybridSearch:
        return HybridSearch(self.embedder, self.search, self.reranker)

    # lifecycle ------------------------------------------------------------------------------
    def check_ready(self) -> None:
        """Fail fast with a named reason instead of on the first request."""
        ensure_schema_current(self.conn)
        expected = self.search.dimension()
        if self.embedder.dimension != expected:
            raise ConfigurationError(
                f"embedder {self.embedder.model!r} has dimension {self.embedder.dimension}, "
                f"chunks table expects {expected}"
            )
        # Touch every adapter so a missing/invalid configuration surfaces here, at startup,
        # rather than on the first request that happens to need it.
        _ = (self.files, self.job_runner, self.llm, self.reranker)
        self.conn.rollback()

    def close(self) -> None:
        for name in ("conn", "usage_conn"):
            if name in self.__dict__:
                self.__dict__[name].close()
