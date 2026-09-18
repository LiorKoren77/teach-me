from __future__ import annotations

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.read_pages import (
    ReadFigure,
    ReadPage,
    ReadPagesOutput,
    format_figure_block,
    read_image,
    read_pdf_batch,
)


def _output(n, with_figure=True):
    pages = []
    for i in range(n):
        figures = (
            [ReadFigure(kind="map", caption="World 1850", description="A world map.")]
            if with_figure and i == 0
            else []
        )
        pages.append(
            ReadPage(
                page_offset=i, printed_number=str(10 + i), text_markdown=f"Page {i} text.", figures=figures
            )
        )
    return ReadPagesOutput(pages=pages)


def test_read_pdf_batch_maps_offsets_to_source_indices_and_appends_figure_blocks():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(2)})
    batch = PdfBatch(first_index=4, last_index=5, data=b"%PDF")
    pages, figures = read_pdf_batch(llm, "fake-model", batch, language_hint="pt")
    assert [p.page_index for p in pages] == [4, 5]
    assert pages[0].printed_number == "10"
    assert pages[0].text.startswith("Page 0 text.")
    assert "> **[Figure: World 1850]** A world map." in pages[0].text
    assert "[Figure" not in pages[1].text
    assert figures == [
        type(figures[0])(
            page_index=4, ordinal=0, kind="map", caption="World 1850", description="A world map."
        )
    ]
    request = llm.calls[0]
    assert request.purpose == "ingest.read_pages" and request.parts[0].kind == "document"
    assert "2 pages" in request.parts[1].text and "pt" in request.parts[1].text


def test_wrong_page_count_is_an_extraction_error():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(1)})
    with pytest.raises(ExtractionError):
        read_pdf_batch(
            llm, "fake-model", PdfBatch(first_index=0, last_index=2, data=b"%PDF"), language_hint=None
        )


def test_read_image_is_a_single_page():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(1, with_figure=False)})
    pages, figures = read_image(llm, "fake-model", b"\x89PNG", "image/png", page_index=0)
    assert len(pages) == 1 and pages[0].page_index == 0 and figures == []
    assert llm.calls[0].parts[0].kind == "image"


def test_format_figure_block_without_caption():
    block = format_figure_block(ReadFigure(kind="photo", caption="", description="A harbour."))
    assert block == "\n\n> **[Figure: photo]** A harbour.\n"
