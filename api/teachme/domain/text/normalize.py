from __future__ import annotations

import re
import unicodedata

from teachme.domain.languages import LANGUAGES

_HEBREW_POINTS = re.compile(r"[֑-ׇ]")  # niqqud and cantillation marks
_WORD = re.compile(r"\w+", re.UNICODE)
_MIN_LEN_FOR_PREFIX_STRIP = 4
_MIN_LEN_AFTER_STRIP = 3
_MAX_PREFIX_STRIPS = 2


def normalize(text: str) -> str:
    """NFKC fold, lowercase, drop Hebrew vowel points. Keeps letters of every script and digits."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return _HEBREW_POINTS.sub("", folded)


def tokenize(text: str, language_code: str) -> list[str]:
    """Content words for lexical indexing and relevance scoring.

    Shared by the pgvector lexical column and the answer-relevance scorer so both sides
    agree on what a token is. Unknown language codes tokenize without stopword removal.
    """
    language = LANGUAGES.get(language_code)
    stopwords = language.stopwords if language else frozenset()
    prefixes = language.prefixes if language else ()
    tokens: list[str] = []
    for raw in _WORD.findall(normalize(text)):
        for variant in _prefix_variants(raw, prefixes):
            if variant in stopwords:
                continue
            tokens.append(variant)
    return tokens


def _prefix_variants(token: str, prefixes: tuple[str, ...]) -> list[str]:
    """The raw token plus up to two progressive one-letter clitic strips.

    Hebrew clitics (ו ה ב ל מ ש כ) stack at the front of a word, so the same underlying
    word can appear as e.g. ביוספרה, הביוספרה, or והביוספרה. Emitting every prefix-stripped
    form as a token lets those variants share a token for lexical matching.
    """
    variants = [token]
    remainder = token
    for _ in range(_MAX_PREFIX_STRIPS):
        if len(remainder) < _MIN_LEN_FOR_PREFIX_STRIP or remainder[0] not in prefixes:
            break
        remainder = remainder[1:]
        if len(remainder) < _MIN_LEN_AFTER_STRIP:
            break
        variants.append(remainder)
    return variants
