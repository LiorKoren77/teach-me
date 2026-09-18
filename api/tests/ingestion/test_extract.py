from __future__ import annotations

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.ingestion.detect_language import DetectedLanguage, detect_language
from teachme.ingestion.errors import TooManyPages, UnsupportedMediaType
from teachme.ingestion.extract import extract
from teachme.ingestion.read_pages import ReadPage, ReadPagesOutput
from teachme.settings import Settings
from tests.helpers import make_pdf


def _responder(req):
    count = int(req.parts[1].text.split("exactly ")[1].split(" ")[0])
    return ReadPagesOutput(
        pages=[
            ReadPage(page_offset=i, printed_number=None, text_markdown=f"p{i}", figures=[])
            for i in range(count)
        ]
    )


def _settings(**overrides):
    return Settings(_env_file=None, llm_provider="fake", **overrides)


def test_pdf_is_read_in_batches():
    llm = FakeLLM({ReadPagesOutput: _responder})
    result = extract(
        llm, _settings(pages_per_read_batch=3), make_pdf(7), "application/pdf", language_hint=None
    )
    assert [p.page_index for p in result.pages] == list(range(7))
    assert result.vision_pages == 7 and len(llm.calls) == 3


def test_text_file_needs_no_model():
    llm = FakeLLM({})
    result = extract(llm, _settings(), b"# Title\n\nBody", "text/markdown", language_hint=None)
    assert len(result.pages) == 1 and result.pages[0].text.startswith("# Title") and result.vision_pages == 0
    assert llm.calls == []


def test_image_is_one_vision_page():
    llm = FakeLLM({ReadPagesOutput: _responder})
    result = extract(llm, _settings(), b"\x89PNG", "image/png", language_hint="he")
    assert len(result.pages) == 1 and result.vision_pages == 1


def test_unsupported_and_too_many_pages():
    llm = FakeLLM({ReadPagesOutput: _responder})
    with pytest.raises(UnsupportedMediaType):
        extract(llm, _settings(), b"x", "application/zip", language_hint=None)
    with pytest.raises(TooManyPages):
        extract(llm, _settings(max_pages_per_source=3), make_pdf(4), "application/pdf", language_hint=None)


def test_detect_language_uses_first_pages():
    llm = FakeLLM({DetectedLanguage: lambda req: DetectedLanguage(code="pt", name="Portuguese")})
    from teachme.domain.models import Page

    pages = [Page(page_index=i, printed_number=None, text=f"texto {i}") for i in range(5)]
    assert detect_language(llm, "fake-model", pages) == "pt"
    assert "texto 0" in llm.calls[0].parts[0].text and llm.calls[0].purpose == "ingest.detect_language"


def test_detect_language_empty_pages_is_none():
    assert detect_language(FakeLLM({}), "fake-model", []) is None


def test_detect_language_und_is_none():
    from teachme.domain.models import Page

    llm = FakeLLM({DetectedLanguage: lambda req: DetectedLanguage(code="und", name="Undetermined")})
    pages = [Page(page_index=0, printed_number=None, text="???")]
    assert detect_language(llm, "fake-model", pages) is None


def test_detect_language_non_code_is_none():
    from teachme.domain.models import Page

    llm = FakeLLM({DetectedLanguage: lambda req: DetectedLanguage(code="Portuguese", name="Portuguese")})
    pages = [Page(page_index=0, printed_number=None, text="texto")]
    assert detect_language(llm, "fake-model", pages) is None


def test_detect_language_normalizes_case():
    from teachme.domain.models import Page

    llm = FakeLLM({DetectedLanguage: lambda req: DetectedLanguage(code="PT", name="Portuguese")})
    pages = [Page(page_index=0, printed_number=None, text="texto")]
    assert detect_language(llm, "fake-model", pages) == "pt"
