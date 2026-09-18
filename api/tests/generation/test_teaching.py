from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm, Part, Section
from teachme.generation.prompts import load_prompt
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


def _good(body="x" * 300, page_refs=(0, 2)):
    return TeachingOut(
        title="מבוא",
        body_markdown=body,
        key_points=["a", "b", "c"],
        sections=[
            SectionContentOut(position=0, title="מה", summary="s"),
            SectionContentOut(position=1, title="למה", summary="s"),
        ],
        page_refs=list(page_refs),
    )


def test_validate_teaching():
    part, sections, terms = _structure()
    slugs = {t.slug for t in terms}
    assert validate_teaching(_good("{{term:biosphere|הביוספרה}} " + "x" * 300), part, sections, slugs) == []
    short = _good("tiny")
    assert any("too short" in e for e in validate_teaching(short, part, sections, slugs))
    missing_section = _good().model_copy(
        update={"sections": [SectionContentOut(position=0, title="t", summary="s")]}
    )
    assert any("sections" in e for e in validate_teaching(missing_section, part, sections, slugs))
    unknown = _good("{{term:ghost|x}} " + "x" * 300)
    assert any(
        "unknown glossary slug" in e and "ghost" in e
        for e in validate_teaching(unknown, part, sections, slugs)
    )


def test_validate_teaching_checks_page_refs_against_the_parts_range():
    part, sections, terms = _structure()  # the part covers global pages 0-3
    slugs = {t.slug for t in terms}
    body = "{{term:biosphere|הביוספרה}} " + "x" * 300
    assert validate_teaching(_good(body, page_refs=()), part, sections, slugs) == []
    assert validate_teaching(_good(body, page_refs=(3, 0)), part, sections, slugs) == []
    outside = validate_teaching(_good(body, page_refs=(1, 4)), part, sections, slugs)
    assert any("page_refs" in e and "4" in e and "0-3" in e for e in outside)
    below = validate_teaching(_good(body, page_refs=(-1,)), part, sections, slugs)
    assert any("page_refs" in e and "-1" in e for e in below)
    duplicated = validate_teaching(_good(body, page_refs=(1, 1)), part, sections, slugs)
    assert any("page_refs" in e and "duplicate" in e for e in duplicated)


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
    assert out.title == "מבוא" and out.page_refs == [0, 2]
    call = llm.calls[0]
    assert call.purpose == "gen.teaching" and call.cached_context == corpus.render()
    assert '"he"' in call.system and "Geo" in call.system
    assert "{{term:slug|words}}" in call.system  # survives .format() unescaped for the model to see


def test_generate_teaching_retries_when_page_refs_leave_the_part():
    part, sections, terms = _structure()
    corpus = _corpus(8)
    body = "{{term:biosphere|הביוספרה}} " + "y" * 300
    attempts = []

    def respond(req):
        attempts.append(req)
        return _good(body, page_refs=(7,) if len(attempts) == 1 else (1,))

    llm = FakeLLM({TeachingOut: respond})
    out = generate_teaching(
        llm, "fake-model", "Geo", "he", corpus, part, sections, terms, {"biosphere": "ביוספרה"}
    )
    assert len(attempts) == 2 and out.page_refs == [1]


def test_teaching_prompt_separates_printed_numbers_from_page_refs():
    prompt = load_prompt("teaching").format(subject="Geo", language='"he"')
    assert "{{term:slug|words}}" in prompt  # survives .format() unescaped
    assert "page_refs" in prompt and "printed" in prompt
