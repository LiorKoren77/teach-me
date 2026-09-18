from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder
from teachme.domain.text.normalize import normalize, tokenize
from teachme.grading.grader import GradeOut
from teachme.grading.relevance_check import RelevanceVerdict
from teachme.grading.sanitize import TAG
from teachme.ports.llm import StructuredRequest

_ANSWER = re.compile(rf"<{TAG}>(.*?)</{TAG}>", re.DOTALL)
_WORD = re.compile(r"\w{3,}", re.UNICODE)
_CORRECT_RATIO = 0.5
"""Half the expected answer's content words is enough for `correct`; anything above none is
`partial`. Arbitrary, but fixed: the fake grader has to be reproducible above all."""


def _user_text(request: StructuredRequest) -> str:
    return "\n".join(p.text or "" for p in request.parts if p.kind == "text")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(normalize(text)))


def _line(text: str, label: str) -> str:
    match = re.search(rf"^{label}: (.*)$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _answer(text: str) -> str:
    match = _ANSWER.search(text)
    return match.group(1) if match else ""


def _grade(request: StructuredRequest) -> BaseModel:
    """Word overlap with the expected answer stands in for a grader: no judgement, but the same
    answer always earns the same verdict, and a better answer never scores worse."""
    text = _user_text(request)
    expected = _words(_line(text, "EXPECTED"))
    covered = expected & _words(_answer(text))
    ratio = len(covered) / len(expected) if expected else 0.0
    verdict = "correct" if ratio >= _CORRECT_RATIO else "partial" if ratio > 0 else "incorrect"
    rubric = [int(m.group(1)) for m in re.finditer(r"^RUBRIC (\d+):", text, re.MULTILINE)]
    return GradeOut(
        verdict=verdict,
        rubric_covered=rubric if verdict == "correct" else rubric[:1] if verdict == "partial" else [],
        missed_concepts=[] if verdict == "correct" else ["fake missed concept"],
        feedback=f"Fake grading: {len(covered)} of {len(expected)} expected words present.",
    )


def _relevance(request: StructuredRequest) -> BaseModel:
    """Deterministic but meaningful, unlike a gate that always waves an answer through: off_topic
    when the answer shares no content word - by the same tokenizer and stopword lists the real
    lexical scorer uses - with the question or the expected answer in the brief, on_topic
    otherwise. This is not a judgement of correctness - that is the grader's job - only of
    whether the answer is an attempt at this question at all, which is exactly what the real
    check is asked to gate. A test that wants a specific verdict installs its own responder."""
    text = _user_text(request)
    language = _line(text, "LANGUAGE") or "en"
    question_words = tokenize(_line(text, "QUESTION"), language)
    expected_words = tokenize(_line(text, "EXPECTED"), language)
    reference = set(question_words) | set(expected_words)
    overlap = reference & set(tokenize(_answer(text), language))
    return RelevanceVerdict(verdict="on_topic" if overlap else "off_topic")


def default_responders() -> dict[type[BaseModel], Responder]:
    return {GradeOut: _grade, RelevanceVerdict: _relevance}
