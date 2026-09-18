from __future__ import annotations

import re

_URL = re.compile(r"^\s*(https?://\S+|www\.\S+)\s*$", re.IGNORECASE)
_WORD = re.compile(r"\w", re.UNICODE)
_REPEAT = re.compile(r"^(.)\1{7,}$")


def classify_junk(answer: str, *, max_chars: int) -> str | None:
    """Model-free rejection reasons; None means the answer deserves scoring."""
    stripped = answer.strip()
    if not stripped:
        return "empty"
    if len(stripped) > max_chars:
        return "too_long"
    if _URL.match(stripped):
        return "url_only"
    if not _WORD.search(stripped):
        return "no_words"
    compact = re.sub(r"\s+", "", stripped)
    if _REPEAT.match(compact):
        return "repeated"
    return None
