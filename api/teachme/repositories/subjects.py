from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Subject, SubjectState
from teachme.repositories.errors import SubjectNotFound

_COLUMNS = "id, name, state, languages, created_by"


def _row_to_subject(row: dict) -> Subject:
    return Subject(
        id=row["id"],
        name=row["name"],
        state=SubjectState(row["state"]),
        languages=tuple(row["languages"]),
        created_by=row["created_by"],
    )


class SubjectRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, name: str, languages: Sequence[str], created_by: str | None = None) -> Subject:
        subject_id = uuid4()
        self._conn.execute(
            "INSERT INTO subjects (id, name, languages, created_by) VALUES (%s, %s, %s, %s)",
            (subject_id, name, list(languages), created_by),
        )
        return self.get(subject_id)

    def get(self, subject_id: UUID) -> Subject:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects WHERE id = %s", (subject_id,)).fetchone()
        if row is None:
            raise SubjectNotFound(subject_id)
        return _row_to_subject(row)

    def get_by_name(self, name: str) -> Subject | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects WHERE name = %s", (name,)).fetchone()
        return _row_to_subject(row) if row else None

    def list(self) -> list[Subject]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects ORDER BY name").fetchall()
        return [_row_to_subject(row) for row in rows]

    def set_state(self, subject_id: UUID, state: SubjectState) -> None:
        self._conn.execute("UPDATE subjects SET state = %s WHERE id = %s", (state.value, subject_id))
