from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image


class PageOutOfRange(IndexError):
    """The document has no such page. A programming error everywhere but at the store boundary,
    where a source's recorded page count can disagree with the file behind it."""

    def __init__(self, page_index: int, page_count: int) -> None:
        super().__init__(f"page {page_index} of a document with {page_count} pages")
        self.page_index = page_index
        self.page_count = page_count


class UnreadablePdf(ValueError):
    """The bytes at the store boundary do not decode (or do not render) as a PDF pypdfium2 can
    open, even though something upstream recorded them as application/pdf. A sibling of
    PageOutOfRange: both name a document that disagrees with what the caller expected of it,
    rather than letting pypdfium2's own exception escape to a service or a route."""


def render_page_png(pdf: bytes, *, page_index: int, width: int) -> bytes:
    """Rasterize one page to PNG at exactly the given width (height follows the page's aspect
    ratio). Deterministic: the same bytes, page and width always give the same image, which is
    what lets the result be cached under a key naming those three."""
    if width <= 0:
        raise ValueError(f"width must be positive, got {width}")
    try:
        document = pdfium.PdfDocument(pdf)
    except pdfium.PdfiumError as exc:
        raise UnreadablePdf(str(exc)) from exc
    try:
        if not 0 <= page_index < len(document):
            raise PageOutOfRange(page_index, len(document))
        try:
            page = document[page_index]
            image = page.render(scale=width / page.get_width()).to_pil()
        except pdfium.PdfiumError as exc:
            raise UnreadablePdf(str(exc)) from exc
        if image.width != width:
            # pypdfium rounds the bitmap up to whole pixels; the cache key promises the width it
            # names, so the last pixel column is scaled away rather than handed to the client.
            height = max(1, round(image.height * width / image.width))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
