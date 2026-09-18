from __future__ import annotations

import re
import string
from uuid import uuid4

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Page, Source, SourceStatus
from teachme.generation.corpus import SubjectCorpus, build_corpus, dominant_language
from teachme.generation.errors import GenerationValidationError
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, StructuredRequest


def _source(name, n):
    return Source(
        id=uuid4(),
        subject_id=uuid4(),
        filename=name,
        media_type="application/pdf",
        file_key="k",
        size=1,
        status=SourceStatus.READY,
        page_count=n,
        detected_language="pt",
    )


def test_prompts_exist():
    for name in ("outline", "outline_merge", "glossary", "glossary_translate", "teaching", "questions"):
        assert len(load_prompt(name)) > 100


def test_prompt_placeholders_survive_formatting():
    """Every prompt is passed through str.format(); any brace that isn't one of the known
    named fields must be doubled so it survives as a literal single brace (e.g. the glossary
    placeholder syntax {{term:slug|words}} shown to the model)."""
    allowed_fields = {"subject", "language", "count"}
    dummy = {"subject": "Subj", "language": '"he"', "count": 5}
    for name in ("outline", "outline_merge", "glossary", "glossary_translate", "teaching", "questions"):
        text = load_prompt(name)
        fields = {
            field_name for _, field_name, _, _ in string.Formatter().parse(text) if field_name is not None
        }
        assert fields <= allowed_fields, f"{name}.md: unexpected format field(s) {fields - allowed_fields}"
        rendered = text.format(**dummy)
        # A single, un-doubled "{term" (not part of a literal "{{term") means .format() collapsed
        # the placeholder's escaped braces down to one.
        assert re.search(r"(?<!\{)\{term", rendered) is None, (
            f"{name}.md: placeholder collapsed to a single brace after format()"
        )


def test_corpus_renders_sources_in_order_with_global_page_indices():
    a, b = _source("a.pdf", 2), _source("b.pdf", 1)
    pages = {
        a.id: [
            Page(page_index=0, printed_number="1", text="A0"),
            Page(page_index=1, printed_number="2", text="A1"),
        ],
        b.id: [Page(page_index=0, printed_number=None, text="B0")],
    }
    corpus = build_corpus([a, b], pages)
    assert isinstance(corpus, SubjectCorpus)
    assert corpus.total_pages == 3
    assert corpus.language == "pt"
    text = corpus.render()
    assert text.index('<source name="a.pdf"') < text.index('<source name="b.pdf"')
    assert '<page index="2" printed="">' in text and "B0" in text.split('index="2"')[1]
    assert corpus.page_text(2) == "B0" and corpus.page_text(1) == "A1"
    assert corpus.locate(2) == (b.id, 0)
    assert corpus.render() == corpus.render()  # byte-identical: safe to cache


def test_corpus_language_is_majority_of_sources():
    a, b, c = _source("a", 1), _source("b", 1), _source("c", 1)
    b = b.model_copy(update={"detected_language": "he"})
    c = c.model_copy(update={"detected_language": "he"})
    pages = {s.id: [Page(page_index=0, printed_number=None, text="x")] for s in (a, b, c)}
    assert build_corpus([a, b, c], pages).language == "he"
    assert dominant_language([a, b, c]) == "he"
    assert dominant_language([a]) == "pt"
    assert dominant_language([a.model_copy(update={"detected_language": None})]) is None
    assert dominant_language([]) is None


def test_corpus_render_escapes_source_name_and_printed_number():
    a = _source('a"b&c.pdf', 1)
    pages = {a.id: [Page(page_index=0, printed_number='3"&4', text="X")]}
    text = build_corpus([a], pages).render()
    assert '<source name="a&quot;b&amp;c.pdf">' in text
    assert 'printed="3&quot;&amp;4"' in text
    assert 'name="a"b&c.pdf"' not in text
    assert 'printed="3"&4"' not in text


def test_page_text_and_locate_raise_indexerror_out_of_range():
    a = _source("a.pdf", 2)
    pages = {
        a.id: [
            Page(page_index=0, printed_number=None, text="A0"),
            Page(page_index=1, printed_number=None, text="A1"),
        ]
    }
    corpus = build_corpus([a], pages)
    for bad in (-1, 2, 100):
        with pytest.raises(IndexError):
            corpus.page_text(bad)
        with pytest.raises(IndexError):
            corpus.locate(bad)


def test_build_corpus_tolerates_source_missing_from_pages_by_source():
    a, b = _source("a.pdf", 1), _source("b.pdf", 1)
    pages = {a.id: [Page(page_index=0, printed_number=None, text="A0")]}
    corpus = build_corpus([a, b], pages)  # b has no entry in pages
    assert corpus.total_pages == 1
    assert corpus.page_text(0) == "A0"


class Out(BaseModel):
    n: int


def _req(text="go"):
    return StructuredRequest(purpose="gen.test", model="m", system="s", parts=(ContentPart.of_text(text),))


def test_generate_validated_retries_once_with_errors_appended():
    attempts = []

    def responder(req):
        attempts.append(req.parts[-1].text)
        return Out(n=len(attempts))

    llm = FakeLLM({Out: responder})
    result = generate_validated(llm, _req(), Out, validate=lambda out: [] if out.n == 2 else ["n must be 2"])
    assert result.output.n == 2
    assert len(attempts) == 2 and "n must be 2" in attempts[1] and "Previous attempt" in attempts[1]


def test_generate_validated_fails_after_second_invalid_output():
    llm = FakeLLM({Out: lambda req: Out(n=0)})
    with pytest.raises(GenerationValidationError) as info:
        generate_validated(llm, _req(), Out, validate=lambda out: ["still wrong"])
    assert "still wrong" in str(info.value) and len(llm.calls) == 2
