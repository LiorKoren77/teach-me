from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from teachme.domain.models import AttemptQuestion, Question

DEFAULT_MIN_LOSS = 0.5
"""Half a point - one partial answer - is already worth reinforcing."""


class UnmappedQuestion(LookupError):
    """An answered question missing from the bank mapping the caller passed in.

    Names the attempt question, so the row that cannot be scored is identifiable, instead of
    surfacing as a bare KeyError on a question id somewhere under the round score.
    """

    def __init__(self, attempt_question: AttemptQuestion) -> None:
        super().__init__(
            f"attempt question {attempt_question.id} answers question"
            f" {attempt_question.question_id}, which is not in the bank"
        )
        self.attempt_question_id = attempt_question.id
        self.question_id = attempt_question.question_id


def _points(attempt_question: AttemptQuestion) -> float:
    """An unanswered question scores nothing: None is a whole point lost, not a missing value."""
    points = attempt_question.points
    return 0.0 if points is None else points


def round_score(answered: Sequence[AttemptQuestion]) -> float:
    """Correct 1, partial 0.5, everything else 0, over the questions asked in the round."""
    if not answered:
        return 0.0
    return sum(_points(aq) for aq in answered) / len(answered)


def _loss_per_section(
    answered: Sequence[AttemptQuestion], questions: Mapping[UUID, Question]
) -> dict[UUID, float]:
    lost: dict[UUID, float] = {}
    for aq in answered:
        question = questions.get(aq.question_id)
        if question is None:
            raise UnmappedQuestion(aq)
        lost[question.section_id] = lost.get(question.section_id, 0.0) + (1.0 - _points(aq))
    return lost


def weak_sections(
    answered: Sequence[AttemptQuestion],
    questions: Mapping[UUID, Question],
    *,
    cap: int,
    min_loss: float = DEFAULT_MIN_LOSS,
) -> list[UUID]:
    """Sections ordered by points lost, keeping those that lost at least min_loss, at most cap.

    A round that lost anything at all always yields at least one section: when nothing clears
    min_loss the sections that did lose ground are returned anyway, so a failed round is never
    reinforced with an empty list. Only an all-correct round comes back empty.
    """
    lost = _loss_per_section(answered, questions)
    ranked = sorted((s for s, loss in lost.items() if loss > 0.0), key=lambda s: (-lost[s], str(s)))
    strict = [section for section in ranked if lost[section] >= min_loss]
    return (strict or ranked)[:cap]


def section_weights(
    answered: Sequence[AttemptQuestion], questions: Mapping[UUID, Question]
) -> dict[UUID, float]:
    """1 + points lost per section: the sampling weight for the next round."""
    return {section: 1.0 + loss for section, loss in _loss_per_section(answered, questions).items()}
