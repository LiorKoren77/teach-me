from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Question, QuestionKind

_COLUMNS = (
    "id, section_id, language, kind, prompt, expected_answer, rubric, key_terms, exact_values, choices,"
    " correct_choice, position"
)


def _question(row: dict) -> Question:
    return Question(
        id=row["id"],
        section_id=row["section_id"],
        language=row["language"],
        kind=QuestionKind(row["kind"]),
        prompt=row["prompt"],
        expected_answer=row["expected_answer"],
        rubric=tuple(row["rubric"]),
        key_terms=tuple(row["key_terms"]),
        exact_values=tuple(row["exact_values"]),
        choices=tuple(row["choices"]) if row["choices"] is not None else None,
        correct_choice=row["correct_choice"],
        position=row["position"],
    )


class QuestionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_for_part(self, part_id: UUID, language: str, questions: Sequence[Question]) -> None:
        self._conn.execute(
            "DELETE FROM questions WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s)",
            (language, part_id),
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO questions ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        q.id,
                        q.section_id,
                        q.language,
                        q.kind.value,
                        q.prompt,
                        q.expected_answer,
                        list(q.rubric),
                        list(q.key_terms),
                        list(q.exact_values),
                        list(q.choices) if q.choices else None,
                        q.correct_choice,
                        q.position,
                    )
                    for q in questions
                ],
            )

    def for_part(self, part_id: UUID, language: str) -> list[Question]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM questions WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s) ORDER BY position",
            (language, part_id),
        ).fetchall()
        return [_question(row) for row in rows]

    def count_by_section(self, part_id: UUID, language: str) -> dict[UUID, int]:
        rows = self._conn.execute(
            "SELECT section_id, count(*) AS n FROM questions WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s) GROUP BY section_id",
            (language, part_id),
        ).fetchall()
        return {row["section_id"]: int(row["n"]) for row in rows}
