from __future__ import annotations

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

    def page_text(self, global_index: int) -> str:
        return self.pages[global_index].text

    def locate(self, global_index: int) -> tuple[UUID, int]:
        page = self.pages[global_index]
        return page.source_id, page.page_index

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
                out.append(f'<source name="{page.source_name}">')
                current = page.source_id
            printed = page.printed_number or ""
            out.append(f'<page index="{page.global_index}" printed="{printed}">\n{page.text}\n</page>')
        if current is not None:
            out.append("</source>")
        return "\n".join(out)


def build_corpus(sources: Sequence[Source], pages_by_source: Mapping[UUID, Sequence[Page]]) -> SubjectCorpus:
    corpus_pages: list[CorpusPage] = []
    for source in sources:
        for page in sorted(pages_by_source[source.id], key=lambda p: p.page_index):
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
    languages = Counter(s.detected_language for s in sources if s.detected_language)
    language = languages.most_common(1)[0][0] if languages else None
    return SubjectCorpus(pages=tuple(corpus_pages), language=language)
