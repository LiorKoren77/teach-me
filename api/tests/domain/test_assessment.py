from __future__ import annotations

import random
from uuid import uuid4

import pytest

from teachme.domain.assessment.sampling import sample_round
from teachme.domain.assessment.scoring import (
    UnmappedQuestion,
    round_score,
    section_weights,
    weak_sections,
)
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
    assert_transition(PartStatus.LEARNING, PartStatus.STALLED)  # the bank ran out mid-attempt
    assert_transition(PartStatus.REINFORCING, PartStatus.STALLED)
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


def test_after_round_rejects_a_score_outside_the_unit_range():
    """A percent slipping in where a fraction belongs would silently pass every part."""
    for bad in (-0.01, 1.5, 60.0):
        with pytest.raises(ValueError, match="score"):
            after_round(score=bad, threshold=50, rounds_used=1, max_rounds=3)


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
    """Aggregate over many seeds instead of one lucky seed: a 3x weight has to show up as a
    materially larger share of the round, while every section still gets its coverage question."""
    sections = [uuid4(), uuid4(), uuid4()]
    bank = _questions(sections, per_section=10, mc_every=100)
    weights = {sections[0]: 3.0, sections[1]: 1.0, sections[2]: 1.0}
    counts = dict.fromkeys(sections, 0)
    for seed in range(200):
        picked = sample_round(bank, asked=set(), per_round=6, weights=weights, rng=random.Random(seed))
        assert len(picked) == 6
        for section in sections:
            drawn = sum(1 for q in picked if q.section_id == section)
            assert drawn >= 1  # coverage survives the weighting
            counts[section] += drawn
    assert counts[sections[0]] >= 1.5 * max(counts[sections[1]], counts[sections[2]])


def test_sample_round_still_reaches_the_weak_section_when_sections_outnumber_the_round():
    """With more sections than questions the coverage pass alone decides the round, so it has to
    run in weight order: otherwise a weak section is simply shuffled out of reach."""
    sections = [uuid4() for _ in range(8)]
    bank = _questions(sections, per_section=3)
    weak = sections[0]
    rounds = [
        sample_round(bank, asked=set(), per_round=4, weights={weak: 5.0}, rng=random.Random(seed))
        for seed in range(200)
    ]
    hit = sum(1 for picked in rounds if any(q.section_id == weak for q in picked))
    assert hit >= 190  # the weak section is in at least 95% of rounds


def test_sample_round_keeps_the_banks_question_mix():
    sections = [uuid4(), uuid4()]
    bank = _questions(sections, per_section=6, mc_every=2)
    assert sum(1 for q in bank if q.kind == QuestionKind.MULTIPLE_CHOICE) == len(bank) // 2
    for seed in range(50):
        picked = sample_round(bank, asked=set(), per_round=6, weights={}, rng=random.Random(seed))
        assert len(picked) == 6
        assert sum(1 for q in picked if q.kind == QuestionKind.MULTIPLE_CHOICE) == 3


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
    mapping = {q.id: q for q in bank}
    # section 1 lost 2 points, section 0 lost 0.5: both clear the default min_loss, ranked by loss
    assert weak_sections(answered, mapping, cap=3) == [sections[1], sections[0]]
    assert weak_sections(answered, mapping, cap=1) == [sections[1]]
    assert weak_sections(answered, mapping, cap=3, min_loss=1.0) == [sections[1]]


def test_weak_sections_never_empty_for_a_failed_round():
    """A failed round always has something to reinforce, whatever min_loss the caller asked for:
    an empty list would leave the student staring at a re-explanation of nothing."""
    sections = [uuid4(), uuid4()]
    bank = _questions(sections, per_section=2, mc_every=100)
    mapping = {q.id: q for q in bank}
    answered = [
        _aq(Grade.CORRECT, bank[0]),
        _aq(Grade.PARTIAL, bank[1]),
        _aq(Grade.CORRECT, bank[2]),
        _aq(Grade.CORRECT, bank[3]),
    ]
    assert weak_sections(answered, mapping, cap=3, min_loss=2.0) == [sections[0]]
    # an unanswered question is a whole point lost, not a free pass
    assert weak_sections([_aq(None, bank[2])], mapping, cap=3) == [sections[1]]
    # an all-correct round has no weak section at all
    assert weak_sections([_aq(Grade.CORRECT, q) for q in bank], mapping, cap=3, min_loss=2.0) == []


def test_section_weights_are_one_plus_the_points_lost():
    sections = [uuid4(), uuid4()]
    bank = _questions(sections, per_section=2, mc_every=100)
    answered = [
        _aq(Grade.INCORRECT, bank[0]),
        _aq(Grade.PARTIAL, bank[1]),
        _aq(Grade.CORRECT, bank[2]),
        _aq(Grade.CORRECT, bank[3]),
    ]
    weights = section_weights(answered, {q.id: q for q in bank})
    assert weights[sections[0]] == pytest.approx(2.5)  # 1 + 1.0 + 0.5
    assert weights[sections[1]] == pytest.approx(1.0)  # all correct: no extra pull


def test_scoring_names_the_attempt_question_behind_an_unmapped_question():
    bank = _questions([uuid4()], per_section=1, mc_every=100)
    answered = [_aq(Grade.CORRECT, bank[0])]
    for call in (lambda: weak_sections(answered, {}, cap=1), lambda: section_weights(answered, {})):
        with pytest.raises(UnmappedQuestion, match=str(answered[0].id)):
            call()
