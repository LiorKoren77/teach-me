from __future__ import annotations

import pytest

from teachme.domain.languages import LANGUAGES, get_language


def test_three_languages_registered():
    assert set(LANGUAGES) == {"he", "en", "pt"}


def test_hebrew_is_rtl_with_prefixes():
    he = get_language("he")
    assert he.direction == "rtl"
    assert "ו" in he.prefixes and "ה" in he.prefixes
    assert "של" in he.stopwords


def test_english_and_portuguese_are_ltr():
    assert get_language("en").direction == "ltr"
    assert get_language("pt").direction == "ltr"
    assert "the" in get_language("en").stopwords
    assert "de" in get_language("pt").stopwords


def test_unknown_code_raises():
    with pytest.raises(KeyError):
        get_language("xx")
