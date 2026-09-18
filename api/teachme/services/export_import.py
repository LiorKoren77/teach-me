from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from teachme.adapters.file_store.local import LocalFileStore
from teachme.domain.models import ChunkRecord, Source, SourceStatus, Subject, SubjectState
from teachme.domain.text.normalize import tokenize
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.index import index_chunks
from teachme.ingestion.pipeline import PipelineDeps


class ExportImportService:
    """The bundle is the portable artifact; the database is a derived index.
    export: database -> local folder. import: local folder -> database (+ primary bundle store)."""

    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps

    def export_source(self, source_id: UUID, out_root: Path) -> Path:
        source = self.d.sources.get(source_id)
        subject = self.d.subjects.get(source.subject_id)
        subject_slug = bundle_slug(subject.name, subject.id)
        source_slug = bundle_slug(source.filename, source.id)
        writer = BundleWriter([LocalFileStore(out_root)], subject_slug)

        records = self.d.search.list_by_source(source.id)
        embedding_model = records[0].embedding_model if records else None
        writer.write_meta(source_slug, self._meta(source, embedding_model))
        writer.write_pages(source_slug, self.d.pages.list(source.id))
        writer.write_figures(source_slug, self.d.figures.list(source.id))
        writer.write_chunks(source_slug, [r.chunk for r in records])
        if records:
            writer.write_embeddings(source_slug, records)
        return out_root / subject_slug / source_slug

    def import_source(self, subject: Subject, bundle_dir: Path) -> Source:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before importing")
        reader = BundleReader(LocalFileStore(bundle_dir), "")
        meta = reader.meta()
        pages, figures, chunks = reader.pages(), reader.figures(), reader.chunks()

        file_key = f"imported/{meta.source_id}/{meta.filename}"
        source = self.d.sources.create(subject.id, meta.filename, meta.media_type, file_key, meta.size)
        self.d.sources.set_status(source.id, SourceStatus.INDEXING)
        self.d.pages.replace(source.id, pages)
        self.d.figures.replace(source.id, figures)
        self.d.sources.set_extraction_result(
            source.id,
            page_count=meta.page_count,
            vision_pages=meta.vision_pages,
            detected_language=meta.language,
        )

        embeddings = reader.embeddings()
        reuse = (
            embeddings is not None
            and meta.embedding_model == self.d.embedder.model
            and len(embeddings) == len(chunks)
        )
        if reuse:
            records = [
                ChunkRecord(
                    id=uuid4(),
                    source_id=source.id,
                    subject_id=subject.id,
                    chunk=chunk,
                    embedding=row.vector,
                    embedding_model=row.model,
                    tokens=tuple(tokenize(chunk.content, meta.language or "")),
                )
                for chunk, row in zip(chunks, embeddings, strict=True)
            ]
            self.d.search.delete_by_source(source.id)
            self.d.search.upsert(records)
        else:
            records = index_chunks(
                self.d.embedder, self.d.search, source.id, subject.id, chunks, language_code=meta.language
            )

        # Mirror the bundle into the primary store so the hosted copy is complete too.
        writer = BundleWriter(self.d.bundle_stores, bundle_slug(subject.name, subject.id))
        source_slug = bundle_slug(source.filename, source.id)
        writer.write_meta(
            source_slug,
            self._meta(self.d.sources.get(source.id), records[0].embedding_model if records else None),
        )
        writer.write_pages(source_slug, pages)
        writer.write_figures(source_slug, figures)
        writer.write_chunks(source_slug, chunks)
        if records:
            writer.write_embeddings(source_slug, records)

        self.d.sources.set_status(source.id, SourceStatus.READY)
        self.d.conn.commit()
        return self.d.sources.get(source.id)

    def _meta(self, source: Source, embedding_model: str | None) -> SourceMeta:
        s = self.d.settings
        return SourceMeta(
            source_id=source.id,
            filename=source.filename,
            media_type=source.media_type,
            size=source.size,
            page_count=source.page_count or 0,
            vision_pages=source.vision_pages or 0,
            language=source.detected_language,
            models={
                "read_pages": s.model_read_pages,
                "detect_language": s.model_detect_language,
                "contextualize": s.model_contextualize,
            },
            embedding_model=embedding_model,
        )
