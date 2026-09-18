from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import GlossaryTerm, GlossaryTranslation


class GlossaryRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_terms(self, outline_id: UUID, terms: Sequence[GlossaryTerm]) -> None:
        self._conn.execute("DELETE FROM glossary_terms WHERE outline_id = %s", (outline_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO glossary_terms (id, outline_id, slug, source_term, definition, pages)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [(t.id, outline_id, t.slug, t.source_term, t.definition, list(t.pages)) for t in terms],
            )

    def terms(self, outline_id: UUID) -> list[GlossaryTerm]:
        rows = self._conn.execute(
            "SELECT id, outline_id, slug, source_term, definition, pages FROM glossary_terms"
            " WHERE outline_id = %s ORDER BY slug",
            (outline_id,),
        ).fetchall()
        return [
            GlossaryTerm(
                id=r["id"],
                outline_id=r["outline_id"],
                slug=r["slug"],
                source_term=r["source_term"],
                definition=r["definition"],
                pages=tuple(r["pages"]),
            )
            for r in rows
        ]

    def replace_translations(
        self, outline_id: UUID, language: str, translations: Sequence[GlossaryTranslation]
    ) -> None:
        self._conn.execute(
            "DELETE FROM glossary_translations WHERE language = %s AND term_id IN"
            " (SELECT id FROM glossary_terms WHERE outline_id = %s)",
            (language, outline_id),
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO glossary_translations (term_id, language, term) VALUES (%s, %s, %s)",
                [(t.term_id, language, t.term) for t in translations],
            )

    def translations(self, outline_id: UUID, language: str) -> list[GlossaryTranslation]:
        rows = self._conn.execute(
            "SELECT tr.term_id, tr.language, tr.term FROM glossary_translations tr"
            " JOIN glossary_terms t ON t.id = tr.term_id WHERE t.outline_id = %s AND tr.language = %s"
            " ORDER BY t.slug",
            (outline_id, language),
        ).fetchall()
        return [
            GlossaryTranslation(term_id=r["term_id"], language=r["language"], term=r["term"]) for r in rows
        ]
