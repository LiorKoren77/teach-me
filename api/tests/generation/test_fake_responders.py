from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm
from teachme.generation.fake_responders import default_responders
from teachme.generation.glossary import generate_glossary, translate_glossary
from teachme.generation.outline import generate_outline
from teachme.generation.question_bank import generate_question_bank, validate_bank
from teachme.generation.teaching import generate_teaching
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
from tests.generation.test_outline import _corpus
from tests.generation.test_teaching import _structure


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
