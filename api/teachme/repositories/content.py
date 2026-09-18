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
            "INSERT INTO part_content"
            " (part_id, language, title, body, key_points, status, model, error, page_refs)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (part_id, language) DO UPDATE SET title = EXCLUDED.title, body = EXCLUDED.body,"
            " key_points = EXCLUDED.key_points, status = EXCLUDED.status, model = EXCLUDED.model,"
            " error = EXCLUDED.error, page_refs = EXCLUDED.page_refs, updated_at = now()",
            (
                content.part_id,
                content.language,
                content.title,
                content.body,
                list(content.key_points),
                content.status.value,
                content.model,
                content.error,
                list(content.page_refs),
            ),
        )

    def part(self, part_id: UUID, language: str) -> PartContent | None:
        row = self._conn.execute(
            "SELECT part_id, language, title, body, key_points, status, model, error, page_refs"
            " FROM part_content WHERE part_id = %s AND language = %s",
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
            page_refs=tuple(row["page_refs"]),
        )

    def upsert_sections(self, contents: Sequence[SectionContent]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO section_content (section_id, language, title, summary) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (section_id, language) DO UPDATE SET title = EXCLUDED.title,"
                " summary = EXCLUDED.summary",
                [(c.section_id, c.language, c.title, c.summary) for c in contents],
            )

    def delete_sections(self, part_id: UUID, language: str) -> None:
        """Used to discard a failed regeneration's leftovers: the previous attempt's section
        content for this part and language must not survive next to a FAILED part."""
        self._conn.execute(
            "DELETE FROM section_content WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s)",
            (language, part_id),
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
        """language -> number of parts with READY content. Languages with none are left out.

        Completeness is the caller's business: comparing this against the outline's part count is
        what `TutorialService.status` does, and it needs the true count to report progress."""
        rows = self._conn.execute(
            "SELECT pc.language, count(*) AS ready FROM part_content pc JOIN parts p ON p.id = pc.part_id"
            " WHERE p.outline_id = %s AND pc.status = 'ready' GROUP BY pc.language",
            (outline_id,),
        ).fetchall()
        return {r["language"]: int(r["ready"]) for r in rows}

    def languages_failed(self, outline_id: UUID) -> dict[str, tuple[int, ...]]:
        """language -> positions of the parts whose content is FAILED, ascending."""
        rows = self._conn.execute(
            "SELECT pc.language, p.position FROM part_content pc JOIN parts p ON p.id = pc.part_id"
            " WHERE p.outline_id = %s AND pc.status = 'failed' ORDER BY pc.language, p.position",
            (outline_id,),
        ).fetchall()
        failed: dict[str, list[int]] = {}
        for row in rows:
            failed.setdefault(row["language"], []).append(int(row["position"]))
        return {language: tuple(positions) for language, positions in failed.items()}
