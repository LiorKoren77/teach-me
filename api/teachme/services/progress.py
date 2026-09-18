from __future__ import annotations

from uuid import UUID

import psycopg
from pydantic import BaseModel

from teachme.domain.models import PartProgress, PartStatus, Subject
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.progress import ProgressRepository


class PartView(BaseModel):
    part_id: UUID
    position: int
    title: str
    status: PartStatus
    locked: bool
    best_score: float | None
    rounds_used: int


class ProgressService:
    """Where a student stands in a subject, and the locks derived from it."""

    def __init__(
        self, conn: psycopg.Connection, outlines: OutlineRepository, progress: ProgressRepository
    ) -> None:
        self._conn = conn
        self._outlines = outlines
        self._progress = progress

    def parts_with_progress(self, user_id: str, subject: Subject) -> list[PartView]:
        """Ensures rows exist, then derives locks: a part is locked until the previous one is passed."""
        assert subject.current_outline_version is not None
        outline = self._outlines.get_version(subject.id, subject.current_outline_version)
        assert outline is not None
        parts = self._outlines.parts(outline.id)
        rows = {
            r.part_id: r
            for r in self._progress.ensure_for_subject(
                user_id, subject.id, outline.version, [p.id for p in parts]
            )
        }
        self._conn.commit()
        views: list[PartView] = []
        previous_passed = True
        for part in parts:
            row: PartProgress = rows[part.id]
            views.append(
                PartView(
                    part_id=part.id,
                    position=part.position,
                    title=part.title,
                    status=row.status,
                    locked=not previous_passed,
                    best_score=row.best_score,
                    rounds_used=row.rounds_used,
                )
            )
            previous_passed = row.status == PartStatus.PASSED
        return views

    def reset_for_new_version(self, subject: Subject, version: int) -> int:
        """A newly published outline version has new part ids: old progress cannot be carried over."""
        deleted = self._progress.reset_subject(subject.id)
        self._conn.commit()
        return deleted
