from __future__ import annotations

from pydantic import BaseModel, Field

from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

OUTLINE_MAX_TOKENS = 16000
# Above this many rendered characters (roughly 600k tokens) the outline is produced per source and
# merged, so a very large subject still fits one model call at a time.
LARGE_CORPUS_CHARS = 2_500_000


class SectionOut(BaseModel):
    title: str = Field(description="Short title in the source language; one idea")
    page_start: int = Field(ge=0, description="Global page index of the first page")
    page_end: int = Field(ge=0, description="Global page index of the last page")


class PartOut(BaseModel):
    title: str = Field(description="Short title in the source language")
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)
    sections: list[SectionOut] = Field(min_length=1, description="2 to 6 sections, in reading order")


class OutlineOut(BaseModel):
    parts: list[PartOut] = Field(min_length=1, description="Parts in reading order; 3 to 6 for a chapter")


def validate_outline(out: OutlineOut, total_pages: int) -> list[str]:
    errors: list[str] = []
    last_end = -1
    for i, part in enumerate(out.parts):
        if part.page_end < part.page_start:
            errors.append(
                f"part {i} '{part.title}': page_end {part.page_end} before page_start {part.page_start}"
            )
        if part.page_end >= total_pages:
            errors.append(
                f"part {i} '{part.title}': page_end {part.page_end} exceeds last page index {total_pages - 1}"
            )
        if part.page_start < last_end:
            errors.append(
                f"part {i} '{part.title}': starts at {part.page_start},"
                f" out of order with the previous part ending {last_end}"
            )
        last_end = max(last_end, part.page_end)
        for j, section in enumerate(part.sections):
            if section.page_end < section.page_start:
                errors.append(f"part {i} section {j}: page_end before page_start")
            # Both ends must sit inside the part, so a section that starts past the part's last
            # page (or ends before its first) is caught too, not only one that overhangs an edge.
            if not (
                part.page_start <= section.page_start <= part.page_end
                and part.page_start <= section.page_end <= part.page_end
            ):
                errors.append(
                    f"part {i} section {j} '{section.title}':"
                    f" pages {section.page_start}-{section.page_end}"
                    f" outside the part's range {part.page_start}-{part.page_end}"
                )
    return errors


def generate_outline(llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus) -> OutlineOut:
    rendered = corpus.render()
    if len(rendered) <= LARGE_CORPUS_CHARS:
        request = StructuredRequest(
            purpose="gen.outline",
            model=model,
            system=load_prompt("outline").format(subject=subject_name),
            parts=(
                ContentPart.of_text(f"Design the outline for all {corpus.total_pages} pages of the corpus."),
            ),
            cached_context=rendered,
            max_tokens=OUTLINE_MAX_TOKENS,
            effort="high",
        )
        return generate_validated(
            llm, request, OutlineOut, validate=lambda out: validate_outline(out, corpus.total_pages)
        ).output
    return _outline_per_source_then_merge(llm, model, subject_name, corpus)


def _outline_per_source_then_merge(
    llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus
) -> OutlineOut:
    partials: list[OutlineOut] = []
    system = load_prompt("outline").format(subject=subject_name)
    for _, first, last in corpus.source_ranges():
        request = StructuredRequest(
            purpose="gen.outline_source",
            model=model,
            system=system,
            parts=(
                ContentPart.of_text(
                    f"Design the outline for pages {first}-{last} only."
                    " Use these global page indices.\n\n" + corpus.render(first, last)
                ),
            ),
            max_tokens=OUTLINE_MAX_TOKENS,
            effort="high",
        )
        partial = generate_validated(
            llm,
            request,
            OutlineOut,
            # first/last are bound as defaults so each validator keeps its own source's range.
            validate=lambda out, first=first, last=last: _validate_within(out, first, last),
        ).output
        partials.append(partial)
    merge_request = StructuredRequest(
        purpose="gen.outline_merge",
        model=model,
        system=load_prompt("outline_merge").format(subject=subject_name),
        parts=(
            ContentPart.of_text(
                "Partial outlines in source order:\n\n"
                + "\n\n".join(p.model_dump_json(indent=2) for p in partials)
            ),
        ),
        max_tokens=OUTLINE_MAX_TOKENS,
        effort="high",
    )
    return generate_validated(
        llm,
        merge_request,
        OutlineOut,
        validate=lambda out: validate_outline(out, corpus.total_pages),
    ).output


def _validate_within(out: OutlineOut, first: int, last: int) -> list[str]:
    errors = validate_outline(out, last + 1)
    for i, part in enumerate(out.parts):
        if part.page_start < first:
            errors.append(f"part {i} starts before page {first}")
    return errors
