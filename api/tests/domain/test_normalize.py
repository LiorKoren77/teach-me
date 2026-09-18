from __future__ import annotations

from teachme.domain.text.normalize import normalize, tokenize


def test_normalize_lowercases_and_strips_hebrew_points():
    assert normalize("Ａtmosphere") == "atmosphere"
    assert normalize("בְּרֵאשִׁית") == "בראשית"


def test_tokenize_english_removes_stopwords():
    assert tokenize("The biosphere and the atmosphere", "en") == ["biosphere", "atmosphere"]


def test_tokenize_keeps_numbers_and_short_words():
    assert tokenize("In 1789 the map", "en") == ["1789", "map"]


def test_tokenize_hebrew_keeps_bare_and_prefixed_forms_overlapping():
    # Different prefixed forms of the same word must share at least one token so they match at query time.
    bare = set(tokenize("ביוספרה", "he"))
    prefixed = set(tokenize("והביוספרה", "he"))
    assert bare & prefixed
    assert "ביוספרה" in bare
    assert "ביוספרה" in prefixed
    # short words are left alone so real words like "הר" are not mangled
    assert tokenize("הר", "he") == ["הר"]


def test_tokenize_portuguese_keeps_accents():
    assert tokenize("A atmosfera é composta", "pt") == ["atmosfera", "composta"]


def test_tokenize_unknown_language_falls_back_to_no_stopwords():
    assert tokenize("the map", "xx") == ["the", "map"]


def test_tokenize_hebrew_keeps_maqaf_as_a_word_separator():
    # U+05BE (maqaf) is Hebrew punctuation, not a vowel point; it must split words, not fuse them.
    tokens = tokenize("בית־ספר", "he")
    assert len(tokens) == 2
    assert "בית" in tokens
    assert "ביתספר" not in tokens


def test_tokenize_hebrew_joins_gershayim_abbreviation():
    # Gershayim (U+05F4) marks an abbreviation/acronym; it must not split the word in two.
    assert "תנך" in tokenize("תנ״ך", "he")


def test_tokenize_english_joins_apostrophe_contraction():
    assert tokenize("don't stop", "en") == ["dont", "stop"]
