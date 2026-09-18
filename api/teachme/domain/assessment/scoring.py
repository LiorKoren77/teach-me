from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from teachme.domain.models import AttemptQuestion, Question


def round_score(answered: Sequence[AttemptQuestion]) -> float:
    """Correct 1, partial 0.5, everything else 0, over the questions asked in the round."""
    if not answered:
        return 0.0
    return sum(aq.points or 0.0 for aq in answered) / len(answered)


def weak_sections(
    answered: Sequence[AttemptQuestion],
    questions: Mapping[UUID, Question],
    *,
    cap: int,
    min_loss: float = 1.0,
) -> list[UUID]:
    """Sections ordered by points lost, keeping those that lost at least min_loss, at most cap."""
    lost: dict[UUID, float] = {}
    for aq in answered:
        section = questions[aq.question_id].section_id
        lost[section] = lost.get(section, 0.0) + (1.0 - (aq.points or 0.0))
    ranked = sorted((s for s, loss in lost.items() if loss >= min_loss), key=lambda s: (-lost[s], str(s)))
    return ranked[:cap]


def section_weights(
    answered: Sequence[AttemptQuestion], questions: Mapping[UUID, Question]
) -> dict[UUID, float]:
    """1 + points lost per section: the sampling weight for the next round."""
    weights: dict[UUID, float] = {}
    for aq in answered:
        section = questions[aq.question_id].section_id
        weights[section] = weights.get(section, 1.0) + (1.0 - (aq.points or 0.0))
    return weights
