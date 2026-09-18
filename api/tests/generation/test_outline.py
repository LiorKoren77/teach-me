from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Page, Source, SourceStatus
from teachme.generation.corpus import build_corpus
from teachme.generation.errors import GenerationValidationError
from teachme.generation.outline import (
    LARGE_CORPUS_CHARS,
    OutlineOut,
    PartOut,
    SectionOut,
    generate_outline,
    validate_outline,
)


def _corpus(n_pages, sources=1):
    srcs, pages = [], {}
    per = n_pages // sources
    for i in range(sources):
        s = Source(
            id=uuid4(),
            subject_id=uuid4(),
            filename=f"s{i}.pdf",
            media_type="application/pdf",
            file_key="k",
            size=1,
            status=SourceStatus.READY,
            page_count=per,
            detected_language="en",
        )
        srcs.append(s)
        pages[s.id] = [Page(page_index=j, printed_number=None, text=f"text {i}-{j}") for j in range(per)]
    return build_corpus(srcs, pages)


def _good_outline(total):
    half = total // 2
    return OutlineOut(
        parts=[
            PartOut(
                title="A",
                page_start=0,
                page_end=half - 1,
                sections=[SectionOut(title="a1", page_start=0, page_end=half - 1)],
            ),
            PartOut(
                title="B",
                page_start=half,
                page_end=total - 1,
                sections=[SectionOut(title="b1", page_start=half, page_end=total - 1)],
            ),
        ]
    )


def test_source_ranges():
    corpus = _corpus(6, sources=2)
    ranges = corpus.source_ranges()
    assert [(first, last) for _, first, last in ranges] == [(0, 2), (3, 5)]


def test_validate_outline_catches_range_and_order_errors():
    total = 6
    assert validate_outline(_good_outline(total), total) == []
    bad = OutlineOut(
        parts=[
            PartOut(
                title="A",
                page_start=0,
                page_end=9,
                sections=[SectionOut(title="x", page_start=0, page_end=1)],
            ),
            PartOut(
                title="B",
                page_start=0,
                page_end=2,
                sections=[SectionOut(title="y", page_start=5, page_end=2)],
            ),
        ]
    )
    errors = validate_outline(bad, total)
    assert any("page_end 9" in e for e in errors)
    assert any("before" in e or "order" in e for e in errors)
    assert any("section" in e and "outside" in e for e in errors)


def test_generate_outline_uses_cached_corpus_and_validates():
    corpus = _corpus(6)
    llm = FakeLLM({OutlineOut: lambda req: _good_outline(6)})
    out = generate_outline(llm, "fake-model", "Geo", corpus)
    assert [p.title for p in out.parts] == ["A", "B"]
    call = llm.calls[0]
    assert call.purpose == "gen.outline" and call.cached_context == corpus.render()
    assert "Geo" in call.system and "6 pages" in call.parts[0].text


def test_generate_outline_fails_after_retry():
    corpus = _corpus(6)
    bad = OutlineOut(
        parts=[
            PartOut(
                title="A",
                page_start=0,
                page_end=99,
                sections=[SectionOut(title="x", page_start=0, page_end=1)],
            )
        ]
    )
    llm = FakeLLM({OutlineOut: lambda req: bad})
    with pytest.raises(GenerationValidationError):
        generate_outline(llm, "fake-model", "Geo", corpus)
    assert len(llm.calls) == 2


def test_large_corpus_goes_per_source_then_merge(monkeypatch):
    import teachme.generation.outline as outline_module

    monkeypatch.setattr(outline_module, "LARGE_CORPUS_CHARS", 10)  # force the split path
    corpus = _corpus(6, sources=2)
    calls = []

    def responder(req):
        calls.append(req.purpose)
        if req.purpose == "gen.outline_source":
            first = int(req.parts[0].text.split("pages ")[1].split("-")[0])
            return OutlineOut(
                parts=[
                    PartOut(
                        title=f"P{first}",
                        page_start=first,
                        page_end=first + 2,
                        sections=[SectionOut(title="s", page_start=first, page_end=first + 2)],
                    )
                ]
            )
        return _good_outline(6)

    llm = FakeLLM({OutlineOut: responder})
    out = generate_outline(llm, "fake-model", "Geo", corpus)
    assert calls == ["gen.outline_source", "gen.outline_source", "gen.outline_merge"]
    assert len(out.parts) == 2
    assert LARGE_CORPUS_CHARS > 10  # module constant untouched outside the monkeypatch
