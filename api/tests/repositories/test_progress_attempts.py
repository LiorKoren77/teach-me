from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from teachme.domain.models import (
    AttemptStatus,
    Grade,
    PartStatus,
    Question,
    QuestionKind,
    RelevanceBand,
    Route,
)
from teachme.repositories.attempts import ActiveAttemptExists, AttemptNotFound, AttemptRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.progress import ProgressNotFound, ProgressRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.subjects import SubjectRepository


def _fixture(db):
    subject = SubjectRepository(db).create(f"S-{uuid4()}", ["he"])
    outlines = OutlineRepository(db)
    outline = outlines.create(subject.id, model="m")
    p1 = outlines.add_part(outline.id, position=0, title="A", page_start=0, page_end=1)
    p2 = outlines.add_part(outline.id, position=1, title="B", page_start=2, page_end=3)
    s1 = outlines.add_section(p1.id, position=0, title="a", page_start=0, page_end=1)
    q = Question(
        id=uuid4(),
        section_id=s1.id,
        language="he",
        kind=QuestionKind.FREE_TEXT,
        prompt="q",
        expected_answer="a",
        rubric=("r",),
        key_terms=(),
        exact_values=(),
        position=0,
    )
    QuestionRepository(db).replace_for_part(p1.id, "he", [q])
    return subject, outline, (p1, p2), q


def test_progress_ensure_get_update_reset(db):
    subject, outline, (p1, p2), _ = _fixture(db)
    repo = ProgressRepository(db)
    rows = repo.ensure_for_subject("user_1", subject.id, outline.version, [p1.id, p2.id])
    assert [r.status for r in rows] == [PartStatus.NOT_STARTED, PartStatus.NOT_STARTED]
    again = repo.ensure_for_subject("user_1", subject.id, outline.version, [p1.id, p2.id])
    assert [r.id for r in again] == [r.id for r in rows]  # idempotent
    repo.update(rows[0].id, status=PartStatus.QUIZZING, best_score=0.4, rounds_used=1)
    loaded = repo.get("user_1", p1.id)
    assert loaded.status == PartStatus.QUIZZING and loaded.best_score == 0.4 and loaded.rounds_used == 1
    repo.update(rows[0].id, best_score=0.3)  # best score never decreases
    assert repo.get("user_1", p1.id).best_score == 0.4
    assert len(repo.list_for_subject("user_1", subject.id)) == 2
    deleted = repo.reset_subject(subject.id)
    assert deleted == 2 and repo.list_for_subject("user_1", subject.id) == []


def test_attempts_lifecycle(db):
    subject, outline, (p1, _), q = _fixture(db)
    repo = AttemptRepository(db)
    attempt = repo.create("user_1", p1.id, "he")
    assert attempt.status == AttemptStatus.ACTIVE and attempt.round_no == 0
    assert repo.active("user_1", p1.id) == attempt
    repo.set_round(attempt.id, 1)
    aq = repo.add_questions(attempt.id, round_no=1, question_ids=[q.id])[0]
    assert aq.position == 0 and aq.grade is None
    assert repo.next_unanswered(attempt.id) == aq
    rejected = repo.record_rejection(
        aq.id,
        relevance_score=0.1,
        band=RelevanceBand.LOW,
        route=Route.REJECT_OFF_TOPIC,
        check_verdict="off_topic",
    )
    assert rejected == 1
    stored = repo.get_question(aq.id)
    assert stored.rejections == 1 and stored.grade is None  # a rejection never closes the question
    assert stored.route == Route.REJECT_OFF_TOPIC and stored.relevance_band == RelevanceBand.LOW
    assert repo.submissions_since_seconds("user_1", 60) == 1  # a rejection counts as a submission
    repo.record_answer(
        aq.id,
        answer_text="my answer",
        answer_choice=None,
        relevance_score=0.7,
        band=RelevanceBand.HIGH,
        route=Route.GRADER,
        check_verdict=None,
        grade=Grade.PARTIAL,
        rubric_covered=(0,),
        missed_concepts=("x",),
        feedback="ok",
    )
    answered = repo.questions_for_round(attempt.id, 1)
    assert answered[0].grade == Grade.PARTIAL
    assert answered[0].feedback == "ok" and answered[0].rubric_covered == (0,)
    assert repo.next_unanswered(attempt.id) is None
    assert repo.asked_question_ids(attempt.id) == {q.id}
    # one rejection plus one answer on the same question is two submissions, not one question
    assert repo.submissions_since_seconds("user_1", 60) == 2
    repo.add_reexplanation(
        attempt.id, round_no=1, section_ids=[q.section_id], language="he", body="again", model="m"
    )
    assert repo.latest_reexplanation(attempt.id).body == "again"
    repo.finish(attempt.id, AttemptStatus.PASSED)
    assert repo.get(attempt.id).status == AttemptStatus.PASSED and repo.active("user_1", p1.id) is None


def test_learning_schema_enforces_the_domain_enums_and_ranges(db):
    """The status, grade, band and route columns feed StrEnums: a value outside them cannot be
    loaded back as a domain object at all, so the database refuses to store one."""
    subject, outline, (p1, _), q = _fixture(db)
    attempts = AttemptRepository(db)
    attempt = attempts.create("user_1", p1.id, "he")
    aq = attempts.add_questions(attempt.id, round_no=1, question_ids=[q.id])[0]
    progress = ProgressRepository(db).ensure_for_subject("user_1", subject.id, outline.version, [p1.id])
    db.commit()

    rejected = [
        (
            "INSERT INTO attempts (id, user_id, part_id, language, status) VALUES (%s, %s, %s, %s, %s)",
            (uuid4(), "user_2", p1.id, "he", "halfway"),
        ),
        (
            "INSERT INTO part_progress (id, user_id, subject_id, part_id, outline_version, status)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (uuid4(), "user_2", subject.id, p1.id, outline.version, "thinking"),
        ),
        ("UPDATE part_progress SET rounds_used = -1 WHERE id = %s", (progress[0].id,)),
        ("UPDATE part_progress SET best_score = 1.5 WHERE id = %s", (progress[0].id,)),
        ("UPDATE attempt_questions SET grade = 'maybe' WHERE id = %s", (aq.id,)),
        ("UPDATE attempt_questions SET relevance_band = 'medium' WHERE id = %s", (aq.id,)),
        ("UPDATE attempt_questions SET route = 'guess' WHERE id = %s", (aq.id,)),
        ("UPDATE attempt_questions SET relevance_score = 1.5 WHERE id = %s", (aq.id,)),
        # a chosen option is an index into the question's choices, never negative
        ("UPDATE attempt_questions SET answer_choice = -1 WHERE id = %s", (aq.id,)),
    ]
    for sql, params in rejected:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(sql, params)
        db.rollback()

    # best_score is a fraction: a percent does not even fit the column
    with pytest.raises(psycopg.errors.NumericValueOutOfRange):
        db.execute("UPDATE part_progress SET best_score = 60 WHERE id = %s", (progress[0].id,))
    db.rollback()


def test_only_one_active_attempt_per_user_and_part(db):
    _, _, (p1, _), _ = _fixture(db)
    repo = AttemptRepository(db)
    first = repo.create("user_1", p1.id, "he")
    db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO attempts (id, user_id, part_id, language, status) VALUES (%s, %s, %s, %s, 'active')",
            (uuid4(), "user_1", p1.id, "he"),
        )
    db.rollback()

    with pytest.raises(ActiveAttemptExists, match=str(p1.id)):
        repo.create("user_1", p1.id, "he")
    db.rollback()

    repo.finish(first.id, AttemptStatus.FAILED)  # finishing the attempt frees the slot
    assert repo.create("user_1", p1.id, "he").id != first.id


def test_best_score_round_trips_a_four_decimal_fraction(db):
    subject, outline, (p1, _), _ = _fixture(db)
    repo = ProgressRepository(db)
    rows = repo.ensure_for_subject("user_1", subject.id, outline.version, [p1.id])
    repo.update(rows[0].id, best_score=0.375)
    assert repo.get("user_1", p1.id).best_score == 0.375


def test_missing_rows_are_reported_as_not_found(db):
    """A student with no row for a part, or an attempt id from nowhere: named errors, not None."""
    _, _, (p1, _), _ = _fixture(db)
    with pytest.raises(ProgressNotFound, match=str(p1.id)):
        ProgressRepository(db).get("user_1", p1.id)
    repo = AttemptRepository(db)
    missing = uuid4()
    with pytest.raises(AttemptNotFound, match=str(missing)):
        repo.get(missing)
    with pytest.raises(AttemptNotFound, match=str(missing)):
        repo.get_question(missing)
    assert repo.active("user_1", p1.id) is None  # no active attempt is an absence, not an error
