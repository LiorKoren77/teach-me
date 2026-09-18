from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from teachme.domain.models import Chunk, Source, SourceStatus, Subject, SubjectState
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug
from teachme.ingestion.contextualize import contextualize
from teachme.ingestion.detect_language import detect_language
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.extract import extract_batch
from teachme.ingestion.index import index_chunks
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMProvider
from teachme.repositories.figures import FigureRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings
from teachme.telemetry.usage import usage_context

log = logging.getLogger(__name__)

# The job kind a queued ingestion travels under.
INGEST_SOURCE = "ingest_source"

# What a finished step hands the source on to. Each step sets its own status when it starts, and
# nothing else; the transition out of it belongs to whoever drives the sequence, so no step has to
# know - or claim - the name of the one that follows it. Extraction stays in EXTRACTING until
# every page is read, because one step is one read batch rather than the whole phase.
NEXT_STEP = {
    SourceStatus.EXTRACTING: SourceStatus.CHUNKING,
    SourceStatus.CHUNKING: SourceStatus.INDEXING,
}


@dataclass
class PipelineDeps:
    conn: psycopg.Connection
    settings: Settings
    llm: LLMProvider
    embedder: Embedder
    search: ChunkSearch
    files: FileStore
    bundle_stores: Sequence[FileStore]  # first one is the primary store; resume reads from it
    subjects: SubjectRepository
    sources: SourceRepository
    pages: PageRepository
    figures: FigureRepository


class IngestionPipeline:
    """uploaded -> extracting -> chunking -> indexing -> ready, resumable from the recorded status.

    Each step commits when its outputs are persisted. On failure the source is marked FAILED with
    resume_status = the step that failed, and re-running continues from there. Extraction resumes
    finer than that - from the first page it has no row for, so the read batches that landed are
    never paid for twice - and chunks are recovered from the bundle when resuming from INDEXING,
    so no model call is repeated."""

    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps

    def ingest_source(self, source_id: UUID) -> Source:
        """The whole run, one step at a time, in this process. What the CLI calls."""
        while self.run_next_step(source_id):
            pass
        return self.d.sources.get(source_id)

    def run_next_step(self, source_id: UUID) -> bool:
        """Exactly one step - one read batch, chunking or indexing - starting from the source's
        own resume point and committed before returning. True means a step is still outstanding,
        so a runner that gets one function invocation per step re-enqueues itself; False means
        the source reached READY.

        Extraction is the step that has to be split: reading a 400-page book is one model call
        per PAGES_PER_READ_BATCH pages, and doing them all in one invocation is what a duration
        limit kills. So a step reads one batch, persists it and leaves the source in EXTRACTING;
        the next call reads the batch after it.

        Failure is handled as it is for a whole run: the transaction is rolled back and the source
        marked FAILED with the step that failed as its resume_status, so the next call picks up
        exactly there. Chunks are not handed from the chunking step to the indexing one in memory,
        because the two may run in different processes - the indexing step reads them back from the
        bundle the chunking step wrote."""
        source = self.d.sources.get(source_id)
        subject = self.d.subjects.get(source.subject_id)
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before ingesting")

        bundle = BundleWriter(self.d.bundle_stores, bundle_slug(subject.name, subject.id))
        source_slug = bundle_slug(source.filename, source.id)
        step = self._resume_point(source)
        extracted_everything = True
        with usage_context(subject_id=subject.id, source_id=source.id):
            try:
                if step in (SourceStatus.UPLOADED, SourceStatus.EXTRACTING):
                    # UPLOADED means read the file from its first page: an explicit re-ingest
                    # must not resume against the pages of the run before it.
                    restart = step == SourceStatus.UPLOADED
                    step = SourceStatus.EXTRACTING
                    extracted_everything = self._extract(source, bundle, source_slug, restart=restart)
                elif step == SourceStatus.CHUNKING:
                    self._chunk(source, subject, bundle, source_slug)
                else:
                    step = SourceStatus.INDEXING
                    self._index(source, subject, bundle, source_slug)
            except Exception as exc:
                log.exception("ingestion of %s failed during %s", source.id, step.value)
                self.d.conn.rollback()
                self.d.sources.set_status(
                    source.id, SourceStatus.FAILED, error=f"{type(exc).__name__}: {exc}", resume_status=step
                )
                self.d.conn.commit()
                raise
        if step == SourceStatus.INDEXING:
            return False  # _index recorded READY itself; there is no next step to hand over to
        if not extracted_everything:
            return True  # more batches to read; the source stays where _extract left it
        self.d.sources.set_status(source.id, NEXT_STEP[step])
        self.d.conn.commit()
        return True

    @staticmethod
    def _resume_point(source: Source) -> SourceStatus:
        if source.status == SourceStatus.FAILED:
            return source.resume_status or SourceStatus.UPLOADED
        if source.status == SourceStatus.READY:
            return SourceStatus.UPLOADED  # explicit re-ingest starts over
        return source.status

    def _extract(self, source: Source, bundle: BundleWriter, source_slug: str, *, restart: bool) -> bool:
        """One read batch, persisted and committed. Returns whether the source now has every
        page, which is what tells the caller extraction is over.

        The batch read is the one starting at the first page with no row, so a step that never
        came back costs at most the batch it was reading. The bundle's page files mirror those
        rows, and the language and meta.json - which describe the whole source - are written
        once, when the last batch has landed."""
        self.d.sources.set_status(source.id, SourceStatus.EXTRACTING)
        if restart:
            # A re-ingest reads the file again from page 0, so the previous run's pages must not
            # be resumed from - and its chunks no longer match anything. Dropping them here
            # rather than when the new ones are indexed keeps nothing stale searchable, even if
            # this run fails.
            self.d.pages.replace(source.id, [])
            self.d.figures.replace(source.id, [])
            self.d.search.delete_by_source(source.id)
        self.d.conn.commit()

        first_index = self.d.pages.first_missing_index(source.id)
        data = self.d.files.get(source.file_key)
        batch = extract_batch(
            self.d.llm,
            self.d.settings,
            data,
            source.media_type,
            language_hint=None,
            first_index=first_index,
        )
        if batch.pages:
            self.d.pages.append(source.id, batch.pages)
            self.d.figures.append(source.id, batch.figures)
            bundle.write_pages(source_slug, batch.pages)
            bundle.write_figures(source_slug, self.d.figures.list(source.id))
            # Asked before the commit, so this step leaves no transaction of its own open: the
            # next batch may well be read by a different invocation on a different connection.
            complete = self.d.pages.first_missing_index(source.id) >= batch.total_pages
            self.d.conn.commit()
            if not complete:
                return False
        self._finish_extraction(source, bundle, source_slug, batch.vision_pages)
        return True

    def _finish_extraction(
        self, source: Source, bundle: BundleWriter, source_slug: str, vision_pages: int
    ) -> None:
        """What is true of the source rather than of a batch: its language, its page count and
        the meta.json a re-import reads. Committed on its own, after the last batch is already
        durable, so a language call that fails costs the language call and nothing else."""
        pages = self.d.pages.list(source.id)
        language = detect_language(self.d.llm, self.d.settings.model_detect_language, pages)
        self.d.sources.set_extraction_result(
            source.id, page_count=len(pages), vision_pages=vision_pages, detected_language=language
        )
        bundle.write_meta(source_slug, self._meta(source, len(pages), vision_pages, language))
        self.d.conn.commit()

    def _chunk(self, source: Source, subject: Subject, bundle: BundleWriter, source_slug: str) -> list[Chunk]:
        self.d.sources.set_status(source.id, SourceStatus.CHUNKING)
        self.d.conn.commit()
        current = self.d.sources.get(source.id)
        pages = self.d.pages.list(source.id)
        chunks = contextualize(
            self.d.llm,
            self.d.settings.model_contextualize,
            subject.name,
            source.filename,
            current.detected_language,
            pages,
            self.d.settings.pages_per_chunk_batch,
        )
        bundle.write_chunks(source_slug, chunks)
        self.d.conn.commit()
        return chunks

    def _index(self, source: Source, subject: Subject, bundle: BundleWriter, source_slug: str) -> None:
        self.d.sources.set_status(source.id, SourceStatus.INDEXING)
        self.d.conn.commit()
        current = self.d.sources.get(source.id)
        reader = BundleReader(self.d.bundle_stores[0], bundle.prefix(source_slug))
        chunks = reader.chunks() if reader.has_chunks() else self._chunk(source, subject, bundle, source_slug)
        records = index_chunks(
            self.d.embedder,
            self.d.search,
            source.id,
            subject.id,
            chunks,
            language_code=current.detected_language,
        )
        bundle.write_embeddings(source_slug, records)
        bundle.write_meta(
            source_slug,
            self._meta(
                current, current.page_count or 0, current.vision_pages or 0, current.detected_language
            ),
        )
        self.d.sources.set_status(source.id, SourceStatus.READY)
        self.d.conn.commit()

    def _meta(self, source: Source, page_count: int, vision_pages: int, language: str | None) -> SourceMeta:
        s = self.d.settings
        return SourceMeta(
            source_id=source.id,
            filename=source.filename,
            media_type=source.media_type,
            size=source.size,
            page_count=page_count,
            vision_pages=vision_pages,
            language=language,
            models={
                "read_pages": s.model_read_pages,
                "detect_language": s.model_detect_language,
                "contextualize": s.model_contextualize,
            },
            embedding_model=self.d.embedder.model,
        )
