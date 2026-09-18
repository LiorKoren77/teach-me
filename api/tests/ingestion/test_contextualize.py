from __future__ import annotations

import re

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Chunk, Page
from teachme.ingestion.contextualize import (
    ChunkOut,
    ChunksOut,
    batch_pages,
    contextualize,
    render_pages,
    validate_coverage,
)
from teachme.ingestion.errors import CoverageError


def _pages(n):
    return [Page(page_index=i, printed_number=str(i + 1), text=f"Text of page {i}.") for i in range(n)]


def _one_chunk_per_page(req):
    body = req.parts[0].text
    batch = body.split("<batch>")[1].split("</batch>")[0]
    indices = [int(m) for m in re.findall(r'<page index="(\d+)"', batch)]
    return ChunksOut(
        chunks=[
            ChunkOut(context=f"ctx {i}", original_text=f"Text of page {i}.", page_start=i, page_end=i)
            for i in indices
        ]
    )


def test_batch_pages():
    assert [[p.page_index for p in b] for b in batch_pages(_pages(5), 2)] == [[0, 1], [2, 3], [4]]


def test_render_pages_wraps_with_tags():
    rendered = render_pages(_pages(1))
    assert rendered == '<page index="0" printed="1">\nText of page 0.\n</page>'


def test_validate_coverage_reports_missing_pages():
    chunks = [Chunk(context="c", text="t", page_start=0, page_end=1)]
    validate_coverage(_pages(2), chunks)
    with pytest.raises(CoverageError, match="2"):
        validate_coverage(_pages(3), chunks)


def test_contextualize_includes_neighbours_and_returns_domain_chunks():
    llm = FakeLLM({ChunksOut: _one_chunk_per_page})
    chunks = contextualize(llm, "fake-model", "Geo", "ch1.pdf", "en", _pages(5), pages_per_batch=2)
    assert [(c.page_start, c.page_end) for c in chunks] == [(i, i) for i in range(5)]
    assert chunks[2].content == "ctx 2\n\nText of page 2."
    second_call = llm.calls[1].parts[0].text
    assert "<context_before>" in second_call and 'index="1"' in second_call.split("<batch>")[0]
    assert "<context_after>" in second_call and 'index="4"' in second_call.split("</batch>")[1]
    assert "Geo" in llm.calls[0].system and "ch1.pdf" in llm.calls[0].system
    assert llm.calls[0].purpose == "ingest.contextualize"
