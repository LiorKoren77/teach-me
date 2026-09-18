from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from teachme.domain.models import AttemptQuestion, Grade, PartStatus, RelevanceBand, Route


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
