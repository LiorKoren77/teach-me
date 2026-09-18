from __future__ import annotations

import pytest

from teachme.domain.models import SubjectState
from teachme.eval.runner import EvalRunner
from teachme.generation.outline import OutlineOut


def test_eval_runner_reports_metrics_with_fake_stack(db, make_container):
    container = make_container()
    report = EvalRunner(container).run(languages=["en"])

    (fixture,) = report.fixtures
    assert fixture.language == "en"
    # min_sections: 2 in the fixture's outline bounds; a single-page source could never fail it.
    assert fixture.outline_ok is True and fixture.parts >= 1 and fixture.sections >= 2
    assert len(fixture.answers) == 4
    assert fixture.grading_agreement == 1.0
    assert 0.0 <= fixture.route_agreement <= 1.0
    assert fixture.relevance_false_rejects == 0
    assert fixture.cost_usd >= 0.0

    text = report.render()
    assert "grading agreement" in text and "outline" in text
    assert "[en]" in text


def test_every_answer_reaches_the_loop_and_is_scored_against_its_expectation(db, make_container):
    """The harness is only worth anything if it really asks: every fixture answer must come back
    with a grade (or a rejection) and the route the service actually took."""
    container = make_container()
    (fixture,) = EvalRunner(container).run(languages=["en"]).fixtures

    assert fixture.notes == []
    (junk,) = [a for a in fixture.answers if a.expected_grade == "junk"]
    assert junk.accepted is False and junk.agrees is True
    (off_topic,) = [a for a in fixture.answers if a.expected_grade == "off_topic"]
    # The fake relevance gate now actually rejects it, so the recorded route is the rejection
    # itself - which still counts as "reached the check" for a fixture that only asked for that.
    assert off_topic.route == "reject_off_topic" and off_topic.route_agrees is True
    (correct,) = [a for a in fixture.answers if a.expected_grade == "correct"]
    assert correct.grade == "correct" and correct.accepted is True
    (incorrect,) = [a for a in fixture.answers if a.expected_grade == "incorrect"]
    assert incorrect.grade == "incorrect" and incorrect.accepted is True
    for answer in fixture.answers:
        assert answer.grade in ("correct", "partial", "incorrect", "off_topic", "junk", "rejected")
        assert answer.question  # the question it was actually asked


def test_every_model_call_the_harness_makes_is_recorded_against_its_subject(db, make_container):
    container = make_container()
    (fixture,) = EvalRunner(container).run(languages=["en"]).fixtures
    purposes = {row["purpose"] for row in container.usage_repo.summarize()}
    assert {"gen.outline", "learn.grade", "learn.relevance_check"} <= purposes
    # the cost the report names is the cost of this fixture's subject alone
    assert fixture.cost_usd == sum(
        row["cost_usd"] for row in container.usage_repo.summarize(subject_id=fixture.subject_id)
    )


def test_eval_tears_down_its_fixture_subject_but_keeps_usage_rows(db, make_container):
    """A run must not leave eval-* subjects behind for GET /api/subjects to serve to students,
    but the money already spent on them stays on the books."""
    container = make_container()
    (fixture,) = EvalRunner(container).run(languages=["en"]).fixtures

    assert [s for s in container.subjects.list() if s.name.startswith("eval-")] == []
    usage_rows = container.usage_repo.summarize(subject_id=fixture.subject_id)
    assert usage_rows and sum(row["cost_usd"] for row in usage_rows) == fixture.cost_usd


def test_keep_flag_leaves_the_fixture_subject_published(db, make_container):
    container = make_container()
    (fixture,) = EvalRunner(container).run(languages=["en"], keep=True).fixtures

    subject = container.subjects.get(fixture.subject_id)
    assert subject.state == SubjectState.PUBLISHED
    assert subject.name == fixture.subject


def test_teardown_runs_even_when_a_fixture_raises_mid_run(db, make_container):
    container = make_container()
    fake = container.llm.inner

    def explode(request):
        raise RuntimeError("boom")

    fake.set_responder(OutlineOut, explode)

    with pytest.raises(RuntimeError, match="boom"):
        EvalRunner(container).run(languages=["en"])

    assert [s for s in container.subjects.list() if s.name.startswith("eval-")] == []
