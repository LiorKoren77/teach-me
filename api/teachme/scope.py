from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg

from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.adapters.job_runner.inprocess import InProcessJobRunner
from teachme.ingestion.pipeline import IngestionPipeline, PipelineDeps
from teachme.ports.job_runner import JobPayload, JobRunner
from teachme.repositories.attempts import AttemptRepository
from teachme.repositories.content import ContentRepository
from teachme.repositories.figures import FigureRepository
from teachme.repositories.glossary import GlossaryRepository
from teachme.repositories.jobs import JobRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.progress import ProgressRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository
from teachme.retrieval.hybrid import HybridSearch
from teachme.services.export_import import ExportImportService
from teachme.services.generation_jobs import (
    GENERATE_SUBJECT,
    GENERATE_UNIT,
    run_generate_subject,
    run_generate_unit,
)
from teachme.services.learning import LearningDeps, LearningService
from teachme.services.progress import ProgressService
from teachme.services.sources import SourceService
from teachme.services.subjects import SubjectService
from teachme.services.thumbnails import ThumbnailService
from teachme.services.tutorial import TutorialService
from teachme.services.usage import UsageService

if TYPE_CHECKING:
    from teachme.container import Container


class Scope:
    """Everything that needs a database connection, built for one connection. The container keeps
    a default scope for the CLI; every HTTP request gets its own from the pool."""

    def __init__(self, shared: Container, conn: psycopg.Connection) -> None:
        self.shared = shared
        self.conn = conn

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
    def outlines(self) -> OutlineRepository:
        return OutlineRepository(self.conn)

    @cached_property
    def glossary(self) -> GlossaryRepository:
        return GlossaryRepository(self.conn)

    @cached_property
    def content(self) -> ContentRepository:
        return ContentRepository(self.conn)

    @cached_property
    def questions(self) -> QuestionRepository:
        return QuestionRepository(self.conn)

    @cached_property
    def progress(self) -> ProgressRepository:
        return ProgressRepository(self.conn)

    @cached_property
    def attempts(self) -> AttemptRepository:
        return AttemptRepository(self.conn)

    @cached_property
    def usage_reads(self) -> UsageRepository:
        """Reads only: telemetry writes through the container's own autocommit connection, so a
        usage row never depends on the transaction of the request that paid for it."""
        return UsageRepository(self.conn)

    # search, pipeline, jobs -----------------------------------------------------------------
    @cached_property
    def search(self) -> PgVectorChunkSearch:
        return PgVectorChunkSearch(self.conn)

    @cached_property
    def hybrid_search(self) -> HybridSearch:
        return HybridSearch(self.shared.embedder, self.search, self.shared.reranker)

    @cached_property
    def pipeline_deps(self) -> PipelineDeps:
        s = self.shared
        return PipelineDeps(
            conn=self.conn,
            settings=s.settings,
            llm=s.llm,
            embedder=s.embedder,
            search=self.search,
            files=s.files,
            bundle_stores=s.bundle_stores,
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

    def _generate_subject_job(self, payload: JobPayload) -> None:
        run_generate_subject(
            payload, service=self.tutorial_service, subjects=self.subjects, runner=self.job_runner
        )

    def _generate_unit_job(self, payload: JobPayload) -> None:
        run_generate_unit(payload, service=self.tutorial_service)

    @cached_property
    def job_runner(self) -> JobRunner:
        settings = self.shared.settings
        if settings.job_runner == "sqs":
            from teachme.container import ConfigurationError

            if not settings.sqs_queue_url:
                raise ConfigurationError("JOB_RUNNER=sqs requires SQS_QUEUE_URL")
            from teachme.adapters.job_runner.sqs import SqsJobRunner

            return SqsJobRunner(
                settings.sqs_queue_url,
                settings.aws_region,
                jobs=self.jobs,
                commit=self.conn.commit,
            )
        return InProcessJobRunner(
            {
                "ingest_source": self._ingest_job,
                GENERATE_SUBJECT: self._generate_subject_job,
                GENERATE_UNIT: self._generate_unit_job,
            },
            jobs=self.jobs,
            commit=self.conn.commit,
            rollback=self.conn.rollback,
        )

    # services -------------------------------------------------------------------------------
    @cached_property
    def subject_service(self) -> SubjectService:
        return SubjectService(self.conn, self.subjects, self.shared.settings)

    @cached_property
    def source_service(self) -> SourceService:
        s = self.shared
        return SourceService(self.conn, s.settings, s.llm, s.files, self.search, self.sources, self.subjects)

    @cached_property
    def usage_service(self) -> UsageService:
        return UsageService(self.usage_reads)

    @cached_property
    def export_import(self) -> ExportImportService:
        return ExportImportService(self.pipeline_deps)

    @cached_property
    def progress_service(self) -> ProgressService:
        return ProgressService(self.conn, self.outlines, self.progress)

    @cached_property
    def tutorial_service(self) -> TutorialService:
        s = self.shared
        service = TutorialService(
            self.conn,
            s.settings,
            s.llm,
            self.subjects,
            self.sources,
            self.pages,
            self.outlines,
            self.glossary,
            self.content,
            self.questions,
            s.bundle_stores,
        )
        # A new published version means new part ids: a student's progress against the old ones
        # is meaningless, so it is dropped the moment the version changes.
        service.on_version_published(
            lambda subject, version: self.progress_service.reset_for_new_version(subject, version)
        )
        return service

    @cached_property
    def thumbnail_service(self) -> ThumbnailService:
        return ThumbnailService(self.shared.files, self.sources, width=self.shared.settings.thumbnail_width)

    @cached_property
    def learning_service(self) -> LearningService:
        s = self.shared
        return LearningService(
            LearningDeps(
                conn=self.conn,
                settings=s.settings,
                llm=s.llm,
                hybrid=self.hybrid_search,
                subjects=self.subjects,
                outlines=self.outlines,
                glossary=self.glossary,
                content=self.content,
                questions=self.questions,
                progress=self.progress,
                attempts=self.attempts,
                tutorial=self.tutorial_service,
                progress_service=self.progress_service,
                corpus_cache=s.corpus_cache,
            )
        )

    @contextmanager
    def active(self) -> Iterator[Scope]:
        """Roll back if the body raises; commits are explicit, inside the services."""
        try:
            yield self
        except BaseException:
            self.conn.rollback()
            raise
