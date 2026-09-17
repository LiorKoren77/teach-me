from __future__ import annotations

import io

from pypdf import PdfWriter


def make_pdf(n_pages: int) -> bytes:
    """A PDF with n blank A4 pages. Enough for page counting and batch splitting;
    the fake LLM does not read page content."""
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
