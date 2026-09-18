from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Outline, Part, Section
from teachme.repositories.errors import NotFound


class OutlineNotFound(NotFound):
    entity = "outline"


class PartNotFound(NotFound):
    entity = "part"


class SectionNotFound(NotFound):
    entity = "section"


def _outline(row: dict) -> Outline:
    return Outline(id=row["id"], subject_id=row["subject_id"], version=row["version"], model=row["model"])


def _part(row: dict) -> Part:
    return Part(
        id=row["id"],
        outline_id=row["outline_id"],
        position=row["position"],
        title=row["title"],
        page_start=row["page_start"],
        page_end=row["page_end"],
    )


def _section(row: dict) -> Section:
    return Section(
        id=row["id"],
        part_id=row["part_id"],
        position=row["position"],
        title=row["title"],
        page_start=row["page_start"],
        page_end=row["page_end"],
    )


class OutlineRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, subject_id: UUID, *, model: str) -> Outline:
        row = self._conn.execute(
            "SELECT coalesce(max(version), 0) + 1 AS next FROM outlines WHERE subject_id = %s", (subject_id,)
        ).fetchone()
        outline_id = uuid4()
        self._conn.execute(
            "INSERT INTO outlines (id, subject_id, version, model) VALUES (%s, %s, %s, %s)",
            (outline_id, subject_id, row["next"], model),
        )
        return self.get(outline_id)

    def get(self, outline_id: UUID) -> Outline:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE id = %s", (outline_id,)
        ).fetchone()
        if row is None:
            raise OutlineNotFound(outline_id)
        return _outline(row)

    def latest(self, subject_id: UUID) -> Outline | None:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE subject_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        return _outline(row) if row else None

    def get_version(self, subject_id: UUID, version: int) -> Outline | None:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE subject_id = %s AND version = %s",
            (subject_id, version),
        ).fetchone()
        return _outline(row) if row else None

    def add_part(
        self, outline_id: UUID, *, position: int, title: str, page_start: int, page_end: int
    ) -> Part:
        part_id = uuid4()
        self._conn.execute(
            "INSERT INTO parts (id, outline_id, position, title, page_start, page_end)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (part_id, outline_id, position, title, page_start, page_end),
        )
        return self.get_part(part_id)

    def add_section(
        self, part_id: UUID, *, position: int, title: str, page_start: int, page_end: int
    ) -> Section:
        section_id = uuid4()
        self._conn.execute(
            "INSERT INTO sections (id, part_id, position, title, page_start, page_end)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (section_id, part_id, position, title, page_start, page_end),
        )
        return self.get_section(section_id)

    def get_part(self, part_id: UUID) -> Part:
        row = self._conn.execute(
            "SELECT id, outline_id, position, title, page_start, page_end FROM parts WHERE id = %s",
            (part_id,),
        ).fetchone()
        if row is None:
            raise PartNotFound(part_id)
        return _part(row)

    def get_section(self, section_id: UUID) -> Section:
        row = self._conn.execute(
            "SELECT id, part_id, position, title, page_start, page_end FROM sections WHERE id = %s",
            (section_id,),
        ).fetchone()
        if row is None:
            raise SectionNotFound(section_id)
        return _section(row)

    def parts(self, outline_id: UUID) -> list[Part]:
        rows = self._conn.execute(
            "SELECT id, outline_id, position, title, page_start, page_end FROM parts WHERE outline_id = %s"
            " ORDER BY position",
            (outline_id,),
        ).fetchall()
        return [_part(row) for row in rows]

    def sections(self, part_id: UUID) -> list[Section]:
        rows = self._conn.execute(
            "SELECT id, part_id, position, title, page_start, page_end FROM sections WHERE part_id = %s"
            " ORDER BY position",
            (part_id,),
        ).fetchall()
        return [_section(row) for row in rows]

    def sections_of_outline(self, outline_id: UUID) -> list[Section]:
        rows = self._conn.execute(
            "SELECT s.id, s.part_id, s.position, s.title, s.page_start, s.page_end FROM sections s"
            " JOIN parts p ON p.id = s.part_id WHERE p.outline_id = %s ORDER BY p.position, s.position",
            (outline_id,),
        ).fetchall()
        return [_section(row) for row in rows]
