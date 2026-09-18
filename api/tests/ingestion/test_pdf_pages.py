from __future__ import annotations

import pytest

from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import page_count, split_pdf
from tests.helpers import make_pdf


def test_page_count():
    assert page_count(make_pdf(7)) == 7


def test_split_into_batches_with_valid_pdfs():
    batches = split_pdf(make_pdf(7), pages_per_batch=3)
    assert [(b.first_index, b.last_index) for b in batches] == [(0, 2), (3, 5), (6, 6)]
    assert [b.page_count for b in batches] == [3, 3, 1]
    assert all(page_count(b.data) == b.page_count for b in batches)


def test_split_single_batch_when_small():
    batches = split_pdf(make_pdf(2), pages_per_batch=6)
    assert len(batches) == 1 and batches[0].page_count == 2


def test_invalid_pdf_raises():
    with pytest.raises(ExtractionError):
        page_count(b"not a pdf")
