from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from teachme.domain.models import Question
from teachme.grading.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

Verdict = Literal["on_topic", "off_topic", "unclear"]

RELEVANCE_MAX_TOKENS = 256


class RelevanceVerdict(BaseModel):
    verdict: Verdict = Field(description="on_topic, off_topic or unclear")


def check_relevance(llm: LLMProvider, model: str, question: Question, answer: str, language: str) -> Verdict:
    """The cheap gate in front of the grader: is this an attempt at the question at all?"""
    body = (
        f"LANGUAGE: {language}\nQUESTION: {question.prompt}\nEXPECTED: {question.expected_answer}\n\n"
        f"<student_answer>\n{answer}\n</student_answer>"
    )
    request = StructuredRequest(
        purpose="learn.relevance_check",
        model=model,
        system=load_prompt("relevance_check"),
        parts=(ContentPart.of_text(body),),
        max_tokens=RELEVANCE_MAX_TOKENS,
        effort="low",
    )
    return llm.generate_structured(request, RelevanceVerdict).output.verdict
