from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Question, QuestionKind
from teachme.grading.fake_responders import default_responders
from teachme.grading.relevance_check import check_relevance


def _question() -> Question:
    return Question(
        id=uuid4(),
        section_id=uuid4(),
        language="en",
        kind=QuestionKind.FREE_TEXT,
        prompt="How does evaporation move water into the atmosphere?",
        expected_answer="Heat from the sun turns liquid water into vapour that rises into the air.",
        rubric=("mentions heat", "mentions vapour"),
        key_terms=("evaporation",),
        exact_values=(),
    )


def _llm() -> FakeLLM:
    return FakeLLM(default_responders())


def test_fake_relevance_gate_rejects_an_answer_sharing_no_content_words_with_the_brief():
    """The fake gate used to always say on_topic, so nothing in the fake stack ever routed to a
    rejection. It must now behave like a (crude) real gate: no shared content words, off_topic."""
    verdict = check_relevance(
        _llm(), "fake-model", _question(), "I like football and watched the match last night.", "en"
    )
    assert verdict == "off_topic"


def test_fake_relevance_gate_accepts_an_answer_sharing_content_words_with_the_question_or_expected():
    verdict = check_relevance(
        _llm(), "fake-model", _question(), "Heat from the sun turns the water into vapour.", "en"
    )
    assert verdict == "on_topic"


def test_fake_relevance_gate_is_deterministic():
    llm = _llm()
    question = _question()
    first = check_relevance(llm, "fake-model", question, "Sunlight heats water into vapour.", "en")
    second = check_relevance(llm, "fake-model", question, "Sunlight heats water into vapour.", "en")
    assert first == second == "on_topic"
