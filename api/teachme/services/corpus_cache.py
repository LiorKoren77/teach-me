from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from threading import Lock
from uuid import UUID

from teachme.domain.models import Subject
from teachme.domain.text.normalize import tokenize
from teachme.generation.corpus import SubjectCorpus

DEFAULT_MAX_ENTRIES = 8
"""Rendered corpora kept at once. A corpus is the whole subject's text, so the cache is capped
rather than left to grow with every subject and version a process ever serves."""

VOCABULARIES_PER_CORPUS = 16
"""Section vocabularies are much smaller than a corpus and there are many per subject, so their
cap is a multiple of the corpus cap."""

CorpusKey = tuple[UUID, int | None]
VocabKey = tuple[UUID, int | None, int, int, str]


class CorpusCache:
    """One rendered corpus per (subject, published version) per process, plus per-section
    vocabularies. Lives on the container so request scopes share it.

    Loading is locked per key, not cache-wide: rendering one subject's corpus takes seconds, and
    under a single lock every other request - including requests for a subject already cached -
    waited behind it. The cache-wide lock is held only to look in the maps and to hand out the
    lock for one key, never across a load.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max(1, max_entries)
        self._corpora: OrderedDict[CorpusKey, SubjectCorpus] = OrderedDict()
        self._vocab: OrderedDict[VocabKey, frozenset[str]] = OrderedDict()
        self._guard = Lock()
        self._loading: dict[Hashable, Lock] = {}

    def corpus(self, subject: Subject, loader: Callable[[], SubjectCorpus]) -> SubjectCorpus:
        key: CorpusKey = (subject.id, subject.current_outline_version)
        return self._load_once(self._corpora, key, loader, self._max_entries)

    def section_vocabulary(
        self, subject: Subject, corpus: SubjectCorpus, page_start: int, page_end: int, language: str
    ) -> frozenset[str]:
        """Tokens of a section's pages, in the student's language and the source's: an answer
        written in either is measured against the same vocabulary."""
        key: VocabKey = (subject.id, subject.current_outline_version, page_start, page_end, language)

        def loader() -> frozenset[str]:
            text = corpus.render(page_start, page_end)
            return frozenset(tokenize(text, language)) | frozenset(
                tokenize(text, corpus.language or language)
            )

        return self._load_once(self._vocab, key, loader, self._max_entries * VOCABULARIES_PER_CORPUS)

    def _load_once(self, cache: OrderedDict, key: Hashable, loader: Callable, max_entries: int):
        """Double-checked, per-key: look, take this key's lock, look again, then load.

        The second look is what keeps two threads racing for one key from both paying for it; the
        lock being per key is what keeps either of them from blocking a third thread asking for
        something else."""
        with self._guard:
            hit = self._peek(cache, key)
            if hit is not None:
                return hit
            lock = self._loading.setdefault(key, Lock())
        with lock:
            with self._guard:
                hit = self._peek(cache, key)
            if hit is not None:
                return hit
            value = loader()
            with self._guard:
                cache[key] = value
                cache.move_to_end(key)
                while len(cache) > max_entries:
                    cache.popitem(last=False)
                self._forget_idle_locks()
            return value

    @staticmethod
    def _peek(cache: OrderedDict, key: Hashable):
        """A hit, kept as the most recently used entry so eviction drops the coldest key."""
        if key not in cache:
            return None
        cache.move_to_end(key)
        return cache[key]

    def _forget_idle_locks(self) -> None:
        """Called under the guard, after eviction: a lock for a key no longer cached and not held
        by anyone is dropped, so the lock map does not outgrow the cache it protects."""
        stale = [
            key
            for key, lock in self._loading.items()
            if key not in self._corpora and key not in self._vocab and not lock.locked()
        ]
        for key in stale:
            del self._loading[key]
