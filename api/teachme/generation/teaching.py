from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from teachme.domain.glossary.render import find_placeholders
from teachme.domain.models import GlossaryTerm, Part, Section
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

TEACHING_MAX_TOKENS = 24000
MIN_BODY_CHARS = 200


class SectionContentOut(BaseModel):
    position: int = Field(ge=0, description="The section position given in the brief")
    title: str = Field(description="Localized section title")
    summary: str = Field(description="One paragraph a later step can use to re-explain this section alone")


class TeachingOut(BaseModel):
    title: str = Field(description="Localized part title")
    body_markdown: str = Field(description="Teaching text with {{term:slug|words}} placeholders")
    key_points: list[str] = Field(min_length=3, max_length=6)
    sections: list[SectionContentOut]
    page_refs: list[int] = Field(
        default_factory=list,
        description=(
            "Global page indices (the corpus `index` attribute, not the printed number) of the"
            " pages whose figures, maps or tables the text tells the student to look at. Empty"
            " when the text points at none."
        ),
    )


def validate_teaching(
    out: TeachingOut, part: Part, sections: Sequence[Section], slugs: set[str]
) -> list[str]:
    errors: list[str] = []
    if len(out.body_markdown.strip()) < MIN_BODY_CHARS:
        errors.append(f"body_markdown too short ({len(out.body_markdown.strip())} chars)")
    expected = sorted(s.position for s in sections)
    got = sorted(s.position for s in out.sections)
    if got != expected:
        errors.append(f"sections must cover positions {expected} exactly once, got {got}")
    for slug, _ in find_placeholders(out.body_markdown):
        if slug not in slugs:
            errors.append(f"unknown glossary slug {slug!r} in body_markdown")
    # page_refs address the page-image route, so an index outside the part is a page the student
    # would be shown by mistake, not a stylistic slip: it fails the attempt and buys the retry.
    outside = sorted({i for i in out.page_refs if not part.page_start <= i <= part.page_end})
    if outside:
        errors.append(
            f"page_refs {outside} outside the part's page range {part.page_start}-{part.page_end};"
            " use the global page index of a page this part covers"
        )
    duplicates = sorted({i for i in out.page_refs if out.page_refs.count(i) > 1})
    if duplicates:
        errors.append(f"page_refs has duplicate entries {duplicates}; list every page at most once")
    return errors


def render_brief(
    part: Part,
    sections: Sequence[Section],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    language: str,
) -> str:
    """The user message: what to teach, where it is, and which terms to wrap. The part's own pages
    are named by the PAGES line, not re-sent here - they are already in the cached corpus (see
    cached_context in generate_teaching), so repeating them would pay uncached input price for
    text the model already has. Machine-readable line prefixes (PART, PAGES, SECTION n, TERM) are
    relied on by the fake responders."""
    lines = [
        f"PART: {part.title}",
        f"PAGES: {part.page_start}-{part.page_end}",
        f"LANGUAGE: {language}",
    ]
    lines += [f"SECTION {s.position}: {s.title} (pages {s.page_start}-{s.page_end})" for s in sections]
    lines += [f"TERM: {t.slug} | {t.source_term} | {translations.get(t.slug, t.source_term)}" for t in terms]
    return "\n".join(lines)


def generate_teaching(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    language: str,
    corpus: SubjectCorpus,
    part: Part,
    sections: Sequence[Section],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
) -> TeachingOut:
    request = StructuredRequest(
        purpose="gen.teaching",
        model=model,
        system=load_prompt("teaching").format(subject=subject_name, language=f'"{language}"'),
        parts=(ContentPart.of_text(render_brief(part, sections, terms, translations, language)),),
        cached_context=corpus.render(),
        max_tokens=TEACHING_MAX_TOKENS,
        effort="high",
    )
    slugs = {t.slug for t in terms}
    out = generate_validated(
        llm, request, TeachingOut, validate=lambda out: validate_teaching(out, part, sections, slugs)
    ).output
    # Validation already refused out-of-range and duplicate indices; sorting is only so the stored
    # order is the reading order of the pages rather than the order the model happened to mention them.
    return out.model_copy(update={"page_refs": sorted(out.page_refs)})
