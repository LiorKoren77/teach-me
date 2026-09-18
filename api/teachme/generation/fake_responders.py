from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder, TextResponder
from teachme.domain.models import QuestionKind
from teachme.generation.glossary import GlossaryOut, GlossaryTranslationOut, TermOut, TranslationOut
from teachme.generation.outline import OutlineOut, PartOut, SectionOut
from teachme.generation.question_bank import QuestionBankOut, QuestionOut
from teachme.generation.teaching import SectionContentOut, TeachingOut
from teachme.ports.llm import StructuredRequest, TextRequest

_ALL_PAGES = re.compile(r"all (\d+) pages")
_PAGE_RANGE = re.compile(r"pages (\d+)-(\d+)")
_SECTION = re.compile(r"^SECTION (\d+): (.+?) \(pages (\d+)-(\d+)\)$", re.MULTILINE)
_TERM = re.compile(r"^TERM: ([a-z0-9-]+) \| ([^|]+?) \| (.+)$", re.MULTILINE)
_COUNT = re.compile(r"^COUNT: (\d+)$", re.MULTILINE)


def _user_text(request: StructuredRequest) -> str:
    return "\n".join(p.text or "" for p in request.parts if p.kind == "text")


def _outline(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    if request.purpose == "gen.outline_merge":
        partials = _parse_partial_outlines(text)
        last = max(part.page_end for partial in partials for part in partial.parts)
        return _build_outline(0, last)
    if request.purpose == "gen.outline_source":
        match = _PAGE_RANGE.search(text)
        if match is None:
            raise ValueError("gen.outline_source: no page range in the outline brief")
        first, last = int(match.group(1)), int(match.group(2))
    elif request.purpose == "gen.outline":
        match = _ALL_PAGES.search(text)
        if match is None:
            raise ValueError("gen.outline: no page count in the outline brief")
        first, last = 0, int(match.group(1)) - 1
    else:
        raise ValueError(f"_outline: unsupported purpose {request.purpose!r}")
    return _build_outline(first, last)


def _build_outline(first: int, last: int) -> OutlineOut:
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


def _parse_partial_outlines(text: str) -> list[OutlineOut]:
    """The gen.outline_merge user text is "Partial outlines in source order:" followed by each
    partial's OutlineOut JSON, blank-line separated (plus, on a retry, validation feedback text
    appended the same way) - so parse every blank-line-separated chunk that is valid JSON and
    ignore the rest."""
    partials = []
    for chunk in re.split(r"\n\n+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            partials.append(OutlineOut.model_validate_json(chunk))
        except ValueError:
            continue
    if not partials:
        raise ValueError("gen.outline_merge: no partial outlines found in the merge brief")
    return partials


def _glossary(request: StructuredRequest) -> BaseModel:
    match = _ALL_PAGES.search(_user_text(request))
    if match is None:
        raise ValueError("gen.glossary: no page count in the glossary brief")
    total = int(match.group(1))
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
    count_match = _COUNT.search(text)
    if count_match is None:
        raise ValueError("gen.questions: no COUNT line in the question brief")
    count = int(count_match.group(1))
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


def default_text_responder() -> TextResponder:
    """The one free-text call in the app is the re-explanation; the fake one re-teaches nothing
    but is shaped like the real thing, so the loop runs to the end without an API key."""

    def respond(request: TextRequest) -> str:
        sections = [m.group(2) for m in _SECTION.finditer("\n".join(p.text or "" for p in request.parts))]
        titles = sections or ["this part"]
        body = "\n\n".join(f"## Again: {title}\n\nFake re-explanation sentence. " * 3 for title in titles)
        return f"{body}\n"

    return respond


def default_responders() -> dict[type[BaseModel], Responder]:
    return {
        OutlineOut: _outline,
        GlossaryOut: _glossary,
        GlossaryTranslationOut: _translate,
        TeachingOut: _teaching,
        QuestionBankOut: _questions,
    }
