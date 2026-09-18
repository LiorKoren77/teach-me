from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import ContentStatus, PartContent, SectionContent


class ContentRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_part(self, content: PartContent) -> None:
        self._conn.execute(
            "INSERT INTO part_content (part_id, language, title, body, key_points, status, model, error)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (part_id, language) DO UPDATE SET title = EXCLUDED.title, body = EXCLUDED.body,"
            " key_points = EXCLUDED.key_points, status = EXCLUDED.status, model = EXCLUDED.model,"
            " error = EXCLUDED.error, updated_at = now()",
            (
                content.part_id,
                content.language,
                content.title,
                content.body,
                list(content.key_points),
                content.status.value,
                content.model,
                content.error,
            ),
        )

    def part(self, part_id: UUID, language: str) -> PartContent | None:
        row = self._conn.execute(
            "SELECT part_id, language, title, body, key_points, status, model, error FROM part_content"
            " WHERE part_id = %s AND language = %s",
            (part_id, language),
        ).fetchone()
        if row is None:
            return None
        return PartContent(
            part_id=row["part_id"],
            language=row["language"],
            title=row["title"],
            body=row["body"],
            key_points=tuple(row["key_points"]),
            status=ContentStatus(row["status"]),
            model=row["model"],
            error=row["error"],
        )

    def upsert_sections(self, contents: Sequence[SectionContent]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO section_content (section_id, language, title, summary) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (section_id, language) DO UPDATE SET title = EXCLUDED.title,"
                " summary = EXCLUDED.summary",
                [(c.section_id, c.language, c.title, c.summary) for c in contents],
            )

    def sections(self, part_id: UUID, language: str) -> list[SectionContent]:
        rows = self._conn.execute(
            "SELECT sc.section_id, sc.language, sc.title, sc.summary FROM section_content sc"
            " JOIN sections s ON s.id = sc.section_id WHERE s.part_id = %s AND sc.language = %s"
            " ORDER BY s.position",
            (part_id, language),
        ).fetchall()
        return [
            SectionContent(
                section_id=r["section_id"], language=r["language"], title=r["title"], summary=r["summary"]
            )
            for r in rows
        ]

    def languages_ready(self, outline_id: UUID) -> dict[str, int]:
        """language -> number of parts with READY content, only for languages where every part is ready."""
        rows = self._conn.execute(
            "SELECT pc.language, count(*) AS ready FROM part_content pc JOIN parts p ON p.id = pc.part_id"
            " WHERE p.outline_id = %s AND pc.status = 'ready' GROUP BY pc.language",
            (outline_id,),
        ).fetchall()
        total = self._conn.execute(
            "SELECT count(*) AS n FROM parts WHERE outline_id = %s", (outline_id,)
        ).fetchone()["n"]
        return {r["language"]: int(r["ready"]) for r in rows if int(r["ready"]) == int(total) and total > 0}
