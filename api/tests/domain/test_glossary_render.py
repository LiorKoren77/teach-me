from __future__ import annotations

from teachme.domain.glossary.render import GlossaryView, find_placeholders, render_placeholders

GLOSSARY = GlossaryView(
    source_language="pt",
    source_terms={"biosphere": "biosfera", "atmosphere": "atmosfera"},
)

TEXT = (
    "{{term:biosphere|הביוספרה}} היא חלק. {{term:atmosphere|האטמוספרה}} גם. שוב {{term:biosphere|ביוספרה}}."
)


def test_find_placeholders_returns_slug_and_words_in_order():
    assert find_placeholders(TEXT) == [
        ("biosphere", "הביוספרה"),
        ("atmosphere", "האטמוספרה"),
        ("biosphere", "ביוספרה"),
    ]


def test_first_occurrence_glossed_when_languages_differ():
    out = render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="first")
    assert out == "הביוספרה (biosfera) היא חלק. האטמוספרה (atmosfera) גם. שוב ביוספרה."


def test_every_occurrence():
    out = render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="every")
    assert out.count("(biosfera)") == 2


def test_never_and_same_language_render_words_only():
    assert (
        render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="never")
        == "הביוספרה היא חלק. האטמוספרה גם. שוב ביוספרה."
    )
    assert "(" not in render_placeholders(TEXT, GLOSSARY, target_language="pt", frequency="first")


def test_unknown_slug_keeps_words_and_is_reported():
    text = "{{term:ghost|רוח}} here"
    assert render_placeholders(text, GLOSSARY, target_language="he", frequency="first") == "רוח here"
    assert find_placeholders(text) == [("ghost", "רוח")]


def test_malformed_placeholder_is_left_untouched():
    text = "{{term:nopipe}} and {{other:x|y}}"
    assert render_placeholders(text, GLOSSARY, target_language="he", frequency="first") == text
