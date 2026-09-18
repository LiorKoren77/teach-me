from __future__ import annotations

from uuid import UUID

from teachme.adapters.pdf_render import PageOutOfRange, UnreadablePdf, render_page_png
from teachme.ports.file_store import FileNotFound, FileStore
from teachme.repositories.sources import SourceRepository

DEFAULT_WIDTH = 800


def thumbnail_prefix(source_id: UUID) -> str:
    """Every thumbnail of one source lives under this prefix, at any width - what SourceService
    deletes when the source itself is deleted."""
    return f"thumbnails/{source_id}/"


class ThumbnailService:
    """PNG of a source page, rendered on first request and cached in the file store.

    The key names the source, the page and the width, so a page is rasterized at most once per
    width however many students read it - and a re-ingested source keeps its key, because the
    file behind a source never changes (a replacement is a new source with a new id)."""

    def __init__(self, files: FileStore, sources: SourceRepository, width: int = DEFAULT_WIDTH) -> None:
        self._files = files
        self._sources = sources
        self._width = width

    def key(self, source_id: UUID, page_index: int) -> str:
        return f"{thumbnail_prefix(source_id)}{page_index:03d}-w{self._width}.png"

    def png(self, source_id: UUID, page_index: int) -> bytes:
        """The page as PNG. FileNotFound when there is no image to serve: the source is not a
        PDF, or the page is past its end."""
        key = self.key(source_id, page_index)
        try:
            return self._files.get(key)
        except FileNotFound:
            pass
        source = self._sources.get(source_id)
        if source.media_type != "application/pdf":
            raise FileNotFound(key)
        if page_index < 0 or (source.page_count is not None and page_index >= source.page_count):
            raise FileNotFound(key)
        try:
            png = render_page_png(self._files.get(source.file_key), page_index=page_index, width=self._width)
        except (PageOutOfRange, UnreadablePdf):
            # page_count is null until extraction has run, and a recorded count could still
            # disagree with the file; the document itself has the last word. A page the document
            # cannot be opened or rendered at all is the same story: no image to serve, not a
            # vendor error to leak through the service and the route.
            raise FileNotFound(key) from None
        self._files.put(key, png, "image/png")
        return png
