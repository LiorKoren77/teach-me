from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from teachme.domain.assessment.sampling import sample_round
from teachme.domain.assessment.scoring import (
    UnmappedQuestion,
    round_score,
    section_weights,
    weak_sections,
)
from teachme.domain.assessment.transitions import IllegalTransition, after_round, assert_transition
from teachme.domain.glossary.render import GlossaryView, render_placeholders
from teachme.domain.models import (
    Attempt,
    AttemptQuestion,
    AttemptStatus,
    Grade,
    Outline,
    PartProgress,
    PartStatus,
    Question,
    QuestionKind,
    Reexplanation,
    RelevanceBand,
    Route,
    Subject,
    SubjectState,
)
from teachme.domain.relevance.junk import classify_junk
from teachme.domain.relevance.router import route_for_band
from teachme.domain.relevance.scorer import score_relevance
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.reexplain import WrongAnswer, reexplain_sections
from teachme.grading.evidence import gather_evidence
from teachme.grading.grader import grade_answer
from teachme.grading.relevance_check import check_relevance
from teachme.ports.llm import LLMProvider, OnDelta
from teachme.repositories.attempts import AttemptRepository
from teachme.repositories.content import ContentRepository
from teachme.repositories.glossary import GlossaryRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.progress import ProgressRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.retrieval.hybrid import HybridSearch
from teachme.services.corpus_cache import CorpusCache
from teachme.services.learning_views import (
    AnswerResult,
    PartSession,
    QuestionView,
    RoundResult,
    SubjectView,
)
from teachme.services.messages import message
from teachme.services.progress import ProgressService
from teachme.services.tutorial import TutorialService
from teachme.settings import Settings
from teachme.telemetry.usage import usage_context

RATE_WINDOW_SECONDS = 60


def _from_bank(bank: dict[UUID, Question], aq: AttemptQuestion) -> Question:
    """The question an answered row answers. `bank[aq.question_id]` raised a bare KeyError when
    the bank was regenerated under an open round, which reached the client as a 500; the round
    scoring already names the row it cannot map, and so does this."""
    question = bank.get(aq.question_id)
    if question is None:
        raise UnmappedQuestion(aq)
    return question


class LearningError(Exception):
    pass


class NotAllowed(LearningError):
    pass


class RateLimited(NotAllowed):
    """Too many submissions in the window. A refusal, but a temporary one: the API answers 429."""


class QuestionClosed(LearningError):
    """The question is not open for answering: it already carries a grade, or it belongs to another
    attempt. A conflict with the state of the round, not an authorization failure - it used to be a
    NotAllowed, and the student who answered twice was told 403 as if the attempt were not theirs.
    """


class InvalidChoice(LearningError):
    """A multiple-choice submission that is not one of the question's options."""


class BankExhausted(LearningError):
    """The attempt has asked every question this part has: the part stalls, it is never locked.

    A fresh attempt starts with an empty asked set, so the whole bank is available again."""


@dataclass(frozen=True, kw_only=True)
class LearningDeps:
    """Everything the learning loop needs, bundled so the state machine keeps one parameter."""

    conn: psycopg.Connection
    settings: Settings
    llm: LLMProvider
    hybrid: HybridSearch
    subjects: SubjectRepository
    outlines: OutlineRepository
    glossary: GlossaryRepository
    content: ContentRepository
    questions: QuestionRepository
    progress: ProgressRepository
    attempts: AttemptRepository
    tutorial: TutorialService
    progress_service: ProgressService
    corpus_cache: CorpusCache
    rng: random.Random | None = None


class LearningService:
    """Tutor asks, student answers. Every transition goes through the domain rules; every model call
    happens at one of three fixed points (relevance check, grading, re-explanation)."""

    def __init__(self, deps: LearningDeps) -> None:
        self._deps = deps
        self._rng = deps.rng or random.Random()

    # views ----------------------------------------------------------------------------------
    def open_subject(self, user_id: str, subject: Subject) -> SubjectView:
        """The subject's parts, and only the languages this deployment enables: the list view
        already filtered them, and a subject view offering a language `start_part` refuses would
        hand the student a language picker with a dead option in it."""
        self._require_published(subject)
        return SubjectView(
            subject_id=subject.id,
            name=subject.name,
            languages=self._offered_languages(subject),
            parts=self._deps.progress_service.parts_with_progress(user_id, subject),
        )

    def _offered_languages(self, subject: Subject) -> tuple[str, ...]:
        enabled = self._deps.settings.enabled_languages
        return tuple(code for code in subject.languages if code in enabled)

    def start_part(self, user_id: str, subject: Subject, position: int, language: str) -> PartSession:
        """Open a part for reading. Starts (or resumes) an attempt unless the part is already passed."""
        self._require_published(subject)
        if language not in self._offered_languages(subject):
            raise NotAllowed(f"language {language!r} is not enabled for {subject.name!r}")
        views = self._deps.progress_service.parts_with_progress(user_id, subject)
        view = next((v for v in views if v.position == position), None)
        if view is None:
            raise LearningError(f"no part {position}")
        if view.locked:
            raise NotAllowed("previous part not passed yet")
        rendered = self._deps.tutorial.rendered_part(subject, language, position)
        progress = self._deps.progress.get(user_id, view.part_id)

        if progress.status == PartStatus.PASSED:
            return PartSession(
                part=rendered,
                status=PartStatus.PASSED,
                attempt_id=None,
                round_no=0,
                current_question=None,
                last_round=None,
                reexplanation=None,
            )

        attempt = self._deps.attempts.active(user_id, view.part_id)
        if progress.status in (PartStatus.NOT_STARTED, PartStatus.STALLED) or attempt is None:
            attempt, progress = self._start_attempt(user_id, view.part_id, language, progress)

        current = self._deps.attempts.next_unanswered(attempt.id)
        last_round = None
        if current is None and attempt.round_no > 0:
            last_round = self._round_result(attempt, progress.status, progress.rounds_used, subject)
        reexp = (
            self._deps.attempts.latest_reexplanation(attempt.id)
            if progress.status == PartStatus.REINFORCING
            else None
        )
        return PartSession(
            part=rendered,
            status=progress.status,
            attempt_id=attempt.id,
            round_no=attempt.round_no,
            current_question=self._question_view(attempt, current, subject) if current else None,
            last_round=last_round,
            reexplanation=self._render(subject, language, reexp.body) if reexp else None,
        )

    def _start_attempt(
        self, user_id: str, part_id: UUID, language: str, progress: PartProgress
    ) -> tuple[Attempt, PartProgress]:
        try:
            assert_transition(progress.status, PartStatus.LEARNING)
        except IllegalTransition as exc:
            # The API layer handles one family: a part that cannot be opened from where it stands
            # is a learning error like any other refusal, not a domain exception of its own.
            raise LearningError(str(exc)) from exc
        try:
            self._deps.progress.update(
                progress.id,
                status=PartStatus.LEARNING,
                rounds_used=0 if progress.status == PartStatus.STALLED else None,
            )
            attempt = self._deps.attempts.create(user_id, part_id, language)
            self._deps.conn.commit()
        except Exception:
            self._deps.conn.rollback()
            raise
        return attempt, self._deps.progress.get(user_id, part_id)

    # rounds ---------------------------------------------------------------------------------
    def begin_round(self, user_id: str, attempt_id: UUID) -> QuestionView:
        """Sample the next round's questions, weighted towards the sections just missed."""
        attempt, subject, progress = self._owned_attempt(user_id, attempt_id)
        if self._deps.attempts.next_unanswered(attempt.id) is not None:
            raise LearningError("the current round is not finished")
        assert_transition(progress.status, PartStatus.QUIZZING)
        bank = self._deps.questions.for_part(attempt.part_id, attempt.language)
        weights: dict[UUID, float] = {}
        if attempt.round_no > 0:
            previous = self._deps.attempts.questions_for_round(attempt.id, attempt.round_no)
            weights = section_weights(previous, {q.id: q for q in bank})
        picked = sample_round(
            bank,
            asked=self._deps.attempts.asked_question_ids(attempt.id),
            per_round=subject.questions_per_round,
            weights=weights,
            rng=self._rng,
        )
        if not picked:
            self._stall_exhausted(attempt, progress)
            raise BankExhausted(
                "the question bank for this part is exhausted; start a fresh attempt to be asked"
                " its questions again"
            )
        round_no = attempt.round_no + 1
        try:
            self._deps.attempts.set_round(attempt.id, round_no)
            try:
                rows = self._deps.attempts.add_questions(
                    attempt.id, round_no=round_no, question_ids=[q.id for q in picked]
                )
            except psycopg.errors.UniqueViolation as exc:
                # attempt_questions is unique on (attempt, round, position): another call already
                # sampled this round, so this one is a duplicate begin_round, not a new round.
                raise LearningError("the current round is not finished") from exc
            self._deps.progress.update(progress.id, status=PartStatus.QUIZZING)
            self._deps.conn.commit()
        except Exception:
            self._deps.conn.rollback()
            raise
        return self._question_view(self._deps.attempts.get(attempt.id), rows[0], subject)

    def _stall_exhausted(self, attempt: Attempt, progress: PartProgress) -> None:
        """Close the attempt rather than leave it active with nothing left to ask: an active
        attempt with an empty bank would hand the student the same finished round forever."""
        assert_transition(progress.status, PartStatus.STALLED)
        try:
            self._deps.progress.update(progress.id, status=PartStatus.STALLED)
            self._deps.attempts.finish(attempt.id, AttemptStatus.FAILED)
            self._deps.conn.commit()
        except Exception:
            self._deps.conn.rollback()
            raise

    def submit_answer(
        self,
        user_id: str,
        attempt_id: UUID,
        attempt_question_id: UUID,
        *,
        answer_text: str | None = None,
        answer_choice: int | None = None,
    ) -> AnswerResult:
        """One answer: junk rules, then the lexical score, then at most one check and one grading."""
        attempt, subject, progress = self._owned_attempt(user_id, attempt_id)
        aq = self._deps.attempts.get_question(attempt_question_id)
        if aq.attempt_id != attempt.id or aq.grade is not None:
            raise QuestionClosed("question is not open for answering")
        if (
            self._deps.attempts.submissions_since_seconds(user_id, RATE_WINDOW_SECONDS)
            >= self._deps.settings.max_answers_per_minute
        ):
            raise RateLimited("rate limit: too many answers in the last minute")
        question = self._deps.questions.get(aq.question_id)
        try:
            with usage_context(subject_id=subject.id, user_id=user_id, attempt_id=attempt.id):
                if question.kind == QuestionKind.MULTIPLE_CHOICE:
                    return self._answer_choice(attempt, subject, progress, aq, question, answer_choice)
                return self._answer_text(attempt, subject, progress, aq, question, answer_text or "")
        except Exception:
            # An attempt is never left half-written: whatever this answer wrote before the failure
            # is discarded, so the question stays open and the student can answer it again.
            self._deps.conn.rollback()
            raise

    def _answer_choice(
        self,
        attempt: Attempt,
        subject: Subject,
        progress: PartProgress,
        aq: AttemptQuestion,
        question: Question,
        answer_choice: int | None,
    ) -> AnswerResult:
        options = len(question.choices or ())
        if answer_choice is None or not 0 <= answer_choice < options:
            # The route already refuses a negative index and a body with no choice at all; this is
            # the upper bound, which only the question knows: an index past the last option would
            # otherwise be stored, and scored wrong, as if the student had chosen something.
            raise InvalidChoice(f"choose one of that question's {options} options")
        grade = Grade.CORRECT if answer_choice == question.correct_choice else Grade.INCORRECT
        feedback = message(attempt.language, "mc_correct" if grade == Grade.CORRECT else "mc_incorrect")
        self._record_answer(
            aq.id,
            answer_text=None,
            answer_choice=answer_choice,
            relevance_score=None,
            band=None,
            route=Route.CODE,
            check_verdict=None,
            grade=grade,
            rubric_covered=(),
            missed_concepts=(),
            feedback=feedback,
        )
        return self._after_answer(attempt, subject, progress, accepted=True, grade=grade, feedback=feedback)

    def _answer_text(
        self,
        attempt: Attempt,
        subject: Subject,
        progress: PartProgress,
        aq: AttemptQuestion,
        question: Question,
        answer: str,
    ) -> AnswerResult:
        language = attempt.language
        junk_reason = classify_junk(answer, max_chars=self._deps.settings.max_answer_chars)
        if junk_reason:
            return self._reject(
                attempt,
                subject,
                progress,
                aq,
                answer,
                reason=junk_reason,
                band=RelevanceBand.JUNK,
                route=Route.REJECT_JUNK,
                grade_if_final=Grade.JUNK,
                check_verdict=None,
            )

        corpus = self._corpus(subject)
        section = self._deps.outlines.get_section(question.section_id)
        vocab = self._deps.corpus_cache.section_vocabulary(
            subject, corpus, section.page_start, section.page_end, language
        )
        relevance = score_relevance(
            answer,
            question,
            section_vocabulary=vocab,
            language_code=language,
            thresholds=self._deps.settings.relevance_thresholds_for(language),
        )
        route = route_for_band(relevance.band)
        check_verdict = None
        if route == Route.CHECK:
            check_verdict = check_relevance(
                self._deps.llm, self._deps.settings.model_relevance_check, question, answer, language
            )
            if check_verdict == "off_topic":
                return self._reject(
                    attempt,
                    subject,
                    progress,
                    aq,
                    answer,
                    reason="off_topic",
                    band=relevance.band,
                    route=Route.REJECT_OFF_TOPIC,
                    grade_if_final=Grade.OFF_TOPIC,
                    check_verdict=check_verdict,
                    score=relevance.score,
                )
        evidence = gather_evidence(self._deps.hybrid, subject.id, question, language)
        outline = self._outline(subject)
        result = grade_answer(
            self._deps.llm,
            self._deps.settings.model_grader,
            question,
            answer,
            language,
            self._glossary_view(subject, outline.id),
            evidence,
        )
        self._record_answer(
            aq.id,
            answer_text=answer,
            answer_choice=None,
            relevance_score=relevance.score,
            band=relevance.band,
            route=route,
            check_verdict=check_verdict,
            grade=result.grade,
            rubric_covered=result.rubric_covered,
            missed_concepts=result.missed_concepts,
            feedback=result.feedback,
        )
        return self._after_answer(
            attempt, subject, progress, accepted=True, grade=result.grade, feedback=result.feedback
        )

    def reexplain(self, user_id: str, attempt_id: UUID, *, on_delta: OnDelta) -> Reexplanation | None:
        """The weak sections of the last failed round, explained again and streamed. Cached per round.

        None when the round left nothing to reinforce: there is no lesson to ask the model for.
        The body is handed back, and streamed, with its glossary placeholders unresolved: the
        route renders them for the reader's language, the way start_part renders a part body."""
        attempt, subject, progress = self._owned_attempt(user_id, attempt_id)
        if progress.status != PartStatus.REINFORCING:
            raise NotAllowed("re-explanation is available only after a failed round")
        # Two requests for the same round would both find no stored re-explanation and both pay
        # for an Opus call. The attempt row is taken for update first, so the second one waits
        # here and then finds the row the first committed. The lock is held until this
        # transaction ends, which is why the cached path commits before returning.
        self._deps.attempts.lock_for_update(attempt.id)
        existing = self._deps.attempts.latest_reexplanation(attempt.id)
        if existing and existing.round_no == attempt.round_no:
            self._deps.conn.commit()
            on_delta(existing.body)
            return existing
        answered = self._deps.attempts.questions_for_round(attempt.id, attempt.round_no)
        bank = {q.id: q for q in self._deps.questions.for_part(attempt.part_id, attempt.language)}
        cap = self._deps.settings.reinforce_sections_cap
        weak_ids = weak_sections(answered, bank, cap=cap)
        weak = set(weak_ids)
        outline = self._outline(subject)
        part = self._deps.outlines.get_part(attempt.part_id)
        sections = [s for s in self._deps.outlines.sections(part.id) if s.id in weak]
        summaries = [
            s for s in self._deps.content.sections(part.id, attempt.language) if s.section_id in weak
        ]
        wrong = [
            WrongAnswer(
                question=_from_bank(bank, aq).prompt,
                student_answer=aq.answer_text or "",
                feedback=aq.feedback or "",
            )
            for aq in answered
            if (aq.points or 0.0) < 1.0 and _from_bank(bank, aq).section_id in weak
        ]
        if not sections:
            self._deps.conn.commit()  # releases the attempt row
            return None  # nothing to reinforce: never ask the model to re-teach an empty list
        terms = self._deps.glossary.terms(outline.id)
        translations = {
            t.term_id: t.term for t in self._deps.glossary.translations(outline.id, attempt.language)
        }
        by_slug = {t.slug: translations.get(t.id, t.source_term) for t in terms}
        try:
            with usage_context(subject_id=subject.id, user_id=user_id, attempt_id=attempt.id):
                result = reexplain_sections(
                    llm=self._deps.llm,
                    model=self._deps.settings.model_reexplain,
                    subject_name=subject.name,
                    language=attempt.language,
                    corpus=self._corpus(subject),
                    part=part,
                    sections=sections,
                    summaries=summaries,
                    wrong=wrong,
                    terms=terms,
                    translations=by_slug,
                    on_delta=on_delta,
                )
            stored = self._store_reexplanation(attempt, weak_ids, result)
        except Exception:
            self._deps.conn.rollback()
            raise
        return stored

    def _store_reexplanation(self, attempt: Attempt, section_ids: list[UUID], result) -> Reexplanation:
        """The generated re-explanation, committed - or, if another caller got there first, the
        one that caller committed.

        reexplanations is unique on (attempt, round). The row lock in `reexplain` means a second
        caller normally never reaches this insert; if one does, its own text is dropped rather
        than the request failing, because the student is owed the round's re-explanation and not
        a particular copy of it."""
        try:
            stored = self._deps.attempts.add_reexplanation(
                attempt.id,
                round_no=attempt.round_no,
                section_ids=section_ids,
                language=attempt.language,
                body=result.text,
                model=result.model,
                truncated=result.truncated,
            )
        except psycopg.errors.UniqueViolation:
            self._deps.conn.rollback()
            existing = self._deps.attempts.latest_reexplanation(attempt.id)
            if existing is None or existing.round_no != attempt.round_no:
                raise
            return existing
        self._deps.conn.commit()
        return stored

    def render_text(self, subject: Subject, language: str, text: str) -> str:
        """Glossary placeholders resolved the way the part body resolves them."""
        return self._render(subject, language, text)

    # internals ------------------------------------------------------------------------------
    def _reject(
        self,
        attempt: Attempt,
        subject: Subject,
        progress: PartProgress,
        aq: AttemptQuestion,
        answer: str,
        *,
        reason: str,
        band: RelevanceBand,
        route: Route,
        grade_if_final: Grade,
        check_verdict: str | None,
        score: float | None = None,
    ) -> AnswerResult:
        """An answer that is not an attempt at the question: asked again, until the cap is reached.

        Every rejection is recorded - it counts towards the rate limit and carries the band, the
        route and the check verdict that rejected it - but the text itself is only kept bounded:
        an answer rejected for its size is not stored at all."""
        count = self._deps.attempts.record_rejection(
            aq.id,
            relevance_score=score,
            band=band,
            route=route,
            check_verdict=check_verdict,
        )
        if count == 0:
            raise QuestionClosed("question is not open for answering")
        if count < self._deps.settings.max_rejections_per_question:
            self._deps.conn.commit()
            current = self._question_view(attempt, self._deps.attempts.get_question(aq.id), subject)
            return AnswerResult(
                accepted=False,
                grade=None,
                feedback=message(attempt.language, "rejected"),
                rejection_reason=reason,
                next_question=current,
            )
        feedback = message(attempt.language, "rejected_final")
        bounded = None if reason == "too_long" else answer[: self._deps.settings.max_answer_chars]
        self._record_answer(
            aq.id,
            answer_text=bounded,
            answer_choice=None,
            relevance_score=score,
            band=band,
            route=route,
            check_verdict=check_verdict,
            grade=grade_if_final,
            rubric_covered=(),
            missed_concepts=(),
            feedback=feedback,
        )
        result = self._after_answer(
            attempt, subject, progress, accepted=False, grade=grade_if_final, feedback=feedback
        )
        result.rejection_reason = reason
        return result

    def _record_answer(self, attempt_question_id: UUID, **fields: Any) -> None:
        """Answering is read, then model call, then write, and the write is what decides the race:
        a question another submission has graded in the meantime is refused, not overwritten."""
        if self._deps.attempts.record_answer(attempt_question_id, **fields) == 0:
            raise QuestionClosed("question is not open for answering")

    def _after_answer(
        self,
        attempt: Attempt,
        subject: Subject,
        progress: PartProgress,
        *,
        accepted: bool,
        grade: Grade,
        feedback: str,
    ) -> AnswerResult:
        """Hand over the next question, or close the round: score it and move the part's status."""
        nxt = self._deps.attempts.next_unanswered(attempt.id)
        if nxt is not None:
            self._deps.conn.commit()
            return AnswerResult(
                accepted=accepted,
                grade=grade,
                feedback=feedback,
                next_question=self._question_view(attempt, nxt, subject),
            )
        answered = self._deps.attempts.questions_for_round(attempt.id, attempt.round_no)
        score = round_score(answered)
        rounds_used = progress.rounds_used + 1
        status = after_round(
            score=score,
            threshold=subject.pass_threshold,
            rounds_used=rounds_used,
            max_rounds=subject.max_rounds,
        )
        assert_transition(progress.status, status)
        self._deps.progress.update(
            progress.id, status=status, best_score=round(score, 4), rounds_used=rounds_used
        )
        if status == PartStatus.PASSED:
            self._deps.attempts.finish(attempt.id, AttemptStatus.PASSED)
        elif status == PartStatus.STALLED:
            self._deps.attempts.finish(attempt.id, AttemptStatus.FAILED)
        self._deps.conn.commit()
        return AnswerResult(
            accepted=accepted,
            grade=grade,
            feedback=feedback,
            round_result=self._round_result(
                self._deps.attempts.get(attempt.id), status, rounds_used, subject
            ),
        )

    def _round_result(
        self, attempt: Attempt, status: PartStatus, rounds_used: int, subject: Subject
    ) -> RoundResult:
        answered = self._deps.attempts.questions_for_round(attempt.id, attempt.round_no)
        bank = {q.id: q for q in self._deps.questions.for_part(attempt.part_id, attempt.language)}
        weak = set(weak_sections(answered, bank, cap=self._deps.settings.reinforce_sections_cap))
        titles = [
            s.title
            for s in self._deps.content.sections(attempt.part_id, attempt.language)
            if s.section_id in weak
        ]
        score = round_score(answered)
        return RoundResult(
            round_no=attempt.round_no,
            score=round(score, 4),
            passed=status == PartStatus.PASSED,
            status=status,
            rounds_left=max(subject.max_rounds - rounds_used, 0),
            weak_section_titles=titles,
        )

    def _question_view(self, attempt: Attempt, aq: AttemptQuestion, subject: Subject) -> QuestionView:
        question: Question = self._deps.questions.get(aq.question_id)
        total = len(self._deps.attempts.questions_for_round(attempt.id, aq.round_no))
        return QuestionView(
            attempt_question_id=aq.id,
            question_id=question.id,
            position=aq.position,
            round_no=aq.round_no,
            total_in_round=total,
            kind=question.kind,
            prompt=self._render(subject, attempt.language, question.prompt),
            choices=(
                tuple(self._render(subject, attempt.language, c) for c in question.choices)
                if question.choices
                else None
            ),
        )

    def _owned_attempt(self, user_id: str, attempt_id: UUID) -> tuple[Attempt, Subject, PartProgress]:
        attempt = self._deps.attempts.get(attempt_id)
        if attempt.user_id != user_id:
            raise NotAllowed("not your attempt")
        if attempt.status != AttemptStatus.ACTIVE:
            raise LearningError("attempt is finished")
        part = self._deps.outlines.get_part(attempt.part_id)
        outline = self._deps.outlines.get(part.outline_id)
        subject = self._deps.subjects.get(outline.subject_id)
        self._require_published(subject)
        return attempt, subject, self._deps.progress.get(user_id, attempt.part_id)

    @staticmethod
    def _require_published(subject: Subject) -> None:
        if subject.state != SubjectState.PUBLISHED or subject.current_outline_version is None:
            raise NotAllowed(f"subject {subject.name!r} is not published")

    def _outline(self, subject: Subject) -> Outline:
        outline = self._deps.outlines.get_version(subject.id, subject.current_outline_version or 0)
        if outline is None:
            raise LearningError("published outline missing")
        return outline

    def _corpus(self, subject: Subject) -> SubjectCorpus:
        return self._deps.corpus_cache.corpus(subject, lambda: self._deps.tutorial.corpus(subject))

    def _glossary_view(self, subject: Subject, outline_id: UUID) -> GlossaryView:
        return GlossaryView(
            source_language=self._corpus(subject).language,
            source_terms={t.slug: t.source_term for t in self._deps.glossary.terms(outline_id)},
        )

    def _render(self, subject: Subject, language: str, text: str) -> str:
        return render_placeholders(
            text,
            self._glossary_view(subject, self._outline(subject).id),
            target_language=language,
            frequency=subject.gloss_frequency,
        )
