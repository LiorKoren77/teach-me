from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import Question, QuestionKind, RelevanceBand
from teachme.domain.relevance.junk import classify_junk
from teachme.domain.relevance.scorer import RelevanceThresholds, score_relevance


def _q(
    prompt="Why does the atmosphere protect the biosphere?",
    key_terms=("atmosphere", "biosphere", "radiation", "ultraviolet"),
    exact_values=(),
):
    return Question(
        id=uuid4(),
        section_id=uuid4(),
        language="en",
        kind=QuestionKind.FREE_TEXT,
        prompt=prompt,
        expected_answer="It absorbs ultraviolet radiation.",
        rubric=("absorbs UV",),
        key_terms=key_terms,
        exact_values=exact_values,
    )


VOCAB = frozenset(
    {"atmosphere", "biosphere", "ozone", "radiation", "ultraviolet", "absorbs", "layer", "protects"}
)


def test_classify_junk():
    assert classify_junk("", max_chars=1000) == "empty"
    assert classify_junk("   ", max_chars=1000) == "empty"
    assert classify_junk("x" * 1001, max_chars=1000) == "too_long"
    assert classify_junk("!!! ... ???", max_chars=1000) == "no_words"
    assert classify_junk("https://example.com/foo", max_chars=1000) == "url_only"
    assert classify_junk("aaaaaaaaaaaaaaaaaaaaaaaa", max_chars=1000) == "repeated"
    assert classify_junk("The ozone layer absorbs UV.", max_chars=1000) is None


def test_key_term_hits_and_topic_overlap_give_high_band():
    answer = "The atmosphere's ozone layer absorbs ultraviolet radiation before it reaches life."
    result = score_relevance(answer, _q(), VOCAB, "en")
    assert result.band == RelevanceBand.HIGH and result.score >= 0.5
    assert result.signals.key_term_hits >= 3 and result.signals.topic_overlap > 0.4


def test_off_topic_text_is_low():
    answer = "My favourite football team won the cup yesterday in the rain."
    result = score_relevance(answer, _q(), VOCAB, "en")
    assert result.band == RelevanceBand.LOW and result.signals.key_term_hits == 0


def test_exact_value_match_short_answer_is_high():
    q = _q(prompt="In which year?", key_terms=("year",), exact_values=("1789",))
    result = score_relevance("1789", q, VOCAB, "en")
    assert result.band == RelevanceBand.HIGH and result.signals.exact_value_hit


def test_short_answer_without_signals_is_uncertain_not_low():
    assert score_relevance("yes", _q(), VOCAB, "en").band == RelevanceBand.UNCERTAIN
    assert score_relevance("idk", _q(), VOCAB, "en").band == RelevanceBand.UNCERTAIN


def test_question_echo_counts_as_neutral():
    echo = score_relevance("Why does the atmosphere protect the biosphere?", _q(), VOCAB, "en")
    assert echo.signals.echo_ratio > 0.8
    assert echo.band != RelevanceBand.HIGH


def test_fuzzy_match_tolerates_inflection_and_typos():
    result = score_relevance("the atmospheric layers absorb ultra-violet radiations", _q(), VOCAB, "en")
    assert result.signals.key_term_hits >= 2


def test_hebrew_answer_with_source_language_term():
    q = Question(
        id=uuid4(),
        section_id=uuid4(),
        language="he",
        kind=QuestionKind.FREE_TEXT,
        prompt="מה מגן על הביוספרה?",
        expected_answer="האטמוספרה",
        rubric=("r",),
        key_terms=("אטמוספרה", "atmosfera", "ביוספרה"),
        exact_values=(),
    )
    result = score_relevance(
        "האטמוספרה מגנה על הביוספרה מקרינה", q, frozenset({"אטמוספרה", "ביוספרה", "קרינה"}), "he"
    )
    assert result.band == RelevanceBand.HIGH


def test_thresholds_are_configurable():
    strict = RelevanceThresholds(high=0.95, low=0.9)
    result = score_relevance("The atmosphere absorbs radiation.", _q(), VOCAB, "en", thresholds=strict)
    assert result.band in (RelevanceBand.UNCERTAIN, RelevanceBand.LOW)
