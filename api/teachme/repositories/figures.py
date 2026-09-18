from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Figure


class FigureRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace(self, source_id: UUID, figures: Sequence[Figure]) -> None:
        self._conn.execute("DELETE FROM source_figures WHERE source_id = %s", (source_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO source_figures (source_id, page_index, ordinal, kind, caption, description)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [(source_id, f.page_index, f.ordinal, f.kind, f.caption, f.description) for f in figures],
            )

    def list(self, source_id: UUID) -> list[Figure]:
        rows = self._conn.execute(
            "SELECT page_index, ordinal, kind, caption, description FROM source_figures"
            " WHERE source_id = %s ORDER BY page_index, ordinal",
            (source_id,),
        ).fetchall()
        return [
            Figure(
                page_index=row["page_index"],
                ordinal=row["ordinal"],
                kind=row["kind"],
                caption=row["caption"],
                description=row["description"],
            )
            for row in rows
        ]
