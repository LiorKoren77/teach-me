from __future__ import annotations

from threading import Event, Thread
from uuid import uuid4

from teachme.domain.models import Subject, SubjectState
from teachme.generation.corpus import CorpusPage, SubjectCorpus
from teachme.services.corpus_cache import CorpusCache

TIMEOUT = 10.0


def _subject(version: int = 1) -> Subject:
    return Subject(
        id=uuid4(),
        name="S",
        state=SubjectState.PUBLISHED,
        languages=("en",),
        current_outline_version=version,
    )


def _corpus(text: str = "ozone layer absorbs radiation") -> SubjectCorpus:
    page = CorpusPage(
        global_index=0,
        source_id=uuid4(),
        source_name="ch1.pdf",
        page_index=0,
        printed_number=None,
        text=text,
    )
    return SubjectCorpus(pages=(page,), language="en")


def test_a_corpus_is_loaded_once_per_subject_version():
    cache = CorpusCache()
    subject = _subject()
    loads = 0

    def loader() -> SubjectCorpus:
        nonlocal loads
        loads += 1
        return _corpus()

    first = cache.corpus(subject, loader)
    assert cache.corpus(subject, loader) is first and loads == 1
    # a new published version is a different corpus, not a cache hit
    cache.corpus(subject.model_copy(update={"current_outline_version": 2}), loader)
    assert loads == 2


def test_loading_one_corpus_does_not_block_another_key():
    """A whole-subject corpus takes seconds to render. A single cache-wide lock made every other
    student's request wait behind it, including requests for subjects already cached."""
    cache = CorpusCache()
    slow, other = _subject(), _subject()
    loading = Event()
    released = Event()

    def slow_loader() -> SubjectCorpus:
        loading.set()
        assert released.wait(TIMEOUT), "the other key never finished loading"
        return _corpus("slow")

    thread = Thread(target=lambda: cache.corpus(slow, slow_loader), daemon=True)
    thread.start()
    assert loading.wait(TIMEOUT)
    assert cache.corpus(other, lambda: _corpus("other")).pages[0].text == "other"
    released.set()
    thread.join(TIMEOUT)
    assert not thread.is_alive()
    assert cache.corpus(slow, lambda: _corpus("never")).pages[0].text == "slow"


def test_two_threads_racing_for_one_key_load_it_once():
    cache = CorpusCache()
    subject = _subject()
    loading = Event()
    released = Event()
    loads = 0
    seen: list[SubjectCorpus] = []

    def loader() -> SubjectCorpus:
        nonlocal loads
        loads += 1
        loading.set()
        assert released.wait(TIMEOUT)
        return _corpus()

    threads = [Thread(target=lambda: seen.append(cache.corpus(subject, loader)), daemon=True)]
    threads[0].start()
    assert loading.wait(TIMEOUT)
    threads.append(Thread(target=lambda: seen.append(cache.corpus(subject, loader)), daemon=True))
    threads[1].start()
    released.set()
    for thread in threads:
        thread.join(TIMEOUT)
    assert loads == 1 and len(seen) == 2 and seen[0] is seen[1]


def test_the_cache_keeps_only_the_most_recent_entries():
    """Unbounded, the cache held every version of every subject a process ever served - whole
    rendered corpora - for the life of the process."""
    cache = CorpusCache(max_entries=2)
    subjects = [_subject() for _ in range(3)]
    loads: list[int] = []

    def load(index: int):
        def loader() -> SubjectCorpus:
            loads.append(index)
            return _corpus(f"corpus-{index}")

        return loader

    for index, subject in enumerate(subjects):
        cache.corpus(subject, load(index))
    assert loads == [0, 1, 2]
    cache.corpus(subjects[2], load(2))  # still cached
    cache.corpus(subjects[1], load(1))  # still cached
    assert loads == [0, 1, 2]
    cache.corpus(subjects[0], load(0))  # evicted by the third subject: loaded again
    assert loads == [0, 1, 2, 0]


def test_section_vocabularies_are_cached_per_section_and_language():
    cache = CorpusCache()
    subject = _subject()
    corpus = _corpus()
    vocab = cache.section_vocabulary(subject, corpus, 0, 0, "en")
    assert "ozone" in vocab
    assert cache.section_vocabulary(subject, corpus, 0, 0, "en") is vocab
