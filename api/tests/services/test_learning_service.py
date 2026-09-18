from __future__ import annotations

import pytest

from teachme.container import Container
from teachme.domain.models import Grade, PartStatus, QuestionKind
from teachme.grading.grader import GradeOut
from teachme.grading.relevance_check import RelevanceVerdict
from teachme.services.learning import LearningError, NotAllowed
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
    yield c, subject, fake
    c.close()


def _grade(verdict):
    return lambda req: GradeOut(
        verdict=verdict,
        rubric_covered=[0] if verdict != "incorrect" else [],
        missed_concepts=["m"],
        feedback=f"fb-{verdict}",
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


def test_relevance_routing_junk_offtopic_and_multiple_choice(env):
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
    assert recorded.route.value == "check" and recorded.check_verdict == "off_topic"
    assert recorded.rejections == 2

    # a clearly on-topic answer skips the check and goes to the grader
    fake.set_responder(RelevanceVerdict, lambda req: RelevanceVerdict(verdict="on_topic"))
    nxt = off.next_question
    while nxt is not None and nxt.kind != QuestionKind.MULTIPLE_CHOICE:
        res = c.learning_service.submit_answer(
            USER,
            session.attempt_id,
            nxt.attempt_question_id,
            answer_text="Fake teaching sentence about the topic with fake words",
        )
        nxt = res.next_question
    if nxt is not None:
        res = c.learning_service.submit_answer(
            USER, session.attempt_id, nxt.attempt_question_id, answer_choice=0
        )
        assert res.grade in (Grade.CORRECT, Grade.INCORRECT) and res.accepted
        mc = c.attempts.get_question(nxt.attempt_question_id)
        assert mc.route.value == "code"


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
