from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Page


class PageRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace(self, source_id: UUID, pages: Sequence[Page]) -> None:
        self._conn.execute("DELETE FROM source_pages WHERE source_id = %s", (source_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO source_pages (source_id, page_index, printed_number, text)"
                " VALUES (%s, %s, %s, %s)",
                [(source_id, p.page_index, p.printed_number, p.text) for p in pages],
            )

    def list(self, source_id: UUID) -> list[Page]:
        rows = self._conn.execute(
            "SELECT page_index, printed_number, text FROM source_pages"
            " WHERE source_id = %s ORDER BY page_index",
            (source_id,),
        ).fetchall()
        return [
            Page(page_index=row["page_index"], printed_number=row["printed_number"], text=row["text"])
            for row in rows
        ]
