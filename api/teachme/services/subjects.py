from __future__ import annotations

from collections.abc import Sequence

import psycopg

from teachme.domain.models import Subject, SubjectState
from teachme.repositories.errors import SubjectNotFound
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings


class LanguageNotEnabled(ValueError):
    pass


class SubjectService:
    def __init__(self, conn: psycopg.Connection, subjects: SubjectRepository, settings: Settings) -> None:
        self._conn = conn
        self._subjects = subjects
        self._settings = settings

    def get_or_create(
        self, name: str, languages: Sequence[str] | None = None, created_by: str | None = None
    ) -> Subject:
        existing = self._subjects.get_by_name(name)
        if existing:
            return existing
        chosen = list(languages) if languages else list(self._settings.enabled_languages)
        disallowed = [code for code in chosen if code not in self._settings.enabled_languages]
        if disallowed:
            raise LanguageNotEnabled(f"languages not enabled in settings: {disallowed}")
        subject = self._subjects.create(name, chosen, created_by)
        self._conn.commit()
        return subject

    def require(self, name: str) -> Subject:
        subject = self._subjects.get_by_name(name)
        if subject is None:
            raise SubjectNotFound(name)
        return subject

    def list(self) -> list[Subject]:
        return self._subjects.list()

    def set_state(self, subject: Subject, state: SubjectState) -> None:
        self._subjects.set_state(subject.id, state)
        self._conn.commit()
