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


def split_pdf(data: bytes, pages_per_batch: int) -> list[PdfBatch]:
    """Consecutive page ranges, each written as its own small PDF for one model call."""
    reader = _reader(data)
    total = len(reader.pages)
    batches: list[PdfBatch] = []
    for first in range(0, total, pages_per_batch):
        last = min(first + pages_per_batch, total) - 1
        writer = PdfWriter()
        for index in range(first, last + 1):
            writer.add_page(reader.pages[index])
        buffer = io.BytesIO()
        writer.write(buffer)
        batches.append(PdfBatch(first_index=first, last_index=last, data=buffer.getvalue()))
    return batches
