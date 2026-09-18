from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Frequency = Literal["first", "every", "never"]

PLACEHOLDER = re.compile(r"\{\{term:([a-z0-9][a-z0-9_-]*)\|([^{}|]+?)\}\}")


class GlossaryView(BaseModel):
    """What rendering needs: the source language and each slug's source-language term."""

    model_config = ConfigDict(frozen=True)

    source_language: str | None
    source_terms: dict[str, str]


def find_placeholders(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text)]


def render_placeholders(
    text: str, glossary: GlossaryView, *, target_language: str, frequency: Frequency
) -> str:
    """Replace `{{term:slug|words}}` with the words, followed by the source-language term in
    parentheses when teaching in a different language than the source. Unknown slugs render as
    their words alone; malformed placeholders are left as they are."""
    gloss = (
        frequency != "never"
        and glossary.source_language is not None
        and target_language != glossary.source_language
    )
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        slug, words = match.group(1), match.group(2)
        source_term = glossary.source_terms.get(slug)
        if not gloss or source_term is None:
            return words
        if frequency == "first" and slug in seen:
            return words
        seen.add(slug)
        return f"{words} ({source_term})"

    return PLACEHOLDER.sub(replace, text)
