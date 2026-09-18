from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.ports.file_store import FileNotFound
from teachme.services.thumbnails import ThumbnailService
from tests.helpers import make_pdf


class _Sources:
    """Stands in for SourceRepository: the service only ever reads one source."""

    def __init__(self, **fields) -> None:
        self._fields = {"media_type": "application/pdf", "file_key": "k", "page_count": 3, **fields}

    def get(self, source_id):
        return SimpleNamespace(id=source_id, **self._fields)


def _service(sources: _Sources, files: InMemoryFileStore) -> ThumbnailService:
    return ThumbnailService(files, sources, width=120)


def test_thumbnail_rendered_once_then_served_from_cache():
    files = InMemoryFileStore()
    files.put("k", make_pdf(3), "application/pdf")
    service = _service(_Sources(), files)
    source_id = uuid4()

    first = service.png(source_id, page_index=2)
    assert first[:4] == b"\x89PNG"
    assert files.exists(f"thumbnails/{source_id}/002-w120.png")

    files.put("k", b"garbage", "application/pdf")  # cache must not re-render
    assert service.png(source_id, page_index=2) == first


def test_the_cache_key_is_deterministic_and_per_page():
    files = InMemoryFileStore()
    files.put("k", make_pdf(3), "application/pdf")
    service = _service(_Sources(), files)
    source_id = uuid4()
    service.png(source_id, page_index=0)
    service.png(source_id, page_index=1)
    assert files.list_keys(f"thumbnails/{source_id}/") == [
        f"thumbnails/{source_id}/000-w120.png",
        f"thumbnails/{source_id}/001-w120.png",
    ]


def test_a_page_past_the_end_and_a_non_pdf_source_have_no_image():
    files = InMemoryFileStore()
    files.put("k", make_pdf(3), "application/pdf")
    source_id = uuid4()
    with pytest.raises(FileNotFound):
        _service(_Sources(), files).png(source_id, page_index=3)
    with pytest.raises(FileNotFound):
        _service(_Sources(media_type="text/markdown"), files).png(source_id, page_index=0)


def test_an_unreadable_pdf_answers_file_not_found_not_the_vendor_error():
    files = InMemoryFileStore()
    files.put("k", b"not a pdf", "application/pdf")
    with pytest.raises(FileNotFound):
        _service(_Sources(page_count=None), files).png(uuid4(), page_index=0)


def test_a_source_of_unknown_length_is_bounded_by_the_document_itself():
    """page_count is null until extraction has run; the renderer still must not be asked for a
    page the file does not have."""
    files = InMemoryFileStore()
    files.put("k", make_pdf(2), "application/pdf")
    with pytest.raises(FileNotFound):
        _service(_Sources(page_count=None), files).png(uuid4(), page_index=5)
