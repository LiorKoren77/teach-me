from __future__ import annotations

import random
from dataclasses import dataclass
from uuid import UUID

import psycopg

from teachme.domain.assessment.sampling import sample_round
from teachme.domain.assessment.scoring import round_score, section_weights, weak_sections
from teachme.domain.assessment.transitions import after_round, assert_transition
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


class LearningError(Exception):
    pass


class NotAllowed(LearningError):
    pass


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
        self.d = deps
        self._rng = deps.rng or random.Random()

    # views ----------------------------------------------------------------------------------
    def open_subject(self, user_id: str, subject: Subject) -> SubjectView:
        self._require_published(subject)
        return SubjectView(
            subject_id=subject.id,
            name=subject.name,
            languages=subject.languages,
            parts=self.d.progress_service.parts_with_progress(user_id, subject),
        )

    def start_part(self, user_id: str, subject: Subject, position: int, language: str) -> PartSession:
        """Open a part for reading. Starts (or resumes) an attempt unless the part is already passed."""
        self._require_published(subject)
        if language not in subject.languages:
            raise NotAllowed(f"language {language!r} is not enabled for {subject.name!r}")
        views = self.d.progress_service.parts_with_progress(user_id, subject)
        view = next((v for v in views if v.position == position), None)
        if view is None:
            raise LearningError(f"no part {position}")
        if view.locked:
            raise NotAllowed("previous part not passed yet")
        rendered = self.d.tutorial.rendered_part(subject, language, position)
        progress = self.d.progress.get(user_id, view.part_id)

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

        attempt = self.d.attempts.active(user_id, view.part_id)
        if progress.status in (PartStatus.NOT_STARTED, PartStatus.STALLED) or attempt is None:
            attempt, progress = self._start_attempt(user_id, view.part_id, language, progress)

        current = self.d.attempts.next_unanswered(attempt.id)
        last_round = None
        if current is None and attempt.round_no > 0:
            last_round = self._round_result(attempt, progress.status, progress.rounds_used, subject)
        reexp = (
            self.d.attempts.latest_reexplanation(attempt.id)
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
        assert_transition(progress.status, PartStatus.LEARNING)
        try:
            self.d.progress.update(
                progress.id,
                status=PartStatus.LEARNING,
                rounds_used=0 if progress.status == PartStatus.STALLED else None,
            )
            attempt = self.d.attempts.create(user_id, part_id, language)
            self.d.conn.commit()
        except Exception:
            self.d.conn.rollback()
            raise
        return attempt, self.d.progress.get(user_id, part_id)

    # rounds ---------------------------------------------------------------------------------
    def begin_round(self, user_id: str, attempt_id: UUID) -> QuestionView:
        """Sample the next round's questions, weighted towards the sections just missed."""
        attempt, subject, progress = self._owned_attempt(user_id, attempt_id)
        if self.d.attempts.next_unanswered(attempt.id) is not None:
            raise LearningError("the current round is not finished")
        assert_transition(progress.status, PartStatus.QUIZZING)
        bank = self.d.questions.for_part(attempt.part_id, attempt.language)
        weights: dict[UUID, float] = {}
        if attempt.round_no > 0:
            previous = self.d.attempts.questions_for_round(attempt.id, attempt.round_no)
            weights = section_weights(previous, {q.id: q for q in bank})
        picked = sample_round(
            bank,
            asked=self.d.attempts.asked_question_ids(attempt.id),
            per_round=subject.questions_per_round,
            weights=weights,
            rng=self._rng,
        )
        if not picked:
            raise LearningError("the question bank for this part is exhausted")
        round_no = attempt.round_no + 1
        try:
            self.d.attempts.set_round(attempt.id, round_no)
            rows = self.d.attempts.add_questions(
                attempt.id, round_no=round_no, question_ids=[q.id for q in picked]
            )
            self.d.progress.update(progress.id, status=PartStatus.QUIZZING)
            self.d.conn.commit()
        except Exception:
            self.d.conn.rollback()
            raise
        return self._question_view(self.d.attempts.get(attempt.id), rows[0], subject)

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
        aq = self.d.attempts.get_question(attempt_question_id)
        if aq.attempt_id != attempt.id or aq.grade is not None:
            raise NotAllowed("question is not open for answering")
        if (
            self.d.attempts.answers_since_seconds(user_id, RATE_WINDOW_SECONDS)
            >= self.d.settings.max_answers_per_minute
        ):
            raise NotAllowed("rate limit: too many answers in the last minute")
        question = self.d.questions.get(aq.question_id)
        try:
            with usage_context(subject_id=subject.id, user_id=user_id, attempt_id=attempt.id):
                if question.kind == QuestionKind.MULTIPLE_CHOICE:
                    return self._answer_choice(attempt, subject, progress, aq, question, answer_choice)
                return self._answer_text(attempt, subject, progress, aq, question, answer_text or "")
        except Exception:
            # An attempt is never left half-written: whatever this answer wrote before the failure
            # is discarded, so the question stays open and the student can answer it again.
            self.d.conn.rollback()
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
        if answer_choice is None:
            raise NotAllowed("choose an option")
        grade = Grade.CORRECT if answer_choice == question.correct_choice else Grade.INCORRECT
        feedback = message(attempt.language, "mc_correct" if grade == Grade.CORRECT else "mc_incorrect")
        self.d.attempts.record_answer(
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
        junk_reason = classify_junk(answer, max_chars=self.d.settings.max_answer_chars)
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
        section = self.d.outlines.get_section(question.section_id)
        vocab = self.d.corpus_cache.section_vocabulary(
            subject, corpus, section.page_start, section.page_end, language
        )
        relevance = score_relevance(answer, question, section_vocabulary=vocab, language_code=language)
        route = route_for_band(relevance.band)
        check_verdict = None
        if route == Route.CHECK:
            check_verdict = check_relevance(
                self.d.llm, self.d.settings.model_relevance_check, question, answer, language
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
                    route=Route.CHECK,
                    grade_if_final=Grade.OFF_TOPIC,
                    check_verdict=check_verdict,
                    score=relevance.score,
                )
        evidence = gather_evidence(self.d.hybrid, subject.id, question, language)
        outline = self._outline(subject)
        result = grade_answer(
            self.d.llm,
            self.d.settings.model_grader,
            question,
            answer,
            language,
            self._glossary_view(subject, outline.id),
            evidence,
        )
        self.d.attempts.record_answer(
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

        None when the round left nothing to reinforce: there is no lesson to ask the model for."""
        attempt, subject, progress = self._owned_attempt(user_id, attempt_id)
        if progress.status != PartStatus.REINFORCING:
            raise NotAllowed("re-explanation is available only after a failed round")
        existing = self.d.attempts.latest_reexplanation(attempt.id)
        if existing and existing.round_no == attempt.round_no:
            on_delta(existing.body)
            return existing
        answered = self.d.attempts.questions_for_round(attempt.id, attempt.round_no)
        bank = {q.id: q for q in self.d.questions.for_part(attempt.part_id, attempt.language)}
        cap = self.d.settings.reinforce_sections_cap
        weak_ids = weak_sections(answered, bank, cap=cap)
        weak = set(weak_ids)
        outline = self._outline(subject)
        part = self.d.outlines.get_part(attempt.part_id)
        sections = [s for s in self.d.outlines.sections(part.id) if s.id in weak]
        summaries = [s for s in self.d.content.sections(part.id, attempt.language) if s.section_id in weak]
        wrong = [
            WrongAnswer(
                question=bank[aq.question_id].prompt,
                student_answer=aq.answer_text or "",
                feedback=aq.feedback or "",
            )
            for aq in answered
            if (aq.points or 0.0) < 1.0 and bank[aq.question_id].section_id in weak
        ]
        if not sections:
            return None  # nothing to reinforce: never ask the model to re-teach an empty list
        terms = self.d.glossary.terms(outline.id)
        translations = {t.term_id: t.term for t in self.d.glossary.translations(outline.id, attempt.language)}
        by_slug = {t.slug: translations.get(t.id, t.source_term) for t in terms}
        try:
            with usage_context(subject_id=subject.id, user_id=user_id, attempt_id=attempt.id):
                result = reexplain_sections(
                    self.d.llm,
                    self.d.settings.model_reexplain,
                    subject.name,
                    attempt.language,
                    self._corpus(subject),
                    part,
                    sections,
                    summaries,
                    wrong,
                    terms,
                    by_slug,
                    on_delta=on_delta,
                )
            stored = self.d.attempts.add_reexplanation(
                attempt.id,
                round_no=attempt.round_no,
                section_ids=weak_ids,
                language=attempt.language,
                body=result.text,
                model=result.model,
                truncated=result.truncated,
            )
            self.d.conn.commit()
        except Exception:
            self.d.conn.rollback()
            raise
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
        """An answer that is not an attempt at the question: asked again, until the cap is reached."""
        count = self.d.attempts.increment_rejections(aq.id)
        if count < self.d.settings.max_rejections_per_question:
            self.d.conn.commit()
            current = self._question_view(attempt, self.d.attempts.get_question(aq.id), subject)
            return AnswerResult(
                accepted=False,
                grade=None,
                feedback=message(attempt.language, "rejected"),
                rejection_reason=reason,
                next_question=current,
            )
        feedback = message(attempt.language, "rejected_final")
        self.d.attempts.record_answer(
            aq.id,
            answer_text=answer,
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
        nxt = self.d.attempts.next_unanswered(attempt.id)
        if nxt is not None:
            self.d.conn.commit()
            return AnswerResult(
                accepted=accepted,
                grade=grade,
                feedback=feedback,
                next_question=self._question_view(attempt, nxt, subject),
            )
        answered = self.d.attempts.questions_for_round(attempt.id, attempt.round_no)
        score = round_score(answered)
        rounds_used = progress.rounds_used + 1
        status = after_round(
            score=score,
            threshold=subject.pass_threshold,
            rounds_used=rounds_used,
            max_rounds=subject.max_rounds,
        )
        assert_transition(PartStatus.QUIZZING, status)
        self.d.progress.update(
            progress.id, status=status, best_score=round(score, 4), rounds_used=rounds_used
        )
        if status == PartStatus.PASSED:
            self.d.attempts.finish(attempt.id, AttemptStatus.PASSED)
        elif status == PartStatus.STALLED:
            self.d.attempts.finish(attempt.id, AttemptStatus.FAILED)
        self.d.conn.commit()
        return AnswerResult(
            accepted=accepted,
            grade=grade,
            feedback=feedback,
            round_result=self._round_result(self.d.attempts.get(attempt.id), status, rounds_used, subject),
        )

    def _round_result(
        self, attempt: Attempt, status: PartStatus, rounds_used: int, subject: Subject
    ) -> RoundResult:
        answered = self.d.attempts.questions_for_round(attempt.id, attempt.round_no)
        bank = {q.id: q for q in self.d.questions.for_part(attempt.part_id, attempt.language)}
        weak = set(weak_sections(answered, bank, cap=self.d.settings.reinforce_sections_cap))
        titles = [
            s.title
            for s in self.d.content.sections(attempt.part_id, attempt.language)
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
        question: Question = self.d.questions.get(aq.question_id)
        total = len(self.d.attempts.questions_for_round(attempt.id, aq.round_no))
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
        attempt = self.d.attempts.get(attempt_id)
        if attempt.user_id != user_id:
            raise NotAllowed("not your attempt")
        if attempt.status != AttemptStatus.ACTIVE:
            raise LearningError("attempt is finished")
        part = self.d.outlines.get_part(attempt.part_id)
        outline = self.d.outlines.get(part.outline_id)
        subject = self.d.subjects.get(outline.subject_id)
        self._require_published(subject)
        return attempt, subject, self.d.progress.get(user_id, attempt.part_id)

    @staticmethod
    def _require_published(subject: Subject) -> None:
        if subject.state != SubjectState.PUBLISHED or subject.current_outline_version is None:
            raise NotAllowed(f"subject {subject.name!r} is not published")

    def _outline(self, subject: Subject) -> Outline:
        outline = self.d.outlines.get_version(subject.id, subject.current_outline_version or 0)
        if outline is None:
            raise LearningError("published outline missing")
        return outline

    def _corpus(self, subject: Subject) -> SubjectCorpus:
        return self.d.corpus_cache.corpus(subject, lambda: self.d.tutorial.corpus(subject))

    def _glossary_view(self, subject: Subject, outline_id: UUID) -> GlossaryView:
        return GlossaryView(
            source_language=self._corpus(subject).language,
            source_terms={t.slug: t.source_term for t in self.d.glossary.terms(outline_id)},
        )

    def _render(self, subject: Subject, language: str, text: str) -> str:
        return render_placeholders(
            text,
            self._glossary_view(subject, self._outline(subject).id),
            target_language=language,
            frequency=subject.gloss_frequency,
        )
