from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

from teachme.domain.glossary.render import find_placeholders
from teachme.domain.models import GlossaryTerm, Part, Question, QuestionKind, Section
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.teaching import TeachingOut
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

QUESTIONS_MAX_TOKENS = 24000
MC_CHOICES = 4


class QuestionOut(BaseModel):
    section_position: int = Field(ge=0, description="Position of the section this question tests")
    kind: QuestionKind
    prompt: str = Field(description="The question, with glossary placeholders")
    expected_answer: str = Field(description="Two or three sentences")
    rubric: list[str] = Field(min_length=1, max_length=4, description="Points a correct answer must cover")
    key_terms: list[str] = Field(description="Terms a genuine attempt would contain, with synonyms")
    exact_values: list[str] = Field(
        default_factory=list, description="Dates, numbers, names for factual questions"
    )
    choices: list[str] | None = Field(default=None, description="Exactly four for multiple_choice, else null")
    correct_choice: int | None = Field(default=None, description="Index into choices for multiple_choice")


class QuestionBankOut(BaseModel):
    questions: list[QuestionOut]


def validate_bank(
    out: QuestionBankOut, sections: Sequence[Section], slugs: set[str], *, min_per_section: int
) -> list[str]:
    errors: list[str] = []
    positions = {s.position for s in sections}
    per_section = {p: 0 for p in positions}
    has_mc = False
    for i, q in enumerate(out.questions):
        if q.section_position not in positions:
            errors.append(f"question {i}: unknown section position {q.section_position}")
        else:
            per_section[q.section_position] += 1
        if q.kind == QuestionKind.MULTIPLE_CHOICE:
            has_mc = True
            if not q.choices or len(q.choices) != MC_CHOICES:
                errors.append(f"question {i}: multiple_choice needs exactly {MC_CHOICES} choices")
            if q.correct_choice is None or not q.choices or not 0 <= q.correct_choice < len(q.choices):
                errors.append(f"question {i}: correct_choice must index into choices")
        elif q.choices is not None or q.correct_choice is not None:
            errors.append(f"question {i}: free_text must not have choices")
        for text in (q.prompt, q.expected_answer):
            for slug, _ in find_placeholders(text):
                if slug not in slugs:
                    errors.append(f"question {i}: unknown glossary slug {slug!r}")
    for position, count in sorted(per_section.items()):
        if count < min_per_section:
            errors.append(f"section {position}: has {count} questions, needs at least {min_per_section}")
    if out.questions and not has_mc:
        errors.append("include at least one multiple_choice question")
    return errors


def augment_key_terms(
    q: QuestionOut, source_terms: Mapping[str, str], target_terms: Mapping[str, str]
) -> tuple[str, ...]:
    """Key terms plus the source- and target-language forms of every glossary term the question uses,
    so a student writing either form scores as on-topic."""
    terms = list(q.key_terms)
    for slug, _ in find_placeholders(q.prompt + " " + q.expected_answer):
        for candidate in (source_terms.get(slug), target_terms.get(slug)):
            if candidate and candidate not in terms:
                terms.append(candidate)
    return tuple(terms)


def to_questions(
    out: QuestionBankOut,
    sections: Sequence[Section],
    language: str,
    source_terms: Mapping[str, str],
    target_terms: Mapping[str, str],
) -> list[Question]:
    by_position = {s.position: s.id for s in sections}
    questions = []
    for i, q in enumerate(out.questions):
        if q.section_position not in by_position:
            raise ValueError(
                f"question {i}: unknown section position {q.section_position}; expected one of"
                f" {sorted(by_position)}"
            )
        questions.append(
            Question(
                id=uuid4(),
                section_id=by_position[q.section_position],
                language=language,
                kind=q.kind,
                prompt=q.prompt,
                expected_answer=q.expected_answer,
                rubric=tuple(q.rubric),
                key_terms=augment_key_terms(q, source_terms, target_terms),
                exact_values=tuple(q.exact_values),
                choices=tuple(q.choices) if q.choices else None,
                correct_choice=q.correct_choice,
                position=i,
            )
        )
    return questions


def render_brief(
    part: Part,
    sections: Sequence[Section],
    teaching: TeachingOut,
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    count: int,
) -> str:
    lines = [
        f"PART: {part.title}",
        f"PAGES: {part.page_start}-{part.page_end}",
        f"COUNT: {count}",
    ]
    lines += [f"SECTION {s.position}: {s.title} (pages {s.page_start}-{s.page_end})" for s in sections]
    lines += [f"TERM: {t.slug} | {t.source_term} | {translations.get(t.slug, t.source_term)}" for t in terms]
    lines += ["", "TEACHING:", teaching.body_markdown]
    return "\n".join(lines)


def generate_question_bank(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    language: str,
    corpus: SubjectCorpus,
    part: Part,
    sections: Sequence[Section],
    teaching: TeachingOut,
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    *,
    count: int,
    min_per_section: int = 2,
) -> QuestionBankOut:
    request = StructuredRequest(
        purpose="gen.questions",
        model=model,
        system=load_prompt("questions").format(subject=subject_name, language=f'"{language}"', count=count),
        parts=(ContentPart.of_text(render_brief(part, sections, teaching, terms, translations, count)),),
        cached_context=corpus.render(),
        max_tokens=QUESTIONS_MAX_TOKENS,
        effort="high",
    )
    slugs = {t.slug for t in terms}
    return generate_validated(
        llm,
        request,
        QuestionBankOut,
        validate=lambda out: validate_bank(out, sections, slugs, min_per_section=min_per_section),
    ).output
