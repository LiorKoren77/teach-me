from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import Chunk, Page
from teachme.ingestion.errors import CoverageError
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

CHUNK_MAX_TOKENS = 32000


class ChunkOut(BaseModel):
    context: str = Field(
        description="50-100 tokens situating the chunk within the source, in the source language"
    )
    original_text: str = Field(description="Verbatim text from the batch pages, unchanged")
    page_start: int = Field(ge=0, description="index attribute of the first page this text spans")
    page_end: int = Field(ge=0, description="index attribute of the last page this text spans")


class ChunksOut(BaseModel):
    chunks: list[ChunkOut]


def batch_pages(pages: Sequence[Page], pages_per_batch: int) -> list[list[Page]]:
    return [list(pages[i : i + pages_per_batch]) for i in range(0, len(pages), pages_per_batch)]


def render_pages(pages: Sequence[Page]) -> str:
    return "\n".join(
        f'<page index="{p.page_index}" printed="{p.printed_number or ""}">\n{p.text}\n</page>' for p in pages
    )


def validate_coverage(pages: Sequence[Page], chunks: Sequence[Chunk]) -> None:
    """Every page index must fall inside at least one chunk's page range."""
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.page_start, chunk.page_end + 1))
    missing = sorted(p.page_index for p in pages if p.page_index not in covered)
    if missing:
        raise CoverageError(f"pages not covered by any chunk: {missing}")


def contextualize(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    source_title: str,
    language: str | None,
    pages: Sequence[Page],
    pages_per_batch: int,
) -> list[Chunk]:
    system = load_prompt("contextualize").format(subject=subject_name, source=source_title)
    batches = batch_pages(pages, pages_per_batch)
    chunks: list[Chunk] = []
    for position, batch in enumerate(batches):
        before = batches[position - 1][-1:] if position > 0 else []
        after = batches[position + 1][:1] if position + 1 < len(batches) else []
        chunks.extend(_contextualize_batch(llm, model, system, language, batch, before, after))
    validate_coverage(pages, chunks)
    return chunks


def _contextualize_batch(
    llm: LLMProvider,
    model: str,
    system: str,
    language: str | None,
    batch: Sequence[Page],
    before: Sequence[Page],
    after: Sequence[Page],
) -> list[Chunk]:
    body = ""
    if before:
        body += f"<context_before>\n{render_pages(before)}\n</context_before>\n"
    body += f"<batch>\n{render_pages(batch)}\n</batch>\n"
    if after:
        body += f"<context_after>\n{render_pages(after)}\n</context_after>\n"
    body += f"\nThe source language is {language or 'unknown'}. Chunk every page inside <batch>."
    request = StructuredRequest(
        purpose="ingest.contextualize",
        model=model,
        system=system,
        parts=(ContentPart.of_text(body),),
        max_tokens=CHUNK_MAX_TOKENS,
        effort="medium",
    )
    output = llm.generate_structured(request, ChunksOut).output
    first, last = batch[0].page_index, batch[-1].page_index
    result: list[Chunk] = []
    for out in output.chunks:
        if out.page_start < first - 1:
            raise CoverageError(
                f"chunk page range ({out.page_start}, {out.page_end}) starts too far before batch "
                f"({first}, {last})"
            )
        if out.page_end > last + 1:
            raise CoverageError(
                f"chunk page range ({out.page_start}, {out.page_end}) ends too far after batch "
                f"({first}, {last})"
            )
        start = min(max(out.page_start, first), last)
        end = min(max(out.page_end, start), last)
        result.append(
            Chunk(context=out.context.strip(), text=out.original_text.strip(), page_start=start, page_end=end)
        )
    validate_coverage(batch, result)
    return result
