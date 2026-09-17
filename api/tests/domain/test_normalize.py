from __future__ import annotations

from teachme.domain.text.normalize import normalize, tokenize


def test_normalize_lowercases_and_strips_hebrew_points():
    assert normalize("Ａtmosphere") == "atmosphere"
    assert normalize("בְּרֵאשִׁית") == "בראשית"


def test_tokenize_english_removes_stopwords():
    assert tokenize("The biosphere and the atmosphere", "en") == ["biosphere", "atmosphere"]


def test_tokenize_keeps_numbers_and_short_words():
    assert tokenize("In 1789 the map", "en") == ["1789", "map"]


def test_tokenize_hebrew_strips_one_prefix_from_long_words():
    # והביוספרה -> strip ו -> הביוספרה (one prefix only, deterministic)
    assert tokenize("והביוספרה", "he") == ["הביוספרה"]
    # short words are left alone so real words like "הר" are not mangled
    assert tokenize("הר", "he") == ["הר"]


def test_tokenize_portuguese_keeps_accents():
    assert tokenize("A atmosfera é composta", "pt") == ["atmosfera", "composta"]


def test_tokenize_unknown_language_falls_back_to_no_stopwords():
    assert tokenize("the map", "xx") == ["the", "map"]
