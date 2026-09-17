from __future__ import annotations

import io

from pypdf import PdfReader

from tests.helpers import make_pdf


def test_make_pdf_has_requested_pages():
    reader = PdfReader(io.BytesIO(make_pdf(3)))
    assert len(reader.pages) == 3
