from __future__ import annotations

import io

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from teachme.ingestion.errors import ExtractionError


class PdfBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_index: int
    last_index: int
    data: bytes

    @property
    def page_count(self) -> int:
        return self.last_index - self.first_index + 1


def _reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        _ = len(reader.pages)
        return reader
    except (PyPdfError, ValueError, TypeError) as exc:
        raise ExtractionError(f"not a readable PDF: {exc}") from exc


def page_count(data: bytes) -> int:
    return len(_reader(data).pages)


def pdf_batch(data: bytes, first_index: int, pages_per_batch: int) -> PdfBatch | None:
    """The one batch that starts at `first_index`, written as its own small PDF for one model
    call, or None when that index is past the last page. Resumable extraction asks for exactly
    the batch it is missing rather than splitting the whole file to throw most of it away."""
    reader = _reader(data)
    total = len(reader.pages)
    if first_index >= total:
        return None
    last = min(first_index + pages_per_batch, total) - 1
    writer = PdfWriter()
    for index in range(first_index, last + 1):
        writer.add_page(reader.pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return PdfBatch(first_index=first_index, last_index=last, data=buffer.getvalue())


def split_pdf(data: bytes, pages_per_batch: int) -> list[PdfBatch]:
    """Consecutive page ranges, each written as its own small PDF for one model call."""
    batches: list[PdfBatch] = []
    first = 0
    while (batch := pdf_batch(data, first, pages_per_batch)) is not None:
        batches.append(batch)
        first = batch.last_index + 1
    return batches
