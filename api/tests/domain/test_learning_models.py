from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from teachme.domain.models import (
    AttemptQuestion,
    Grade,
    PartProgress,
    PartStatus,
    RelevanceBand,
    Route,
)


def test_part_status_values_in_spec_order():
    assert [s.value for s in PartStatus] == [
        "not_started",
        "learning",
        "quizzing",
        "reinforcing",
        "passed",
        "stalled",
    ]


def test_grade_and_band_and_route_values():
    assert {g.value for g in Grade} == {"correct", "partial", "incorrect", "off_topic", "junk"}
    assert {b.value for b in RelevanceBand} == {"junk", "low", "uncertain", "high"}
    assert {r.value for r in Route} == {"reject_junk", "check", "grader", "reject_off_topic", "code"}


def test_attempt_question_score_points():
    base = dict(id=uuid4(), attempt_id=uuid4(), question_id=uuid4(), position=0)
    assert AttemptQuestion(**base, grade=Grade.CORRECT).points == 1.0
    assert AttemptQuestion(**base, grade=Grade.PARTIAL).points == 0.5
    assert AttemptQuestion(**base, grade=Grade.INCORRECT).points == 0.0
    assert AttemptQuestion(**base, grade=Grade.OFF_TOPIC).points == 0.0
    assert AttemptQuestion(**base).points is None  # unanswered
    with pytest.raises(ValidationError):
        AttemptQuestion(**base, relevance_score=1.5)


def test_attempt_question_rejects_negative_position_and_round():
    base = dict(id=uuid4(), attempt_id=uuid4(), question_id=uuid4())
    assert AttemptQuestion(**base, position=0, round_no=0).round_no == 0
    with pytest.raises(ValidationError):
        AttemptQuestion(**base, position=-1)
    with pytest.raises(ValidationError):
        AttemptQuestion(**base, position=0, round_no=-1)


def test_part_progress_best_score_is_a_fraction():
    base = dict(id=uuid4(), user_id="u", subject_id=uuid4(), part_id=uuid4(), status=PartStatus.QUIZZING)
    assert PartProgress(**base, outline_version=1, best_score=0.375).best_score == 0.375
    assert PartProgress(**base, outline_version=1).best_score is None
    for bad in (
        dict(outline_version=-1),
        dict(outline_version=1, rounds_used=-1),
        dict(outline_version=1, best_score=60.0),  # a percent is not a fraction
        dict(outline_version=1, best_score=-0.1),
    ):
        with pytest.raises(ValidationError):
            PartProgress(**base, **bad)
