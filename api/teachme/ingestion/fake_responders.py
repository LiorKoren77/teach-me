from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder
from teachme.ingestion.contextualize import ChunkOut, ChunksOut
from teachme.ingestion.detect_language import DetectedLanguage
from teachme.ingestion.read_pages import ReadFigure, ReadPage, ReadPagesOutput
from teachme.ports.llm import StructuredRequest

_COUNT = re.compile(r"exactly (\d+) pages")
_PAGE_TAG = re.compile(r'<page index="(\d+)" printed="[^"]*">\n(.*?)\n</page>', re.DOTALL)


def _read_pages(request: StructuredRequest) -> BaseModel:
    text_part = next(p for p in request.parts if p.kind == "text")
    count = int(_COUNT.search(text_part.text or "").group(1))
    pages = []
    for offset in range(count):
        figures = (
            [ReadFigure(kind="map", caption="Fake map", description="A fake map for tests.")]
            if offset == 0
            else []
        )
        pages.append(
            ReadPage(
                page_offset=offset,
                printed_number=str(offset + 1),
                text_markdown=f"Fake text of page offset {offset}.",
                figures=figures,
            )
        )
    return ReadPagesOutput(pages=pages)


def _detect_language(request: StructuredRequest) -> BaseModel:
    return DetectedLanguage(code="en", name="English")


def _contextualize(request: StructuredRequest) -> BaseModel:
    body = request.parts[0].text or ""
    batch = body.split("<batch>")[1].split("</batch>")[0]
    chunks = [
        ChunkOut(
            context=f"Fake context for page {index}.",
            original_text=text.strip(),
            page_start=int(index),
            page_end=int(index),
        )
        for index, text in _PAGE_TAG.findall(batch)
    ]
    return ChunksOut(chunks=chunks)


def default_responders() -> dict[type[BaseModel], Responder]:
    """Responders for every ingestion schema, so the pipeline runs end to end without a key."""
    return {ReadPagesOutput: _read_pages, DetectedLanguage: _detect_language, ChunksOut: _contextualize}
