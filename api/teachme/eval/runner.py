from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from teachme.container import Container
from teachme.domain.models import AttemptQuestion, Question, QuestionKind, Subject, SubjectState
from teachme.eval.fixtures import SOURCE_NAME, ExpectedAnswer, Fixture, FixtureCase, load_cases
from teachme.eval.report import AnswerOutcome, EvalReport, FixtureReport

REAL_ATTEMPT_GRADES = frozenset({"correct", "partial", "incorrect"})
"""Grades a fixture only writes down for an answer that is a genuine attempt at the question."""

_REJECTION_GRADES = frozenset({"junk", "off_topic"})

_ROUTE_REACHED = {
    # An answer the model check rejected still went through the check, which is what a fixture
    # asking for "check" is saying; the same is not true the other way round.
    "check": frozenset({"check", "reject_off_topic"}),
}


def _route_agrees(expected: str, recorded: str | None) -> bool:
    return recorded is not None and recorded in _ROUTE_REACHED.get(expected, frozenset({expected}))


class EvalRunner:
    """Ingest a fixture source, generate, publish, then answer the generated questions as a
    synthetic student and compare the grades and routes with the fixture's expectations.

    Every call goes through the container's own providers, so the models, prompts and thresholds
    under test are exactly the ones a student would meet, and re-running after a settings change
    yields a comparison rather than a new experiment. Each fixture gets a freshly named subject
    and each expected answer its own synthetic student, so one answer's grade never changes which
    questions the next one is asked.

    The fixture subject is scratch, not material to keep: unless `keep=True`, it is unpublished,
    its sources deleted and its row dropped once the fixture has run, so an eval subject never
    lingers in `GET /api/subjects` for a student to see.
    """

    def __init__(self, container: Container) -> None:
        self._c = container

    def run(
        self, *, languages: Sequence[str] | None = None, directory: Path | None = None, keep: bool = False
    ) -> EvalReport:
        cases = load_cases(directory, languages=languages)
        return EvalReport(fixtures=[self._run_case(case, keep=keep) for case in cases])

    # one fixture ----------------------------------------------------------------------------
    def _run_case(self, case: FixtureCase, *, keep: bool) -> FixtureReport:
        spec = case.spec
        name = f"eval-{spec.language}-{uuid4().hex[:6]}"
        try:
            subject = self._prepare(case, name)
            parts, sections = self._outline_shape(subject)
            notes: list[str] = []
            outcomes = [
                outcome
                for index, expected in enumerate(spec.answers)
                if (outcome := self._ask(subject, spec, expected, index, notes)) is not None
            ]
            routed = [o for o in outcomes if o.route_agrees is not None]
            return FixtureReport(
                language=spec.language,
                subject=subject.name,
                subject_id=subject.id,
                outline_ok=self._outline_ok(subject, spec),
                parts=len(parts),
                sections=sections,
                # An answer the harness could not ask counts against agreement: the denominator is
                # what the fixture asked for, not what happened to run.
                grading_agreement=sum(o.agrees for o in outcomes) / len(spec.answers),
                route_agreement=(sum(bool(o.route_agrees) for o in routed) / len(routed)) if routed else 1.0,
                relevance_false_rejects=sum(
                    1 for o in outcomes if o.expected_grade in REAL_ATTEMPT_GRADES and not o.accepted
                ),
                cost_usd=self._cost(subject.id),
                answers=outcomes,
                notes=notes,
            )
        finally:
            if not keep:
                self._teardown(name)

    def _prepare(self, case: FixtureCase, name: str) -> Subject:
        """A new subject per run, named after the fixture and a fresh suffix, so a second run
        compares against the first instead of colliding with it."""
        scope = self._c.scope
        subject = scope.subject_service.get_or_create(name, case.spec.teach_in)
        source = scope.source_service.register(subject, SOURCE_NAME, case.source)
        scope.pipeline.ingest_source(source.id)
        scope.tutorial_service.generate(subject)
        return scope.tutorial_service.publish(subject)

    def _teardown(self, name: str) -> None:
        """Remove the subject this run published, if it got that far: unpublish it so its
        sources can be deleted, delete each source (files, chunks, rows), then delete the subject
        row itself. Usage rows are left alone - `llm_usage.subject_id` carries no foreign key, so
        the fixture's cost stays on the books after the subject it was spent on is gone."""
        scope = self._c.scope
        scope.conn.rollback()  # a mid-run failure may have left the connection mid-transaction
        subject = scope.subjects.get_by_name(name)
        if subject is None:
            return
        if subject.state == SubjectState.PUBLISHED:
            scope.subject_service.set_state(subject, SubjectState.DRAFT)
        for source in scope.source_service.list(subject):
            scope.source_service.delete(source.id)
        scope.subjects.delete(subject.id)
        scope.conn.commit()

    def _outline_shape(self, subject: Subject) -> tuple[list, int]:
        scope = self._c.scope
        outline = scope.outlines.get_version(subject.id, subject.current_outline_version or 0)
        parts = scope.outlines.parts(outline.id) if outline else []
        return parts, sum(len(scope.outlines.sections(part.id)) for part in parts)

    def _outline_ok(self, subject: Subject, spec: Fixture) -> bool:
        scope = self._c.scope
        parts, _ = self._outline_shape(subject)
        return spec.outline.min_parts <= len(parts) <= spec.outline.max_parts and all(
            len(scope.outlines.sections(part.id)) >= spec.outline.min_sections for part in parts
        )

    def _cost(self, subject_id: UUID) -> float:
        """Telemetry writes on the container's own connection, so this reads what every model
        call this fixture made has already recorded."""
        return sum(float(row["cost_usd"]) for row in self._c.usage_repo.summarize(subject_id=subject_id))

    # one answer -----------------------------------------------------------------------------
    def _ask(
        self, subject: Subject, spec: Fixture, expected: ExpectedAnswer, index: int, notes: list[str]
    ) -> AnswerOutcome | None:
        scope = self._c.scope
        language = spec.teach_in[0]
        user = f"{subject.name}-student-{index}"
        session = scope.learning_service.start_part(user, subject, 0, language)
        if session.attempt_id is None:
            notes.append(f"answer {index}: the part started with no attempt to answer into")
            return None
        picked = self._pick(user, session.attempt_id, expected.question_contains)
        if picked is None:
            notes.append(f"answer {index}: the round held no free-text question")
            return None
        aq, question = picked
        result = scope.learning_service.submit_answer(
            user, session.attempt_id, aq.id, answer_text=expected.answer
        )
        recorded = scope.attempts.get_question(aq.id)
        grade = result.grade.value if result.grade else "rejected"
        route = recorded.route.value if recorded.route else None
        return AnswerOutcome(
            question=question.prompt,
            answer=expected.answer,
            expected_grade=expected.expected_grade,
            grade=grade,
            route=route,
            accepted=result.accepted,
            # A rejection is the right outcome for junk and off-topic text even before the
            # question closes with a final grade, so either counts as agreement.
            agrees=grade == expected.expected_grade
            or (expected.expected_grade in _REJECTION_GRADES and not result.accepted),
            route_agrees=_route_agrees(expected.expected_route, route) if expected.expected_route else None,
        )

    def _pick(self, user: str, attempt_id: UUID, contains: str) -> tuple[AttemptQuestion, Question] | None:
        """A still-open free-text question of the current round, preferring one whose prompt
        contains the fixture's substring. Any open question of the round can be answered, so the
        harness never has to work through the ones it did not write an answer for."""
        scope = self._c.scope
        if scope.attempts.next_unanswered(attempt_id) is None:
            scope.learning_service.begin_round(user, attempt_id)
        attempt = scope.attempts.get(attempt_id)
        open_rows = [
            row
            for row in scope.attempts.questions_for_round(attempt_id, attempt.round_no)
            if row.grade is None
        ]
        free = [(row, scope.questions.get(row.question_id)) for row in open_rows]
        free = [pair for pair in free if pair[1].kind == QuestionKind.FREE_TEXT]
        wanted = contains.strip().lower()
        if wanted:
            matched = next((pair for pair in free if wanted in pair[1].prompt.lower()), None)
            if matched is not None:
                return matched
        return free[0] if free else None
