from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import (
    Attempt,
    AttemptQuestion,
    AttemptStatus,
    Grade,
    Reexplanation,
    RelevanceBand,
    Route,
)
from teachme.repositories.errors import NotFound

_ATTEMPT = "id, user_id, part_id, language, round_no, status"
_AQ = (
    "id, attempt_id, question_id, round_no, position, answer_text, answer_choice, relevance_score,"
    " relevance_band, route, check_verdict, grade, rubric_covered, missed_concepts, feedback, rejections"
)
_REEXPLANATION = "id, attempt_id, round_no, section_ids, language, body, model, truncated"


class AttemptNotFound(NotFound):
    entity = "attempt"


class ActiveAttemptExists(Exception):
    """attempts_one_active_idx: a (student, part) can hold only one active attempt at a time.

    Raised instead of the raw UniqueViolation so the learning service, which resumes the active
    attempt and starts a new one only after the previous is finished, fails with a name.
    """

    def __init__(self, user_id: str, part_id: UUID) -> None:
        super().__init__(f"{user_id} already has an active attempt on part {part_id}")
        self.user_id = user_id
        self.part_id = part_id


def _attempt(row: dict) -> Attempt:
    return Attempt(
        id=row["id"],
        user_id=row["user_id"],
        part_id=row["part_id"],
        language=row["language"],
        round_no=row["round_no"],
        status=AttemptStatus(row["status"]),
    )


def _aq(row: dict) -> AttemptQuestion:
    return AttemptQuestion(
        id=row["id"],
        attempt_id=row["attempt_id"],
        question_id=row["question_id"],
        round_no=row["round_no"],
        position=row["position"],
        answer_text=row["answer_text"],
        answer_choice=row["answer_choice"],
        relevance_score=row["relevance_score"],
        relevance_band=RelevanceBand(row["relevance_band"]) if row["relevance_band"] else None,
        route=Route(row["route"]) if row["route"] else None,
        check_verdict=row["check_verdict"],
        grade=Grade(row["grade"]) if row["grade"] else None,
        rubric_covered=tuple(row["rubric_covered"] or ()),
        missed_concepts=tuple(row["missed_concepts"] or ()),
        feedback=row["feedback"],
        rejections=row["rejections"],
    )


def _reexplanation(row: dict) -> Reexplanation:
    return Reexplanation(
        id=row["id"],
        attempt_id=row["attempt_id"],
        round_no=row["round_no"],
        section_ids=tuple(row["section_ids"]),
        language=row["language"],
        body=row["body"],
        model=row["model"],
        truncated=row["truncated"],
    )


class AttemptRepository:
    """attempts, their questions and their re-explanations. Never commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, part_id: UUID, language: str) -> Attempt:
        attempt_id = uuid4()
        try:
            self._conn.execute(
                "INSERT INTO attempts (id, user_id, part_id, language, status)"
                " VALUES (%s, %s, %s, %s, 'active')",
                (attempt_id, user_id, part_id, language),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise ActiveAttemptExists(user_id, part_id) from exc
        return self.get(attempt_id)

    def get(self, attempt_id: UUID) -> Attempt:
        row = self._conn.execute(f"SELECT {_ATTEMPT} FROM attempts WHERE id = %s", (attempt_id,)).fetchone()
        if row is None:
            raise AttemptNotFound(attempt_id)
        return _attempt(row)

    def active(self, user_id: str, part_id: UUID) -> Attempt | None:
        row = self._conn.execute(
            f"SELECT {_ATTEMPT} FROM attempts WHERE user_id = %s AND part_id = %s AND status = 'active'"
            " ORDER BY started_at DESC LIMIT 1",
            (user_id, part_id),
        ).fetchone()
        return _attempt(row) if row else None

    def set_round(self, attempt_id: UUID, round_no: int) -> None:
        self._conn.execute("UPDATE attempts SET round_no = %s WHERE id = %s", (round_no, attempt_id))

    def finish(self, attempt_id: UUID, status: AttemptStatus) -> None:
        self._conn.execute(
            "UPDATE attempts SET status = %s, finished_at = now() WHERE id = %s",
            (status.value, attempt_id),
        )

    def add_questions(
        self, attempt_id: UUID, *, round_no: int, question_ids: Sequence[UUID]
    ) -> list[AttemptQuestion]:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO attempt_questions (id, attempt_id, question_id, round_no, position)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(uuid4(), attempt_id, qid, round_no, i) for i, qid in enumerate(question_ids)],
            )
        return self.questions_for_round(attempt_id, round_no)

    def questions_for_round(self, attempt_id: UUID, round_no: int) -> list[AttemptQuestion]:
        rows = self._conn.execute(
            f"SELECT {_AQ} FROM attempt_questions WHERE attempt_id = %s AND round_no = %s ORDER BY position",
            (attempt_id, round_no),
        ).fetchall()
        return [_aq(row) for row in rows]

    def next_unanswered(self, attempt_id: UUID) -> AttemptQuestion | None:
        row = self._conn.execute(
            f"SELECT {_AQ} FROM attempt_questions WHERE attempt_id = %s AND grade IS NULL"
            " ORDER BY round_no, position LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return _aq(row) if row else None

    def get_question(self, attempt_question_id: UUID) -> AttemptQuestion:
        row = self._conn.execute(
            f"SELECT {_AQ} FROM attempt_questions WHERE id = %s", (attempt_question_id,)
        ).fetchone()
        if row is None:
            raise AttemptNotFound(attempt_question_id)
        return _aq(row)

    def asked_question_ids(self, attempt_id: UUID) -> set[UUID]:
        rows = self._conn.execute(
            "SELECT question_id FROM attempt_questions WHERE attempt_id = %s", (attempt_id,)
        ).fetchall()
        return {row["question_id"] for row in rows}

    def record_answer(
        self,
        attempt_question_id: UUID,
        *,
        answer_text: str | None,
        answer_choice: int | None,
        relevance_score: float | None,
        band: RelevanceBand | None,
        route: Route,
        check_verdict: str | None,
        grade: Grade,
        rubric_covered: Sequence[int],
        missed_concepts: Sequence[str],
        feedback: str | None,
    ) -> int:
        """Rows written: 0 when the question already carries a grade.

        `grade IS NULL` makes the write the point where two submissions of the same question are
        decided, instead of the read that preceded them: the second one overwrote the first
        verdict, and the student saw feedback for an answer that was not the recorded one."""
        result = self._conn.execute(
            "UPDATE attempt_questions SET answer_text = %s, answer_choice = %s, relevance_score = %s,"
            " relevance_band = %s, route = %s, check_verdict = %s, grade = %s, rubric_covered = %s,"
            " missed_concepts = %s, feedback = %s, answered_at = now()"
            " WHERE id = %s AND grade IS NULL",
            (
                answer_text,
                answer_choice,
                relevance_score,
                band.value if band else None,
                route.value,
                check_verdict,
                grade.value,
                list(rubric_covered),
                list(missed_concepts),
                feedback,
                attempt_question_id,
            ),
        )
        return result.rowcount

    def record_rejection(
        self,
        attempt_question_id: UUID,
        *,
        relevance_score: float | None,
        band: RelevanceBand | None,
        route: Route,
        check_verdict: str | None,
    ) -> int:
        """Count a rejection and keep why it was rejected; returns the new count, 0 if nothing
        was written because the question already carries a grade.

        `grade` stays NULL: the question is asked again. The relevance columns are written even
        so, because a rejection that is not the final one used to leave no trace of the band, the
        route or the check verdict that produced it - and the check verdict cost a model call.
        """
        row = self._conn.execute(
            "UPDATE attempt_questions SET rejections = rejections + 1, last_rejected_at = now(),"
            " relevance_score = %s, relevance_band = %s, route = %s, check_verdict = %s"
            " WHERE id = %s AND grade IS NULL RETURNING rejections",
            (
                relevance_score,
                band.value if band else None,
                route.value,
                check_verdict,
                attempt_question_id,
            ),
        ).fetchone()
        return int(row["rejections"]) if row else 0

    def submissions_since_seconds(self, user_id: str, seconds: int) -> int:
        """Answers and rejections in the window: a rejected submission is what the rate limit is
        there for, since an off-topic answer can still reach the relevance check."""
        row = self._conn.execute(
            "SELECT count(*) AS n FROM attempt_questions aq JOIN attempts a ON a.id = aq.attempt_id"
            " WHERE a.user_id = %s AND greatest(aq.answered_at, aq.last_rejected_at)"
            " >= now() - make_interval(secs => %s)",
            (user_id, seconds),
        ).fetchone()
        return int(row["n"])

    def add_reexplanation(
        self,
        attempt_id: UUID,
        *,
        round_no: int,
        section_ids: Sequence[UUID],
        language: str,
        body: str,
        model: str,
        truncated: bool = False,
    ) -> Reexplanation:
        rid = uuid4()
        self._conn.execute(
            f"INSERT INTO reexplanations ({_REEXPLANATION}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (rid, attempt_id, round_no, list(section_ids), language, body, model, truncated),
        )
        return Reexplanation(
            id=rid,
            attempt_id=attempt_id,
            round_no=round_no,
            section_ids=tuple(section_ids),
            language=language,
            body=body,
            model=model,
            truncated=truncated,
        )

    def latest_reexplanation(self, attempt_id: UUID) -> Reexplanation | None:
        row = self._conn.execute(
            f"SELECT {_REEXPLANATION} FROM reexplanations WHERE attempt_id = %s"
            " ORDER BY created_at DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return _reexplanation(row) if row else None
