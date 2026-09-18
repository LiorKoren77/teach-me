from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from teachme.domain.glossary.render import GlossaryView, render_placeholders
from teachme.domain.models import ChunkHit, Grade, Question
from teachme.grading.prompts import load_prompt
from teachme.grading.sanitize import as_student_data
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

GRADE_MAX_TOKENS = 1500


class GradeOut(BaseModel):
    verdict: Literal["correct", "partial", "incorrect", "off_topic"]
    rubric_covered: list[int] = Field(description="Indices of rubric points the answer covers")
    missed_concepts: list[str] = Field(description="Short phrases for what the student missed")
    feedback: str = Field(
        min_length=1, description="One or two sentences for the student, without the full answer"
    )


class GradeResult(BaseModel):
    grade: Grade
    rubric_covered: tuple[int, ...]
    missed_concepts: tuple[str, ...]
    feedback: str


def render_for_grader(text: str, view: GlossaryView, language: str) -> str:
    return render_placeholders(text, view, target_language=language, frequency="every")


def grade_answer(
    llm: LLMProvider,
    model: str,
    question: Question,
    answer: str,
    language: str,
    glossary: GlossaryView,
    evidence: Sequence[ChunkHit],
) -> GradeResult:
    """One graded answer: the rubric, the glossary and the retrieved extracts are all the grader
    sees, so a verdict can always be traced back to the material."""
    lines = [
        f"QUESTION: {render_for_grader(question.prompt, glossary, language)}",
        f"EXPECTED: {render_for_grader(question.expected_answer, glossary, language)}",
    ]
    lines += [f"RUBRIC {i}: {point}" for i, point in enumerate(question.rubric)]
    # the key terms and values a correct answer turns on, so the grader can credit a student who
    # used the source-language form instead of the translation
    if question.key_terms:
        rendered = (render_for_grader(term, glossary, language) for term in question.key_terms)
        lines.append("KEY TERMS: " + ", ".join(rendered))
    if question.exact_values:
        lines.append("EXACT VALUES: " + ", ".join(question.exact_values))
    lines += [f"GLOSSARY: {slug} = {term}" for slug, term in sorted(glossary.source_terms.items())]
    lines.append("EVIDENCE:")
    lines += [
        f'<extract pages="{h.page_start}-{h.page_end}">\n{h.content}\n</extract>' for h in evidence
    ] or ["(none retrieved)"]
    lines.append("\n" + as_student_data(answer))
    request = StructuredRequest(
        purpose="learn.grade",
        model=model,
        system=load_prompt("grader").format(language=language),
        parts=(ContentPart.of_text("\n".join(lines)),),
        max_tokens=GRADE_MAX_TOKENS,
        effort="medium",
    )
    out = llm.generate_structured(request, GradeOut).output
    valid = tuple(i for i in out.rubric_covered if 0 <= i < len(question.rubric))
    return GradeResult(
        grade=Grade(out.verdict),
        rubric_covered=valid,
        missed_concepts=tuple(out.missed_concepts),
        feedback=out.feedback.strip(),
    )
