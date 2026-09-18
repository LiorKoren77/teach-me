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
        self.append(source_id, pages)

    def append(self, source_id: UUID, pages: Sequence[Page]) -> None:
        """Add one read batch's pages to the ones this source already has. What resumable
        extraction writes: the batches before this one are committed and must survive."""
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO source_pages (source_id, page_index, printed_number, text)"
                " VALUES (%s, %s, %s, %s)",
                [(source_id, p.page_index, p.printed_number, p.text) for p in pages],
            )

    def first_missing_index(self, source_id: UUID) -> int:
        """Where extraction has to carry on from: the lowest page index this source has no row
        for. Computed as the length of the run starting at 0 rather than as a count, so a gap -
        however it got there - is read again instead of silently skipped."""
        rows = self._conn.execute(
            "SELECT page_index FROM source_pages WHERE source_id = %s ORDER BY page_index",
            (source_id,),
        ).fetchall()
        expected = 0
        for row in rows:
            if row["page_index"] != expected:
                break
            expected += 1
        return expected

    def printed_numbers(self, source_ids: Sequence[UUID]) -> dict[UUID, list[str]]:
        """Each source's printed page numbers in page order, "" for a page that carries none.
        One query for all of them: a caller labelling a subject's pages wants every source at
        once, and the page text - the bulk of a page row - is of no interest to it."""
        if not source_ids:
            return {}
        rows = self._conn.execute(
            "SELECT source_id, printed_number FROM source_pages"
            " WHERE source_id = ANY(%s) ORDER BY source_id, page_index",
            (list(source_ids),),
        ).fetchall()
        numbers: dict[UUID, list[str]] = {source_id: [] for source_id in source_ids}
        for row in rows:
            numbers[row["source_id"]].append(row["printed_number"] or "")
        return numbers

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
