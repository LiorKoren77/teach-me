from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder
from teachme.domain.models import QuestionKind
from teachme.generation.glossary import GlossaryOut, GlossaryTranslationOut, TermOut, TranslationOut
from teachme.generation.outline import OutlineOut, PartOut, SectionOut
from teachme.generation.question_bank import QuestionBankOut, QuestionOut
from teachme.generation.teaching import SectionContentOut, TeachingOut
from teachme.ports.llm import StructuredRequest

_ALL_PAGES = re.compile(r"all (\d+) pages")
_PAGE_RANGE = re.compile(r"pages (\d+)-(\d+)")
_SECTION = re.compile(r"^SECTION (\d+): (.+?) \(pages (\d+)-(\d+)\)$", re.MULTILINE)
_TERM = re.compile(r"^TERM: ([a-z0-9-]+) \| ([^|]+?) \| (.+)$", re.MULTILINE)
_COUNT = re.compile(r"^COUNT: (\d+)$", re.MULTILINE)


def _user_text(request: StructuredRequest) -> str:
    return "\n".join(p.text or "" for p in request.parts if p.kind == "text")


def _outline(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    if match := _ALL_PAGES.search(text):
        first, last = 0, int(match.group(1)) - 1
    else:
        rng = _PAGE_RANGE.search(text)
        first, last = int(rng.group(1)), int(rng.group(2))
    parts = []
    start = first
    while start <= last:
        end = min(start + 2, last)
        mid = (start + end) // 2
        sections = [SectionOut(title=f"Section {start}", page_start=start, page_end=mid)]
        if mid < end:
            sections.append(SectionOut(title=f"Section {mid + 1}", page_start=mid + 1, page_end=end))
        parts.append(PartOut(title=f"Part {start}-{end}", page_start=start, page_end=end, sections=sections))
        start = end + 1
    return OutlineOut(parts=parts)


def _glossary(request: StructuredRequest) -> BaseModel:
    total = int(_ALL_PAGES.search(_user_text(request)).group(1))
    return GlossaryOut(
        terms=[
            TermOut(slug="biosphere", term="biosfera", definition="Fake definition one.", pages=[0]),
            TermOut(
                slug="atmosphere",
                term="atmosfera",
                definition="Fake definition two.",
                pages=[min(1, total - 1)],
            ),
        ]
    )


def _translate(request: StructuredRequest) -> BaseModel:
    slugs = [m.group(1) for m in _TERM.finditer(_user_text(request))]
    return GlossaryTranslationOut(translations=[TranslationOut(slug=s, term=f"tr-{s}") for s in slugs])


def _teaching(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    sections = [(int(m.group(1)), m.group(2)) for m in _SECTION.finditer(text)]
    slugs = [m.group(1) for m in _TERM.finditer(text)]
    placeholder = f"{{{{term:{slugs[0]}|fake-words}}}}" if slugs else ""
    body = f"# Fake teaching\n\n{placeholder} " + "Fake teaching sentence. " * 30
    return TeachingOut(
        title="Fake part title",
        body_markdown=body,
        key_points=["point 1", "point 2", "point 3"],
        sections=[
            SectionContentOut(position=pos, title=f"Fake {title}", summary="Fake summary.")
            for pos, title in sections
        ],
    )


def _questions(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    positions = [int(m.group(1)) for m in _SECTION.finditer(text)]
    if not positions:
        raise ValueError("no SECTION lines in the question brief")
    count = int(_COUNT.search(text).group(1))
    slugs = [m.group(1) for m in _TERM.finditer(text)]
    placeholder = f" {{{{term:{slugs[0]}|fake-words}}}}" if slugs else ""
    questions: list[QuestionOut] = []
    target = max(count, 2 * len(positions))
    while len(questions) < target:
        for pos in positions:
            questions.append(
                QuestionOut(
                    section_position=pos,
                    kind=QuestionKind.FREE_TEXT,
                    prompt=f"Fake question {len(questions)}{placeholder}?",
                    expected_answer="Fake expected answer.",
                    rubric=["fake point"],
                    key_terms=["fake"],
                    exact_values=[],
                )
            )
    if questions:
        # Replace question 0, not the last one: it already belongs to positions[0], so
        # swapping it in for the multiple-choice question leaves every section's count unchanged.
        questions[0] = QuestionOut(
            section_position=positions[0],
            kind=QuestionKind.MULTIPLE_CHOICE,
            prompt="Fake choice question?",
            expected_answer="B",
            rubric=["fake"],
            key_terms=[],
            exact_values=[],
            choices=["A", "B", "C", "D"],
            correct_choice=1,
        )
    return QuestionBankOut(questions=questions)


def default_responders() -> dict[type[BaseModel], Responder]:
    return {
        OutlineOut: _outline,
        GlossaryOut: _glossary,
        GlossaryTranslationOut: _translate,
        TeachingOut: _teaching,
        QuestionBankOut: _questions,
    }
