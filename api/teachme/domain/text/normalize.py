from __future__ import annotations

import re
import unicodedata

from teachme.domain.languages import LANGUAGES

_HEBREW_POINTS = re.compile(r"[֑-ׇ]")  # niqqud and cantillation marks
_WORD = re.compile(r"\w+", re.UNICODE)
_MIN_LEN_FOR_PREFIX_STRIP = 4


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
        if raw in stopwords:
            continue
        token = _strip_prefix(raw, prefixes)
        if token in stopwords:
            continue
        tokens.append(token)
    return tokens


def _strip_prefix(token: str, prefixes: tuple[str, ...]) -> str:
    if len(token) >= _MIN_LEN_FOR_PREFIX_STRIP and token[0] in prefixes:
        return token[1:]
    return token
