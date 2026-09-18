from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm, Part, Section
from teachme.generation.teaching import (
    SectionContentOut,
    TeachingOut,
    generate_teaching,
    render_brief,
    validate_teaching,
)
from tests.generation.test_outline import _corpus


def _structure():
    outline_id, part_id = uuid4(), uuid4()
    part = Part(id=part_id, outline_id=outline_id, position=0, title="Intro", page_start=0, page_end=3)
    sections = [
        Section(id=uuid4(), part_id=part_id, position=0, title="What", page_start=0, page_end=1),
        Section(id=uuid4(), part_id=part_id, position=1, title="Why", page_start=2, page_end=3),
    ]
    terms = [
        GlossaryTerm(
            id=uuid4(),
            outline_id=outline_id,
            slug="biosphere",
            source_term="biosfera",
            definition="d",
            pages=(0,),
        )
    ]
    return part, sections, terms


def _good(body="x" * 300):
    return TeachingOut(
        title="מבוא",
        body_markdown=body,
        key_points=["a", "b", "c"],
        sections=[
            SectionContentOut(position=0, title="מה", summary="s"),
            SectionContentOut(position=1, title="למה", summary="s"),
        ],
    )


def test_validate_teaching():
    part, sections, terms = _structure()
    slugs = {t.slug for t in terms}
    assert validate_teaching(_good("{{term:biosphere|הביוספרה}} " + "x" * 300), sections, slugs) == []
    short = _good("tiny")
    assert any("too short" in e for e in validate_teaching(short, sections, slugs))
    missing_section = _good().model_copy(
        update={"sections": [SectionContentOut(position=0, title="t", summary="s")]}
    )
    assert any("sections" in e for e in validate_teaching(missing_section, sections, slugs))
    unknown = _good("{{term:ghost|x}} " + "x" * 300)
    assert any(
        "unknown glossary slug" in e and "ghost" in e for e in validate_teaching(unknown, sections, slugs)
    )


def test_render_brief_lists_sections_and_glossary_and_pages():
    part, sections, terms = _structure()
    brief = render_brief(part, sections, terms, {"biosphere": "ביוספרה"}, "he")
    assert "PART: Intro" in brief and "PAGES: 0-3" in brief
    assert "SECTION 0: What (pages 0-1)" in brief and "SECTION 1: Why (pages 2-3)" in brief
    assert "TERM: biosphere | biosfera | ביוספרה" in brief
    # The part's pages aren't re-sent in the brief - they're read from the cached corpus by the
    # global page indices the PAGES line already gives, not repeated here at uncached price.
    assert "<page index=" not in brief
    assert '<page index="3"' in _corpus(4).render()


def test_generate_teaching_uses_cached_corpus_and_language():
    part, sections, terms = _structure()
    corpus = _corpus(4)
    llm = FakeLLM({TeachingOut: lambda req: _good("{{term:biosphere|הביוספרה}} " + "y" * 300)})
    out = generate_teaching(
        llm, "fake-model", "Geo", "he", corpus, part, sections, terms, {"biosphere": "ביוספרה"}
    )
    assert out.title == "מבוא"
    call = llm.calls[0]
    assert call.purpose == "gen.teaching" and call.cached_context == corpus.render()
    assert '"he"' in call.system and "Geo" in call.system
    assert "{{term:slug|words}}" in call.system  # survives .format() unescaped for the model to see
