from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.container import Container
from teachme.domain.models import (
    AttemptStatus,
    Grade,
    PartStatus,
    Question,
    QuestionKind,
    RelevanceBand,
    Route,
)
from teachme.grading.grader import GradeOut
from teachme.grading.relevance_check import RelevanceVerdict
from teachme.repositories.attempts import AttemptRepository
from teachme.services.learning import BankExhausted, LearningError, NotAllowed
from teachme.settings import Settings
from tests.helpers import make_pdf

USER = "user_student_1"


@pytest.fixture
def env(db, migrated_database, tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=migrated_database,
        llm_provider="fake",
        embeddings_provider="fake",
        reranker_provider="noop",
        file_store="local",
        local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest",
        pages_per_read_batch=3,
        pages_per_chunk_batch=3,
        max_answers_per_minute=1000,
    )
    c = Container(settings)
    subject = c.subject_service.get_or_create("Geo", ["he", "en"])
    source = c.source_service.register(subject, "ch1.pdf", make_pdf(6))
    c.pipeline.ingest_source(source.id)
    c.tutorial_service.generate(subject)
    subject = c.tutorial_service.publish(subject)
    fake = c.llm.inner  # the FakeLLM under the recorder
    # A generic answer is not lexically close to a generated question, so the round routes through
    # the relevance check by default; the tests that exercise rejection override this responder.
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="on_topic"))
    yield c, subject, fake
    c.close()


def _grade(verdict):
    return lambda req: GradeOut(
        verdict=verdict,
        rubric_covered=[0] if verdict != "incorrect" else [],
        missed_concepts=["m"],
        feedback=f"fb-{verdict}",
    )


def _free_text(section_id, position):
    return Question(
        id=uuid4(),
        section_id=section_id,
        language="en",
        kind=QuestionKind.FREE_TEXT,
        prompt=f"Question {position} about the ozone layer?",
        expected_answer="the ozone layer",
        rubric=("names the layer",),
        key_terms=(),
        exact_values=(),
        position=position,
    )


def _answer_all(c, attempt_id, question, verdict="correct"):
    """Answer every question of the current round with the given grader verdict; return the round result."""
    result = None
    while question is not None:
        if question.kind == QuestionKind.MULTIPLE_CHOICE:
            res = c.learning_service.submit_answer(
                USER, attempt_id, question.attempt_question_id, answer_choice=1
            )
        else:
            res = c.learning_service.submit_answer(
                USER,
                attempt_id,
                question.attempt_question_id,
                answer_text="The ozone layer of the atmosphere absorbs radiation, protecting the biosphere.",
            )
        question, result = res.next_question, res.round_result
    return result


def test_open_subject_creates_progress_and_locks_later_parts(env):
    c, subject, _ = env
    view = c.learning_service.open_subject(USER, subject)
    assert view.parts[0].status == PartStatus.NOT_STARTED and not view.parts[0].locked
    assert all(p.locked for p in view.parts[1:])
    with pytest.raises(NotAllowed):
        c.learning_service.start_part(USER, subject, position=1, language="he")


def test_full_pass_on_first_round(env):
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("correct"))
    session = c.learning_service.start_part(USER, subject, position=0, language="he")
    assert session.status == PartStatus.LEARNING and session.attempt_id
    assert "{{term:" not in session.part.body
    first = c.learning_service.begin_round(USER, session.attempt_id)
    assert first.round_no == 1 and first.total_in_round == subject.questions_per_round
    assert first.position == 0
    result = _answer_all(c, session.attempt_id, first)
    assert result.passed and result.status == PartStatus.PASSED and result.score >= 0.5
    view = c.learning_service.open_subject(USER, subject)
    assert view.parts[0].status == PartStatus.PASSED and not view.parts[1].locked
    # a passed part can be reopened for reading, without an attempt
    again = c.learning_service.start_part(USER, subject, position=0, language="he")
    assert again.status == PartStatus.PASSED and again.attempt_id is None


def test_fail_reinforce_then_pass(env):
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("incorrect"))
    fake.set_text_responder(lambda req: "## Again\n\n{{term:biosphere|x}} explained differently.")
    session = c.learning_service.start_part(USER, subject, position=0, language="he")
    first = c.learning_service.begin_round(USER, session.attempt_id)
    result = _answer_all(c, session.attempt_id, first)
    assert not result.passed and result.status == PartStatus.REINFORCING
    assert result.rounds_left == subject.max_rounds - 1
    assert result.weak_section_titles

    seen = []
    reexp = c.learning_service.reexplain(USER, session.attempt_id, on_delta=seen.append)
    assert "".join(seen) == reexp.body and "{{term:" in reexp.body
    replay = []
    c.learning_service.reexplain(USER, session.attempt_id, on_delta=replay.append)  # cached
    assert "".join(replay) == reexp.body
    assert sum(1 for r in fake.calls if r.purpose == "learn.reexplain") == 1

    fake.set_responder(GradeOut, _grade("correct"))
    second = c.learning_service.begin_round(USER, session.attempt_id)
    assert second.round_no == 2
    asked_round1 = {q.question_id for q in c.attempts.questions_for_round(session.attempt_id, 1)}
    asked_round2 = {q.question_id for q in c.attempts.questions_for_round(session.attempt_id, 2)}
    assert not asked_round1 & asked_round2
    result = _answer_all(c, session.attempt_id, second)
    assert result.passed
    assert c.progress.get(USER, c.attempts.get(session.attempt_id).part_id).rounds_used == 2


def test_stall_after_max_rounds_then_retry(env):
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("incorrect"))
    fake.set_text_responder(lambda req: "again")
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    for _round_no in range(1, subject.max_rounds + 1):
        q = c.learning_service.begin_round(USER, session.attempt_id)
        result = _answer_all(c, session.attempt_id, q)
    assert result.status == PartStatus.STALLED and result.rounds_left == 0
    with pytest.raises(LearningError):
        c.learning_service.begin_round(USER, session.attempt_id)  # attempt is finished
    retry = c.learning_service.start_part(USER, subject, position=0, language="en")
    assert retry.status == PartStatus.LEARNING and retry.attempt_id != session.attempt_id


def test_relevance_routing_rejects_junk_and_off_topic_answers(env):
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("correct"))
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="off_topic"))
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    q = c.learning_service.begin_round(USER, session.attempt_id)
    assert q.kind == QuestionKind.FREE_TEXT

    junk = c.learning_service.submit_answer(
        USER, session.attempt_id, q.attempt_question_id, answer_text="   "
    )
    assert not junk.accepted and junk.rejection_reason == "empty"
    assert junk.next_question.attempt_question_id == q.attempt_question_id

    off = c.learning_service.submit_answer(
        USER, session.attempt_id, q.attempt_question_id, answer_text="I love football and pizza tonight"
    )
    # second rejection on the same question: graded as wrong and the round moves on
    assert not off.accepted and off.grade == Grade.OFF_TOPIC
    assert off.next_question.attempt_question_id != q.attempt_question_id
    recorded = c.attempts.get_question(q.attempt_question_id)
    assert recorded.route == Route.REJECT_OFF_TOPIC and recorded.check_verdict == "off_topic"
    assert recorded.rejections == 2

    # a clearly on-topic answer skips the rejection path and reaches the grader
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="on_topic"))
    res = c.learning_service.submit_answer(
        USER,
        session.attempt_id,
        off.next_question.attempt_question_id,
        answer_text="Fake teaching sentence about the topic with fake words",
    )
    assert res.accepted and res.grade == Grade.CORRECT


def test_multiple_choice_is_graded_in_code_without_a_model_call(env):
    """The round is made of exactly one multiple-choice question, so the path is reached every
    run instead of only when the sampler happens to draw the bank's single choice question."""
    c, subject, fake = env
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    part_id = c.attempts.get(session.attempt_id).part_id
    section = c.outlines.sections(part_id)[0]
    slug = c.glossary.terms(c.outlines.get(c.outlines.get_part(part_id).outline_id).id)[0].slug
    c.questions.replace_for_part(
        part_id,
        "en",
        [
            Question(
                id=uuid4(),
                section_id=section.id,
                language="en",
                kind=QuestionKind.MULTIPLE_CHOICE,
                prompt="Which layer absorbs it?",
                expected_answer="B",
                rubric=("names the layer",),
                key_terms=(),
                exact_values=(),
                choices=("A", f"the {{{{term:{slug}|chosen layer}}}}", "C", "D"),
                correct_choice=1,
                position=0,
            )
        ],
    )
    c.conn.commit()

    calls_before = len(fake.calls)
    question = c.learning_service.begin_round(USER, session.attempt_id)
    assert question.kind == QuestionKind.MULTIPLE_CHOICE and question.total_in_round == 1
    assert question.choices == ("A", "the chosen layer", "C", "D")  # placeholders rendered

    result = c.learning_service.submit_answer(
        USER, session.attempt_id, question.attempt_question_id, answer_choice=0
    )
    assert result.accepted and result.grade == Grade.INCORRECT
    assert result.round_result is not None and result.round_result.score == 0.0
    recorded = c.attempts.get_question(question.attempt_question_id)
    assert recorded.route == Route.CODE and recorded.answer_choice == 0 and recorded.answer_text is None
    assert len(fake.calls) == calls_before  # grading a choice never reaches a model


def test_ownership_and_rate_limit(env):
    c, subject, fake = env
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    q = c.learning_service.begin_round(USER, session.attempt_id)
    with pytest.raises(NotAllowed):
        c.learning_service.submit_answer(
            "someone_else", session.attempt_id, q.attempt_question_id, answer_text="x"
        )
    c.settings.max_answers_per_minute = 0
    with pytest.raises(NotAllowed, match="rate"):
        c.learning_service.submit_answer(
            USER, session.attempt_id, q.attempt_question_id, answer_text="a real answer here"
        )


def test_publish_with_new_version_resets_progress(env):
    c, subject, fake = env
    c.learning_service.open_subject(USER, subject)
    assert c.progress.list_for_subject(USER, subject.id)
    draft = c.tutorial_service.unpublish(subject)
    c.tutorial_service.generate(draft)  # new outline version 2
    c.tutorial_service.publish(c.subjects.get(subject.id))
    assert c.progress.list_for_subject(USER, subject.id) == []


def test_an_exhausted_question_bank_stalls_the_part_instead_of_locking_it(env):
    """Nothing is permanently locked: the bank runs out mid-attempt, the part stalls, and a fresh
    attempt - whose asked set is empty - has the whole bank to draw from again."""
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("incorrect"))
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    part_id = c.attempts.get(session.attempt_id).part_id
    section = c.outlines.sections(part_id)[0]
    # smaller than questions_per_round * max_rounds: round 1 takes five, round 2 the last one
    c.questions.replace_for_part(part_id, "en", [_free_text(section.id, i) for i in range(6)])
    c.conn.commit()

    for _round_no in (1, 2):
        question = c.learning_service.begin_round(USER, session.attempt_id)
        _answer_all(c, session.attempt_id, question)
    with pytest.raises(BankExhausted, match="fresh attempt"):
        c.learning_service.begin_round(USER, session.attempt_id)
    assert c.progress.get(USER, part_id).status == PartStatus.STALLED
    assert c.attempts.get(session.attempt_id).status == AttemptStatus.FAILED

    retry = c.learning_service.start_part(USER, subject, position=0, language="en")
    assert retry.status == PartStatus.LEARNING and retry.attempt_id != session.attempt_id
    reopened = c.learning_service.begin_round(USER, retry.attempt_id)
    assert reopened.round_no == 1 and reopened.total_in_round == subject.questions_per_round


def _grader_calls(fake):
    return sum(1 for r in fake.calls if r.purpose == "learn.grade")


def test_answers_are_recorded_once_even_under_concurrent_submission(env, db):
    """Two submissions of the same question interleave: both pass the "still open" read, but only
    the first write lands, and the second is refused instead of overwriting a stored verdict."""
    c, subject, fake = env
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    question = c.learning_service.begin_round(USER, session.attempt_id)
    rival = AttemptRepository(db)

    def grade_while_the_rival_commits(_req):
        rival.record_answer(
            question.attempt_question_id,
            answer_text="the rival answer",
            answer_choice=None,
            relevance_score=None,
            band=None,
            route=Route.GRADER,
            check_verdict=None,
            grade=Grade.PARTIAL,
            rubric_covered=(),
            missed_concepts=(),
            feedback="rival feedback",
        )
        db.commit()
        return _grade("correct")(_req)

    fake.set_responder(GradeOut, grade_while_the_rival_commits)
    with pytest.raises(NotAllowed, match="not open"):
        c.learning_service.submit_answer(
            USER,
            session.attempt_id,
            question.attempt_question_id,
            answer_text="The ozone layer of the atmosphere absorbs radiation.",
        )
    stored = c.attempts.get_question(question.attempt_question_id)
    assert stored.grade == Grade.PARTIAL and stored.feedback == "rival feedback"

    graded = _grader_calls(fake)
    fake.set_responder(GradeOut, _grade("correct"))
    with pytest.raises(NotAllowed, match="not open"):
        c.learning_service.submit_answer(
            USER, session.attempt_id, question.attempt_question_id, answer_text="another try"
        )
    assert _grader_calls(fake) == graded  # a closed question never reaches the grader again


def test_a_round_already_sampled_elsewhere_is_reported_as_unfinished(env, db):
    c, subject, fake = env
    fake.set_responder(GradeOut, _grade("incorrect"))
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    first = c.learning_service.begin_round(USER, session.attempt_id)
    _answer_all(c, session.attempt_id, first)
    part_id = c.attempts.get(session.attempt_id).part_id

    rival = AttemptRepository(db)
    spare = next(
        q
        for q in c.questions.for_part(part_id, "en")
        if q.id not in c.attempts.asked_question_ids(session.attempt_id)
    )
    rival_row = rival.add_questions(session.attempt_id, round_no=2, question_ids=[spare.id])[0]
    rival.record_answer(
        rival_row.id,
        answer_text="already answered",
        answer_choice=None,
        relevance_score=None,
        band=None,
        route=Route.GRADER,
        check_verdict=None,
        grade=Grade.CORRECT,
        rubric_covered=(),
        missed_concepts=(),
        feedback="ok",
    )
    db.commit()

    with pytest.raises(LearningError, match="not finished"):
        c.learning_service.begin_round(USER, session.attempt_id)


def test_rejections_are_stored_bounded_and_count_toward_the_rate_limit(env):
    """A rejected answer is not kept whole and is not free: the oversized text is dropped, the
    relevance telemetry of a non-final rejection is kept, and the submission counts."""
    c, subject, fake = env
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="off_topic"))
    c.settings.max_rejections_per_question = 3
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    question = c.learning_service.begin_round(USER, session.attempt_id)

    too_long = "ozone " * c.settings.max_answer_chars
    first = c.learning_service.submit_answer(
        USER, session.attempt_id, question.attempt_question_id, answer_text=too_long
    )
    assert not first.accepted and first.rejection_reason == "too_long"
    stored = c.attempts.get_question(question.attempt_question_id)
    assert stored.answer_text is None and stored.grade is None and stored.rejections == 1
    assert stored.route == Route.REJECT_JUNK and stored.relevance_band == RelevanceBand.JUNK

    off = c.learning_service.submit_answer(
        USER, session.attempt_id, question.attempt_question_id, answer_text="I love football and pizza"
    )
    assert not off.accepted and off.rejection_reason == "off_topic"
    stored = c.attempts.get_question(question.attempt_question_id)
    assert stored.route == Route.REJECT_OFF_TOPIC and stored.check_verdict == "off_topic"
    assert stored.relevance_band is not None and stored.grade is None and stored.rejections == 2

    # a non-final off-topic rejection still costs a relevance-check call, so it is rate limited
    # (the window counts questions submitted to, and a rejection alone used to count for nothing)
    assert c.attempts.submissions_since_seconds(USER, 60) == 1
    c.settings.max_answers_per_minute = 1
    with pytest.raises(NotAllowed, match="rate"):
        c.learning_service.submit_answer(
            USER, session.attempt_id, question.attempt_question_id, answer_text="pizza again tonight"
        )


def test_a_final_oversized_answer_is_not_persisted(env):
    c, subject, fake = env
    session = c.learning_service.start_part(USER, subject, position=0, language="en")
    question = c.learning_service.begin_round(USER, session.attempt_id)
    too_long = "ozone " * c.settings.max_answer_chars
    for _ in range(c.settings.max_rejections_per_question):
        result = c.learning_service.submit_answer(
            USER, session.attempt_id, question.attempt_question_id, answer_text=too_long
        )
    assert result.grade == Grade.JUNK  # the last rejection scores the question wrong
    stored = c.attempts.get_question(question.attempt_question_id)
    assert stored.answer_text is None  # an answer rejected for its size is never kept
