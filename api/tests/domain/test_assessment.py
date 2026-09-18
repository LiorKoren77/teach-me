from __future__ import annotations

import random
from uuid import uuid4

import pytest

from teachme.domain.assessment.sampling import sample_round
from teachme.domain.assessment.scoring import round_score, weak_sections
from teachme.domain.assessment.transitions import IllegalTransition, after_round, assert_transition
from teachme.domain.models import (
    AttemptQuestion,
    Grade,
    PartStatus,
    Question,
    QuestionKind,
    RelevanceBand,
    Route,
)
from teachme.domain.relevance.router import route_for_band


def test_router():
    assert route_for_band(RelevanceBand.JUNK) == Route.REJECT_JUNK
    assert route_for_band(RelevanceBand.HIGH) == Route.GRADER
    assert route_for_band(RelevanceBand.UNCERTAIN) == Route.CHECK
    assert route_for_band(RelevanceBand.LOW) == Route.CHECK


def test_transitions_table():
    assert_transition(PartStatus.NOT_STARTED, PartStatus.LEARNING)
    assert_transition(PartStatus.LEARNING, PartStatus.QUIZZING)
    assert_transition(PartStatus.QUIZZING, PartStatus.PASSED)
    assert_transition(PartStatus.QUIZZING, PartStatus.REINFORCING)
    assert_transition(PartStatus.QUIZZING, PartStatus.STALLED)
    assert_transition(PartStatus.REINFORCING, PartStatus.QUIZZING)
    assert_transition(PartStatus.STALLED, PartStatus.LEARNING)
    assert_transition(PartStatus.LEARNING, PartStatus.LEARNING)  # reopening is idempotent
    for illegal in [
        (PartStatus.NOT_STARTED, PartStatus.PASSED),
        (PartStatus.PASSED, PartStatus.QUIZZING),
        (PartStatus.LEARNING, PartStatus.REINFORCING),
        (PartStatus.REINFORCING, PartStatus.PASSED),
    ]:
        with pytest.raises(IllegalTransition):
            assert_transition(*illegal)


def test_after_round():
    assert after_round(score=0.6, threshold=50, rounds_used=1, max_rounds=3) == PartStatus.PASSED
    assert after_round(score=0.5, threshold=50, rounds_used=1, max_rounds=3) == PartStatus.PASSED
    assert after_round(score=0.2, threshold=50, rounds_used=1, max_rounds=3) == PartStatus.REINFORCING
    assert after_round(score=0.2, threshold=50, rounds_used=3, max_rounds=3) == PartStatus.STALLED


def _questions(sections, per_section, mc_every=5):
    qs = []
    for s in sections:
        for _i in range(per_section):
            kind = QuestionKind.MULTIPLE_CHOICE if (len(qs) + 1) % mc_every == 0 else QuestionKind.FREE_TEXT
            qs.append(
                Question(
                    id=uuid4(),
                    section_id=s,
                    language="en",
                    kind=kind,
                    prompt=f"q{len(qs)}",
                    expected_answer="a",
                    rubric=("r",),
                    key_terms=(),
                    exact_values=(),
                    choices=("a", "b", "c", "d") if kind == QuestionKind.MULTIPLE_CHOICE else None,
                    correct_choice=0 if kind == QuestionKind.MULTIPLE_CHOICE else None,
                    position=len(qs),
                )
            )
    return qs


def test_sample_round_spreads_across_sections_and_never_repeats():
    sections = [uuid4(), uuid4(), uuid4()]
    bank = _questions(sections, per_section=6)
    rng = random.Random(1)
    first = sample_round(bank, asked=set(), per_round=5, weights={}, rng=rng)
    assert len(first) == 5 and len({q.id for q in first}) == 5
    assert {q.section_id for q in first} == set(sections)  # every section represented
    second = sample_round(bank, asked={q.id for q in first}, per_round=5, weights={}, rng=rng)
    assert not {q.id for q in first} & {q.id for q in second}


def test_sample_round_weights_weak_sections_but_keeps_coverage():
    sections = [uuid4(), uuid4(), uuid4()]
    bank = _questions(sections, per_section=10)
    weights = {sections[0]: 3.0, sections[1]: 1.0, sections[2]: 1.0}
    rng = random.Random(7)
    picked = sample_round(bank, asked=set(), per_round=6, weights=weights, rng=rng)
    counts = {s: sum(1 for q in picked if q.section_id == s) for s in sections}
    assert counts[sections[0]] >= 3 and all(c >= 1 for c in counts.values())


def test_sample_round_runs_out_gracefully():
    sections = [uuid4()]
    bank = _questions(sections, per_section=2)
    assert len(sample_round(bank, asked={bank[0].id}, per_round=5, weights={}, rng=random.Random(0))) == 1
    assert sample_round(bank, asked={q.id for q in bank}, per_round=5, weights={}, rng=random.Random(0)) == []


def _aq(grade, question):
    return AttemptQuestion(id=uuid4(), attempt_id=uuid4(), question_id=question.id, position=0, grade=grade)


def test_round_score_and_weak_sections():
    sections = [uuid4(), uuid4()]
    bank = _questions(sections, per_section=2, mc_every=100)
    answered = [
        _aq(Grade.CORRECT, bank[0]),
        _aq(Grade.PARTIAL, bank[1]),
        _aq(Grade.INCORRECT, bank[2]),
        _aq(Grade.OFF_TOPIC, bank[3]),
    ]
    assert round_score(answered) == pytest.approx(0.375)
    assert round_score([]) == 0.0
    weak = weak_sections(answered, {q.id: q for q in bank}, cap=3)
    # section 1 lost 2 points, section 0 lost 0.5 -> only the fully-weak section, then ranked by loss
    assert weak == [sections[1]]
    weak_all = weak_sections(answered, {q.id: q for q in bank}, cap=3, min_loss=0.25)
    assert weak_all == [sections[1], sections[0]]
