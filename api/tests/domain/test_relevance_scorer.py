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


def _score(answer, question=None, vocabulary=None, language="en", **kwargs):
    return score_relevance(
        answer,
        question or _q(),
        section_vocabulary=vocabulary if vocabulary is not None else VOCAB,
        language_code=language,
        **kwargs,
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
    result = _score(answer)
    assert result.band == RelevanceBand.HIGH and result.score >= 0.5
    assert result.signals.key_term_hits >= 3 and result.signals.topic_overlap > 0.4


def test_off_topic_text_is_low():
    answer = "My favourite football team won the cup yesterday in the rain."
    result = _score(answer)
    assert result.band == RelevanceBand.LOW and result.signals.key_term_hits == 0


def test_exact_value_match_short_answer_is_high():
    q = _q(prompt="In which year?", key_terms=("year",), exact_values=("1789",))
    result = _score("1789", q)
    assert result.band == RelevanceBand.HIGH and result.signals.exact_value_hit


def test_exact_value_does_not_match_inside_a_longer_number():
    q = _q(prompt="In which year?", key_terms=("year",), exact_values=("1789",))
    assert not _score("the register counted 17890 households that spring", q).signals.exact_value_hit
    assert _score("it happened in 1789, right after the harvest", q).signals.exact_value_hit


def test_short_answer_without_signals_is_uncertain_not_low():
    assert _score("yes").band == RelevanceBand.UNCERTAIN
    assert _score("idk").band == RelevanceBand.UNCERTAIN


def test_question_echo_counts_as_neutral():
    echo = _score("Why does the atmosphere protect the biosphere?")
    assert echo.signals.echo_ratio > 0.8
    assert echo.band != RelevanceBand.HIGH


def test_fuzzy_match_tolerates_inflection_and_typos():
    result = _score("the atmospheric layers absorb ultra-violet radiations")
    assert result.signals.key_term_hits >= 2


def test_fuzzy_match_tolerates_dropped_diacritics():
    q = _q(prompt="O que absorve a radiacao?", key_terms=("radiação",), exact_values=())
    assert _score("a radiacao ultravioleta e absorvida pela camada", q, language="pt").signals.key_term_hits
    q_plain = _q(prompt="O que absorve a radiacao?", key_terms=("radiacao",), exact_values=())
    assert _score(
        "a radiação ultravioleta e absorvida pela camada", q_plain, language="pt"
    ).signals.key_term_hits


def test_a_shared_stem_is_not_a_key_term_hit():
    """The prefix rule used to accept any five shared characters, which made a key term match
    an unrelated word that merely starts the same way."""
    protein = _q(prompt="What carries the signal?", key_terms=("protein",))
    assert _score("the cell protects itself from outside damage", protein).signals.key_term_hits == 0
    photosynthesis = _q(prompt="How does a leaf feed itself?", key_terms=("photosynthesis",))
    assert _score("i took a photograph of the leaf in the garden", photosynthesis).signals.key_term_hits == 0


def test_a_short_key_term_does_not_match_inside_a_longer_word():
    ion = _q(prompt="What carries the charge?", key_terms=("ion",))
    assert _score("a nation builds its own railway network", ion).signals.key_term_hits == 0
    assert _score("the ion moves towards the negative plate", ion).signals.key_term_hits == 1


def test_a_multi_word_key_term_matches_its_words_in_any_order():
    q = _q(prompt="What absorbs ultraviolet light?", key_terms=("ozone layer",))
    assert _score("a layer of ozone high above the ground absorbs it").signals.key_term_hits == 0
    assert _score("a layer of ozone high above the ground absorbs it", q).signals.key_term_hits == 1
    assert _score("the ozone layer absorbs it", q).signals.key_term_hits == 1


def test_two_word_off_topic_answers_land_in_the_same_band_in_any_language():
    """The Hebrew tokenizer emits a prefix-stripped variant per word, so counting tokens made a
    two-word Hebrew answer look long enough to judge while the English one did not."""
    hebrew = Question(
        id=uuid4(),
        section_id=uuid4(),
        language="he",
        kind=QuestionKind.FREE_TEXT,
        prompt="מה מגן על הביוספרה?",
        expected_answer="האטמוספרה",
        rubric=("r",),
        key_terms=("אטמוספרה", "ביוספרה"),
        exact_values=(),
    )
    he = _score("הכדורגל והפיצה", hebrew, frozenset({"אטמוספרה", "ביוספרה"}), language="he")
    en = _score("football pizza")
    assert he.band == en.band == RelevanceBand.UNCERTAIN


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
    result = _score(
        "האטמוספרה מגנה על הביוספרה מקרינה",
        q,
        frozenset({"אטמוספרה", "ביוספרה", "קרינה"}),
        language="he",
    )
    assert result.band == RelevanceBand.HIGH


def test_thresholds_are_configurable():
    strict = RelevanceThresholds(high=0.95, low=0.9)
    result = _score("The atmosphere absorbs radiation.", thresholds=strict)
    assert result.band in (RelevanceBand.UNCERTAIN, RelevanceBand.LOW)
