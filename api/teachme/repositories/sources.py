from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Source, SourceStatus
from teachme.repositories.errors import SourceNotFound

_COLUMNS = (
    "id, subject_id, filename, media_type, file_key, size, status, resume_status, error, "
    "page_count, vision_pages, detected_language"
)


def _row_to_source(row: dict) -> Source:
    return Source(
        id=row["id"],
        subject_id=row["subject_id"],
        filename=row["filename"],
        media_type=row["media_type"],
        file_key=row["file_key"],
        size=row["size"],
        status=SourceStatus(row["status"]),
        resume_status=SourceStatus(row["resume_status"]) if row["resume_status"] is not None else None,
        error=row["error"],
        page_count=row["page_count"],
        vision_pages=row["vision_pages"],
        detected_language=row["detected_language"],
    )


class SourceRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, subject_id: UUID, filename: str, media_type: str, file_key: str, size: int) -> Source:
        source_id = uuid4()
        self._conn.execute(
            "INSERT INTO sources (id, subject_id, filename, media_type, file_key, size, status)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (source_id, subject_id, filename, media_type, file_key, size, SourceStatus.UPLOADED.value),
        )
        return self.get(source_id)

    def get(self, source_id: UUID) -> Source:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM sources WHERE id = %s", (source_id,)).fetchone()
        if row is None:
            raise SourceNotFound(source_id)
        return _row_to_source(row)

    def list_by_subject(self, subject_id: UUID) -> list[Source]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM sources WHERE subject_id = %s ORDER BY created_at, filename",
            (subject_id,),
        ).fetchall()
        return [_row_to_source(row) for row in rows]

    def set_status(
        self,
        source_id: UUID,
        status: SourceStatus,
        *,
        error: str | None = None,
        resume_status: SourceStatus | None = None,
    ) -> None:
        """A non-failed status clears error and resume_status; FAILED records both."""
        if status is not SourceStatus.FAILED:
            error = None
            resume_status = None
        self._conn.execute(
            "UPDATE sources SET status = %s, error = %s, resume_status = %s, updated_at = now()"
            " WHERE id = %s",
            (status.value, error, resume_status.value if resume_status is not None else None, source_id),
        )

    def set_extraction_result(
        self, source_id: UUID, *, page_count: int, vision_pages: int, detected_language: str | None
    ) -> None:
        self._conn.execute(
            "UPDATE sources SET page_count = %s, vision_pages = %s, detected_language = %s,"
            " updated_at = now() WHERE id = %s",
            (page_count, vision_pages, detected_language, source_id),
        )

    def delete(self, source_id: UUID) -> None:
        self._conn.execute("DELETE FROM sources WHERE id = %s", (source_id,))
