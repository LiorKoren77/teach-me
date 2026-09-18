from __future__ import annotations

from pydantic import BaseModel

from teachme.domain.models import Figure, Page
from teachme.ingestion.errors import TooManyPages, UnsupportedMediaType
from teachme.ingestion.pdf_pages import page_count, pdf_batch
from teachme.ingestion.read_pages import read_image, read_pdf_batch
from teachme.ports.llm import LLMProvider
from teachme.settings import Settings

TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
PDF_TYPE = "application/pdf"


class Extraction(BaseModel):
    pages: list[Page]
    figures: list[Figure]
    vision_pages: int


class BatchExtraction(Extraction):
    """One read batch of a source, and what the whole source is. `total_pages` is how the caller
    knows whether anything is left to read - and, with `first_index`, how it resumes: the pages
    it already has are the ones it does not ask for again. `vision_pages` counts the whole
    source, because it is the cost of reading it and is recorded once, at the end."""

    total_pages: int


def extract_batch(
    llm: LLMProvider,
    settings: Settings,
    data: bytes,
    media_type: str,
    language_hint: str | None,
    *,
    first_index: int = 0,
) -> BatchExtraction:
    """One unit of reading: the batch of pages that starts at `first_index`, or nothing at all
    when that index is past the last page. Sized by PAGES_PER_READ_BATCH, so a caller with one
    function invocation to spend makes one model call in it rather than one per batch of a book.

    Dispatch is on media type. Every PDF and image page goes through the model so figures are
    described; text files become one page without a model call."""
    if media_type == PDF_TYPE:
        total = page_count(data)
        if total > settings.max_pages_per_source:
            raise TooManyPages(f"{total} pages exceeds MAX_PAGES_PER_SOURCE={settings.max_pages_per_source}")
        batch = pdf_batch(data, first_index, settings.pages_per_read_batch)
        if batch is None:
            return BatchExtraction(pages=[], figures=[], vision_pages=total, total_pages=total)
        pages, figures = read_pdf_batch(llm, settings.model_read_pages, batch, language_hint)
        return BatchExtraction(pages=pages, figures=figures, vision_pages=total, total_pages=total)
    if media_type in IMAGE_TYPES:
        if first_index >= 1:
            return BatchExtraction(pages=[], figures=[], vision_pages=1, total_pages=1)
        pages, figures = read_image(
            llm, settings.model_read_pages, data, media_type, page_index=0, language_hint=language_hint
        )
        return BatchExtraction(pages=pages, figures=figures, vision_pages=1, total_pages=1)
    if media_type in TEXT_TYPES:
        if first_index >= 1:
            return BatchExtraction(pages=[], figures=[], vision_pages=0, total_pages=1)
        text = data.decode("utf-8", errors="replace").strip()
        return BatchExtraction(
            pages=[Page(page_index=0, printed_number=None, text=text)],
            figures=[],
            vision_pages=0,
            total_pages=1,
        )
    raise UnsupportedMediaType(f"cannot extract {media_type!r}")


def extract(
    llm: LLMProvider, settings: Settings, data: bytes, media_type: str, language_hint: str | None
) -> Extraction:
    """Every batch of a source, in one call. The pipeline reads one batch per step instead; this
    is for a caller that has the whole file and the time to read it."""
    pages: list[Page] = []
    figures: list[Figure] = []
    while True:
        batch = extract_batch(llm, settings, data, media_type, language_hint, first_index=len(pages))
        if not batch.pages:
            return Extraction(pages=pages, figures=figures, vision_pages=batch.vision_pages)
        pages.extend(batch.pages)
        figures.extend(batch.figures)
