from __future__ import annotations

from pydantic import BaseModel

from teachme.domain.models import Figure, Page
from teachme.ingestion.errors import TooManyPages, UnsupportedMediaType
from teachme.ingestion.pdf_pages import page_count, split_pdf
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


def extract(
    llm: LLMProvider, settings: Settings, data: bytes, media_type: str, language_hint: str | None
) -> Extraction:
    """Dispatch on media type. Every PDF and image page goes through the model so figures are
    described; text files become one page without a model call."""
    if media_type == PDF_TYPE:
        total = page_count(data)
        if total > settings.max_pages_per_source:
            raise TooManyPages(f"{total} pages exceeds MAX_PAGES_PER_SOURCE={settings.max_pages_per_source}")
        pages: list[Page] = []
        figures: list[Figure] = []
        for batch in split_pdf(data, settings.pages_per_read_batch):
            batch_pages, batch_figures = read_pdf_batch(llm, settings.model_read_pages, batch, language_hint)
            pages.extend(batch_pages)
            figures.extend(batch_figures)
        return Extraction(pages=pages, figures=figures, vision_pages=total)
    if media_type in IMAGE_TYPES:
        pages, figures = read_image(
            llm, settings.model_read_pages, data, media_type, page_index=0, language_hint=language_hint
        )
        return Extraction(pages=pages, figures=figures, vision_pages=1)
    if media_type in TEXT_TYPES:
        text = data.decode("utf-8", errors="replace").strip()
        return Extraction(
            pages=[Page(page_index=0, printed_number=None, text=text)], figures=[], vision_pages=0
        )
    raise UnsupportedMediaType(f"cannot extract {media_type!r}")
