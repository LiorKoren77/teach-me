from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Source, SourceStatus, Subject, SubjectState
from teachme.ingestion.errors import SubjectLocked, UnsupportedMediaType
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMProvider
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings

_EXTRA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".webp": "image/webp",
}
# A private table: mimetypes.guess_type() also reads the host's /etc/mime.types, which would
# make the accepted upload types differ between a developer machine and the server.
_MIME = mimetypes.MimeTypes()


class SourceService:
    """Registers, lists and removes sources. Accepted upload types are what the LLM adapter can
    read, optionally narrowed by ALLOWED_UPLOAD_TYPES, never widened."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        llm: LLMProvider,
        files: FileStore,
        search: ChunkSearch,
        sources: SourceRepository,
        subjects: SubjectRepository,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._llm = llm
        self._files = files
        self._search = search
        self._sources = sources
        self._subjects = subjects

    def accepted_media_types(self) -> frozenset[str]:
        accepted = self._llm.capabilities().media_types
        if self._settings.allowed_upload_types is not None:
            accepted = accepted & frozenset(self._settings.allowed_upload_types)
        return accepted

    @staticmethod
    def media_type_for(filename: str) -> str | None:
        lower = filename.lower()
        for suffix, media_type in _EXTRA_TYPES.items():
            if lower.endswith(suffix):
                return media_type
        guessed, encoding = _MIME.guess_type(lower)
        return None if encoding else guessed

    def register(self, subject: Subject, filename: str, data: bytes) -> Source:
        self._require_draft(subject)
        safe_name = PurePosixPath(filename.replace("\\", "/")).name
        if not safe_name:
            raise UnsupportedMediaType("empty filename")
        media_type = self.media_type_for(safe_name)
        accepted = sorted(self.accepted_media_types())
        if media_type is None or media_type not in accepted:
            raise UnsupportedMediaType(f"{filename!r} ({media_type}) is not accepted; accepted: {accepted}")
        key = f"sources/{subject.id}/{uuid4()}/{safe_name}"
        self._files.put(key, data, media_type)
        source = self._sources.create(subject.id, safe_name, media_type, key, len(data))
        self._conn.commit()
        return source

    def list(self, subject: Subject) -> list[Source]:
        return self._sources.list_by_subject(subject.id)

    def mark_for_reingest(self, source_id: UUID) -> Source:
        source = self._sources.get(source_id)
        self._require_draft(self._subjects.get(source.subject_id))
        self._sources.set_status(source.id, SourceStatus.UPLOADED)
        self._conn.commit()
        return self._sources.get(source.id)

    def delete(self, source_id: UUID) -> None:
        source = self._sources.get(source_id)
        self._require_draft(self._subjects.get(source.subject_id))
        self._search.delete_by_source(source.id)
        self._files.delete(source.file_key)
        self._sources.delete(source.id)  # pages and figures cascade
        self._conn.commit()

    @staticmethod
    def _require_draft(subject: Subject) -> None:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; sources are locked")
