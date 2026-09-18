from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import GlossaryTerm
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

GLOSSARY_MAX_TOKENS = 16000
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class TermOut(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN, description="lowercase ascii, digits and hyphens; unique")
    term: str = Field(description="The term as written in the source language, dictionary form")
    definition: str = Field(description="One sentence in the source language")
    pages: list[int] = Field(description="Global page indices where the term is introduced")


class GlossaryOut(BaseModel):
    terms: list[TermOut]


class TranslationOut(BaseModel):
    slug: str
    term: str = Field(description="The standard target-language term, dictionary form")


class GlossaryTranslationOut(BaseModel):
    translations: list[TranslationOut]


def validate_glossary(out: GlossaryOut, total_pages: int) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for term in out.terms:
        if term.slug in seen:
            errors.append(f"duplicate slug {term.slug!r}")
        seen.add(term.slug)
        if not term.term.strip():
            errors.append(f"slug {term.slug!r}: empty term")
        for page in term.pages:
            if page < 0 or page >= total_pages:
                errors.append(f"slug {term.slug!r}: page {page} outside 0-{total_pages - 1}")
    return errors


def validate_translations(out: GlossaryTranslationOut, slugs: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for tr in out.translations:
        if tr.slug not in slugs:
            errors.append(f"unknown slug {tr.slug!r}")
        elif tr.slug in seen:
            errors.append(f"duplicate translation for {tr.slug!r}")
        if not tr.term.strip():
            errors.append(f"slug {tr.slug!r}: empty translation")
        seen.add(tr.slug)
    for slug in sorted(slugs - seen):
        errors.append(f"missing translation for {slug!r}")
    return errors


def generate_glossary(llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus) -> GlossaryOut:
    request = StructuredRequest(
        purpose="gen.glossary",
        model=model,
        system=load_prompt("glossary").format(subject=subject_name),
        parts=(ContentPart.of_text(f"Extract the key terminology from all {corpus.total_pages} pages."),),
        cached_context=corpus.render(),
        max_tokens=GLOSSARY_MAX_TOKENS,
        # Every call that shares the cached corpus prefix (outline, glossary, teaching, questions)
        # must use the same effort level; providers key their prompt cache on the full request
        # including effort, so a differing value here would silently miss the cache and re-pay for
        # the whole corpus. translate_glossary has no cached context, so it is free to use "low".
        effort="high",
    )
    return generate_validated(
        llm, request, GlossaryOut, validate=lambda out: validate_glossary(out, corpus.total_pages)
    ).output


def render_terms(terms: Sequence[GlossaryTerm]) -> str:
    return "\n".join(f"TERM: {t.slug} | {t.source_term} | {t.definition}" for t in terms)


def translate_glossary(
    llm: LLMProvider, model: str, language: str, terms: Sequence[GlossaryTerm]
) -> GlossaryTranslationOut:
    request = StructuredRequest(
        purpose="gen.glossary_translate",
        model=model,
        system=load_prompt("glossary_translate").format(language=language),
        parts=(ContentPart.of_text(render_terms(terms)),),
        max_tokens=8000,
        effort="low",
    )
    slugs = {t.slug for t in terms}
    return generate_validated(
        llm,
        request,
        GlossaryTranslationOut,
        validate=lambda out: validate_translations(out, slugs),
    ).output
