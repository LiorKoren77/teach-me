from __future__ import annotations

import html
from collections import Counter
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import Page, Source


class CorpusPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    global_index: int
    source_id: UUID
    source_name: str
    page_index: int
    printed_number: str | None
    text: str


class SubjectCorpus(BaseModel):
    """Every page of every ready source, in source order, with global page indices.
    render() is deterministic so the result can be a cached prompt prefix."""

    model_config = ConfigDict(frozen=True)

    pages: tuple[CorpusPage, ...]
    language: str | None

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    def _page_at(self, global_index: int) -> CorpusPage:
        if not 0 <= global_index < self.total_pages:
            raise IndexError(
                f"global page index {global_index} out of range for corpus of {self.total_pages} pages"
            )
        return self.pages[global_index]

    def page_text(self, global_index: int) -> str:
        return self._page_at(global_index).text

    def locate(self, global_index: int) -> tuple[UUID, int]:
        page = self._page_at(global_index)
        return page.source_id, page.page_index

    def source_ranges(self) -> list[tuple[UUID, int, int]]:
        """(source_id, first_global_index, last_global_index) per source, in order."""
        ranges: list[tuple[UUID, int, int]] = []
        for page in self.pages:
            if ranges and ranges[-1][0] == page.source_id:
                ranges[-1] = (page.source_id, ranges[-1][1], page.global_index)
            else:
                ranges.append((page.source_id, page.global_index, page.global_index))
        return ranges

    def render(self, first: int | None = None, last: int | None = None) -> str:
        """Pages [first, last] (inclusive, global) grouped by source. Defaults to everything."""
        first = 0 if first is None else first
        last = self.total_pages - 1 if last is None else last
        out: list[str] = []
        current: UUID | None = None
        for page in self.pages[first : last + 1]:
            if page.source_id != current:
                if current is not None:
                    out.append("</source>")
                out.append(f'<source name="{html.escape(page.source_name, quote=True)}">')
                current = page.source_id
            printed = html.escape(page.printed_number, quote=True) if page.printed_number else ""
            out.append(f'<page index="{page.global_index}" printed="{printed}">\n{page.text}\n</page>')
        if current is not None:
            out.append("</source>")
        return "\n".join(out)


def dominant_language(sources: Sequence[Source]) -> str | None:
    """The language most of a subject's sources were detected in, or None when none is known.
    This is the corpus language: what glossary terms are in, and what rendering glosses from."""
    languages = Counter(source.detected_language for source in sources if source.detected_language)
    return languages.most_common(1)[0][0] if languages else None


def build_corpus(sources: Sequence[Source], pages_by_source: Mapping[UUID, Sequence[Page]]) -> SubjectCorpus:
    corpus_pages: list[CorpusPage] = []
    for source in sources:
        for page in sorted(pages_by_source.get(source.id, ()), key=lambda p: p.page_index):
            corpus_pages.append(
                CorpusPage(
                    global_index=len(corpus_pages),
                    source_id=source.id,
                    source_name=source.filename,
                    page_index=page.page_index,
                    printed_number=page.printed_number,
                    text=page.text,
                )
            )
    return SubjectCorpus(pages=tuple(corpus_pages), language=dominant_language(sources))
