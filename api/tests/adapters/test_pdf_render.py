from __future__ import annotations

import struct

import pytest

from teachme.adapters.pdf_render import PageOutOfRange, render_page_png
from tests.helpers import make_pdf


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    return width, height


def test_render_page_png_returns_png_bytes_of_requested_size():
    width, height = _png_size(render_page_png(make_pdf(2), page_index=1, width=200))
    assert width == 200 and height > width  # A4 portrait


def test_render_page_png_is_deterministic():
    """The cache key promises one image per (source, page, width): the same page must not
    render differently on a second call."""
    pdf = make_pdf(1)
    assert render_page_png(pdf, page_index=0, width=120) == render_page_png(pdf, page_index=0, width=120)


def test_a_page_the_document_does_not_have_is_refused():
    with pytest.raises(PageOutOfRange):
        render_page_png(make_pdf(2), page_index=2, width=200)


def test_a_non_positive_width_is_refused():
    with pytest.raises(ValueError):
        render_page_png(make_pdf(1), page_index=0, width=0)
