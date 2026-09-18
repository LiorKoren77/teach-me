from __future__ import annotations

from pydantic import BaseModel, Field

from teachme.domain.models import Figure, Page
from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

READ_MAX_TOKENS = 32000


class ReadFigure(BaseModel):
    kind: str = Field(description="One of: map, diagram, chart, photo, illustration, table, other")
    caption: str = Field(description="The caption exactly as printed; empty string if none")
    description: str = Field(description="Two to four sentences on what the figure shows and what to notice")


class ReadPage(BaseModel):
    page_offset: int = Field(ge=0, description="0 for the first page of this fragment, 1 for the second, ...")
    printed_number: str | None = Field(description="Page number printed on the page, or null")
    text_markdown: str = Field(description="Complete page text as Markdown in the original language")
    figures: list[ReadFigure]


class ReadPagesOutput(BaseModel):
    pages: list[ReadPage]


def format_figure_block(figure: ReadFigure) -> str:
    label = figure.caption.strip() or figure.kind
    return f"\n\n> **[Figure: {label}]** {figure.description.strip()}\n"


def read_pdf_batch(
    llm: LLMProvider, model: str, batch: PdfBatch, language_hint: str | None
) -> tuple[list[Page], list[Figure]]:
    parts = (
        ContentPart.of_document(batch.data, "application/pdf"),
        ContentPart.of_text(_instruction(batch.page_count, language_hint)),
    )
    return _read(llm, model, parts, first_index=batch.first_index, expected=batch.page_count)


def read_image(
    llm: LLMProvider,
    model: str,
    data: bytes,
    media_type: str,
    page_index: int,
    language_hint: str | None = None,
) -> tuple[list[Page], list[Figure]]:
    parts = (ContentPart.of_image(data, media_type), ContentPart.of_text(_instruction(1, language_hint)))
    return _read(llm, model, parts, first_index=page_index, expected=1)


def _instruction(page_count: int, language_hint: str | None) -> str:
    language = language_hint or "unknown"
    return (
        f"This fragment contains exactly {page_count} pages. The document language is probably {language}. "
        "Transcribe every page and list its figures."
    )


def _read(
    llm: LLMProvider, model: str, parts: tuple[ContentPart, ...], *, first_index: int, expected: int
) -> tuple[list[Page], list[Figure]]:
    request = StructuredRequest(
        purpose="ingest.read_pages",
        model=model,
        system=load_prompt("read_pages"),
        parts=parts,
        max_tokens=READ_MAX_TOKENS,
        effort="medium",
    )
    output = llm.generate_structured(request, ReadPagesOutput).output
    offsets = sorted(p.page_offset for p in output.pages)
    if offsets != list(range(expected)):
        raise ExtractionError(f"expected pages 0..{expected - 1}, model returned offsets {offsets}")

    pages: list[Page] = []
    figures: list[Figure] = []
    for read_page in sorted(output.pages, key=lambda p: p.page_offset):
        index = first_index + read_page.page_offset
        text = read_page.text_markdown.rstrip()
        for ordinal, figure in enumerate(read_page.figures):
            text += format_figure_block(figure)
            figures.append(
                Figure(
                    page_index=index,
                    ordinal=ordinal,
                    kind=figure.kind,
                    caption=figure.caption,
                    description=figure.description,
                )
            )
        pages.append(Page(page_index=index, printed_number=read_page.printed_number, text=text))
    return pages, figures
