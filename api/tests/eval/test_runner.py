from __future__ import annotations

from teachme.eval.runner import EvalRunner


def test_eval_runner_reports_metrics_with_fake_stack(db, make_container):
    container = make_container()
    report = EvalRunner(container).run(languages=["en"])

    (fixture,) = report.fixtures
    assert fixture.language == "en"
    assert fixture.outline_ok is True and fixture.parts >= 1 and fixture.sections >= 1
    assert len(fixture.answers) == 4
    assert 0.0 <= fixture.grading_agreement <= 1.0
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
    assert off_topic.route == "check" and off_topic.route_agrees is True
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
