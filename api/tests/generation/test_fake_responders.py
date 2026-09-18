from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm
from teachme.generation.fake_responders import _questions, default_responders
from teachme.generation.glossary import generate_glossary, translate_glossary
from teachme.generation.outline import generate_outline, validate_outline
from teachme.generation.question_bank import generate_question_bank, validate_bank
from teachme.generation.teaching import generate_teaching
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
from teachme.ports.llm import ContentPart, StructuredRequest
from tests.generation.test_outline import _corpus
from tests.generation.test_teaching import _good, _structure


def test_generation_responders_drive_every_schema_and_validate():
    llm = FakeLLM({**ingestion_responders(), **default_responders()})
    corpus = _corpus(6)
    outline = generate_outline(llm, "fake-model", "Geo", corpus)
    assert outline.parts and all(p.sections for p in outline.parts)
    assert outline.parts[-1].page_end == 5

    glossary = generate_glossary(llm, "fake-model", "Geo", corpus)
    assert len(glossary.terms) >= 2

    terms = [
        GlossaryTerm(
            id=uuid4(),
            outline_id=uuid4(),
            slug=t.slug,
            source_term=t.term,
            definition=t.definition,
            pages=tuple(t.pages),
        )
        for t in glossary.terms
    ]
    translated = translate_glossary(llm, "fake-model", "he", terms)
    assert {t.slug for t in translated.translations} == {t.slug for t in terms}

    part, sections, _ = _structure()
    teaching = generate_teaching(
        llm, "fake-model", "Geo", "he", corpus, part, sections, terms, {t.slug: f"he-{t.slug}" for t in terms}
    )
    assert "{{term:" in teaching.body_markdown and len(teaching.sections) == 2

    bank = generate_question_bank(
        llm,
        "fake-model",
        "Geo",
        "he",
        corpus,
        part,
        sections,
        teaching,
        terms,
        {t.slug: f"he-{t.slug}" for t in terms},
        count=5,
    )
    assert validate_bank(bank, sections, {t.slug for t in terms}, min_per_section=2) == []


def test_question_responder_keeps_every_section_covered_when_count_is_tight():
    """count <= 2 * n_sections used to steal a question from the last section by overwriting
    index -1 with the multiple-choice question, dropping that section below min_per_section."""
    llm = FakeLLM({**ingestion_responders(), **default_responders()})
    corpus = _corpus(6)
    part, sections, terms = _structure()
    teaching = _good()
    bank = generate_question_bank(
        llm, "fake-model", "Geo", "he", corpus, part, sections, teaching, terms, {}, count=4
    )
    assert validate_bank(bank, sections, {t.slug for t in terms}, min_per_section=2) == []


def test_outline_responder_dispatches_on_purpose_for_large_corpus_merge(monkeypatch):
    """gen.outline_merge used to sniff the user text for the all-pages/page-range phrases, which
    the merge prompt never contains, crashing with AttributeError on a None regex match."""
    import teachme.generation.outline as outline_module

    monkeypatch.setattr(outline_module, "LARGE_CORPUS_CHARS", 10)  # force the per-source-then-merge path
    llm = FakeLLM({**ingestion_responders(), **default_responders()})
    corpus = _corpus(12, sources=3)
    out = generate_outline(llm, "fake-model", "Geo", corpus)
    purposes = [call.purpose for call in llm.calls if call.purpose.startswith("gen.outline")]
    assert purposes == ["gen.outline_source", "gen.outline_source", "gen.outline_source", "gen.outline_merge"]
    assert validate_outline(out, corpus.total_pages) == []


def test_question_responder_requires_section_lines():
    request = StructuredRequest(
        purpose="gen.questions", model="m", system="s", parts=(ContentPart.of_text("COUNT: 4"),)
    )
    with pytest.raises(ValueError, match="no SECTION lines"):
        _questions(request)
