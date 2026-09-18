from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm
from teachme.generation.glossary import (
    GlossaryOut,
    GlossaryTranslationOut,
    TermOut,
    TranslationOut,
    generate_glossary,
    translate_glossary,
    validate_glossary,
    validate_translations,
)
from tests.generation.test_outline import _corpus


def test_validate_glossary_slugs_unique_and_pages_in_range():
    good = GlossaryOut(terms=[TermOut(slug="biosphere", term="biosfera", definition="d", pages=[0, 1])])
    assert validate_glossary(good, total_pages=3) == []
    bad = GlossaryOut(
        terms=[
            TermOut(slug="a", term="x", definition="d", pages=[7]),
            TermOut(slug="a", term="y", definition="d", pages=[]),
            TermOut(slug="c", term="", definition="d", pages=[0]),
        ]
    )
    errors = validate_glossary(bad, total_pages=3)
    assert any("duplicate slug" in e for e in errors)
    assert any("page 7" in e for e in errors)
    assert any("empty term" in e for e in errors)


def test_generate_glossary_uses_cached_corpus():
    corpus = _corpus(4)
    llm = FakeLLM(
        {GlossaryOut: lambda req: GlossaryOut(terms=[TermOut(slug="t", term="T", definition="d", pages=[0])])}
    )
    out = generate_glossary(llm, "fake-model", "Geo", corpus)
    assert out.terms[0].slug == "t"
    assert llm.calls[0].purpose == "gen.glossary" and llm.calls[0].cached_context == corpus.render()
    # Same effort as every other call sharing this cached corpus prefix (outline/teaching/questions),
    # so the cached prefix is never invalidated by a differing effort level.
    assert llm.calls[0].effort == "high"


def test_translate_glossary_validates_full_coverage():
    terms = [
        GlossaryTerm(
            id=uuid4(),
            outline_id=uuid4(),
            slug="biosphere",
            source_term="biosfera",
            definition="d",
            pages=(0,),
        ),
        GlossaryTerm(
            id=uuid4(),
            outline_id=uuid4(),
            slug="atmosphere",
            source_term="atmosfera",
            definition="d",
            pages=(1,),
        ),
    ]
    complete = GlossaryTranslationOut(
        translations=[
            TranslationOut(slug="biosphere", term="ביוספרה"),
            TranslationOut(slug="atmosphere", term="אטמוספרה"),
        ]
    )
    assert validate_translations(complete, {"biosphere", "atmosphere"}) == []
    partial = GlossaryTranslationOut(
        translations=[
            TranslationOut(slug="biosphere", term="ביוספרה"),
            TranslationOut(slug="ghost", term="x"),
        ]
    )
    errors = validate_translations(partial, {"biosphere", "atmosphere"})
    assert any("missing" in e and "atmosphere" in e for e in errors)
    assert any("unknown slug" in e and "ghost" in e for e in errors)

    llm = FakeLLM({GlossaryTranslationOut: lambda req: complete})
    out = translate_glossary(llm, "fake-model", "he", terms)
    assert {t.slug: t.term for t in out.translations}["atmosphere"] == "אטמוספרה"
    call = llm.calls[0]
    assert call.purpose == "gen.glossary_translate" and call.cached_context is None
    assert "TERM: biosphere | biosfera | d" in call.parts[0].text and "he" in call.system
