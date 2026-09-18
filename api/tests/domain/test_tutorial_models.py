from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from teachme.domain.models import (
    ContentStatus,
    Question,
    QuestionKind,
    Section,
    Subject,
    SubjectState,
)


def test_question_multiple_choice_requires_choices_and_correct_index():
    with pytest.raises(ValidationError):
        Question(
            id=uuid4(),
            section_id=uuid4(),
            language="he",
            kind=QuestionKind.MULTIPLE_CHOICE,
            prompt="?",
            expected_answer="a",
            rubric=("r",),
            key_terms=("k",),
            exact_values=(),
            choices=None,
            correct_choice=None,
        )
    ok = Question(
        id=uuid4(),
        section_id=uuid4(),
        language="he",
        kind=QuestionKind.MULTIPLE_CHOICE,
        prompt="?",
        expected_answer="a",
        rubric=("r",),
        key_terms=("k",),
        exact_values=(),
        choices=("a", "b"),
        correct_choice=0,
    )
    assert ok.choices == ("a", "b")


def test_free_text_question_has_no_choices():
    q = Question(
        id=uuid4(),
        section_id=uuid4(),
        language="en",
        kind=QuestionKind.FREE_TEXT,
        prompt="Why?",
        expected_answer="Because",
        rubric=("r1", "r2"),
        key_terms=("why",),
        exact_values=(),
    )
    assert q.choices is None and q.correct_choice is None


def test_section_page_range_ordering():
    with pytest.raises(ValidationError):
        Section(id=uuid4(), part_id=uuid4(), position=0, page_start=5, page_end=2)


def test_content_status_values():
    assert [s.value for s in ContentStatus] == ["generating", "ready", "failed"]


def test_subject_gloss_frequency_is_one_of_the_rendering_frequencies():
    def subject(**overrides):
        return Subject(id=uuid4(), name="Geo", state=SubjectState.DRAFT, languages=("he",), **overrides)

    assert subject().gloss_frequency == "first"
    assert subject(gloss_frequency="never").gloss_frequency == "never"
    with pytest.raises(ValidationError):
        subject(gloss_frequency="sometimes")
