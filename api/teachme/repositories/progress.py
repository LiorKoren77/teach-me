from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import PartProgress, PartStatus
from teachme.repositories.errors import NotFound

_COLUMNS = "id, user_id, subject_id, part_id, outline_version, status, best_score, rounds_used"


class ProgressNotFound(NotFound):
    entity = "progress"


def _row(row: dict) -> PartProgress:
    return PartProgress(
        id=row["id"],
        user_id=row["user_id"],
        subject_id=row["subject_id"],
        part_id=row["part_id"],
        outline_version=row["outline_version"],
        status=PartStatus(row["status"]),
        best_score=float(row["best_score"]) if row["best_score"] is not None else None,
        rounds_used=row["rounds_used"],
    )


class ProgressRepository:
    """One row per (student, part). Never commits: the service owns the transaction boundary."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def ensure_for_subject(
        self, user_id: str, subject_id: UUID, outline_version: int, part_ids: Sequence[UUID]
    ) -> list[PartProgress]:
        """Create NOT_STARTED rows for parts the student has no row for; idempotent."""
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO part_progress (id, user_id, subject_id, part_id, outline_version, status)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, part_id) DO NOTHING",
                [
                    (uuid4(), user_id, subject_id, part_id, outline_version, PartStatus.NOT_STARTED.value)
                    for part_id in part_ids
                ],
            )
        return self.list_for_subject(user_id, subject_id)

    def get(self, user_id: str, part_id: UUID) -> PartProgress:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM part_progress WHERE user_id = %s AND part_id = %s",
            (user_id, part_id),
        ).fetchone()
        if row is None:
            raise ProgressNotFound(part_id)
        return _row(row)

    def list_for_subject(self, user_id: str, subject_id: UUID) -> list[PartProgress]:
        rows = self._conn.execute(
            f"SELECT pp.{_COLUMNS.replace(', ', ', pp.')} FROM part_progress pp"
            " JOIN parts p ON p.id = pp.part_id"
            " WHERE pp.user_id = %s AND pp.subject_id = %s ORDER BY p.position",
            (user_id, subject_id),
        ).fetchall()
        return [_row(row) for row in rows]

    def update(
        self,
        progress_id: UUID,
        *,
        status: PartStatus | None = None,
        best_score: float | None = None,
        rounds_used: int | None = None,
    ) -> None:
        """Every field is optional; best_score only ever moves up."""
        self._conn.execute(
            "UPDATE part_progress SET status = coalesce(%s, status),"
            " best_score = greatest(coalesce(%s, best_score), coalesce(best_score, %s)),"
            " rounds_used = coalesce(%s, rounds_used), updated_at = now() WHERE id = %s",
            (status.value if status else None, best_score, best_score, rounds_used, progress_id),
        )

    def reset_subject(self, subject_id: UUID) -> int:
        """Called when a subject is published with a new outline version: old parts no longer exist."""
        result = self._conn.execute("DELETE FROM part_progress WHERE subject_id = %s", (subject_id,))
        return result.rowcount
