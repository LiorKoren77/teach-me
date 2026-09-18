from __future__ import annotations

from uuid import UUID


class NotFound(Exception):
    entity = "entity"

    def __init__(self, identifier: UUID | str) -> None:
        super().__init__(f"{self.entity} {identifier} not found")
        self.identifier = identifier


class SubjectNotFound(NotFound):
    entity = "subject"


class SourceNotFound(NotFound):
    entity = "source"


class JobNotFound(NotFound):
    entity = "job"
