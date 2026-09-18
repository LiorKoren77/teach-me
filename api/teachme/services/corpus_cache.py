from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from uuid import UUID

from teachme.domain.models import Subject
from teachme.domain.text.normalize import tokenize
from teachme.generation.corpus import SubjectCorpus


class CorpusCache:
    """One rendered corpus per (subject, published version) per process, plus per-section
    vocabularies. Lives on the container so request scopes share it."""

    def __init__(self) -> None:
        self._corpora: dict[tuple[UUID, int | None], SubjectCorpus] = {}
        self._vocab: dict[tuple[UUID, int | None, int, int, str], frozenset[str]] = {}
        self._lock = Lock()

    def corpus(self, subject: Subject, loader: Callable[[], SubjectCorpus]) -> SubjectCorpus:
        key = (subject.id, subject.current_outline_version)
        with self._lock:
            if key not in self._corpora:
                self._corpora[key] = loader()
            return self._corpora[key]

    def section_vocabulary(
        self, subject: Subject, corpus: SubjectCorpus, page_start: int, page_end: int, language: str
    ) -> frozenset[str]:
        """Tokens of a section's pages, in the student's language and the source's: an answer
        written in either is measured against the same vocabulary."""
        key = (subject.id, subject.current_outline_version, page_start, page_end, language)
        with self._lock:
            if key not in self._vocab:
                text = corpus.render(page_start, page_end)
                self._vocab[key] = frozenset(tokenize(text, language)) | frozenset(
                    tokenize(text, corpus.language or language)
                )
            return self._vocab[key]
