from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from uuid import UUID

from teachme.domain.models import Question, QuestionKind


def sample_round(
    bank: Sequence[Question],
    *,
    asked: set[UUID],
    per_round: int,
    weights: Mapping[UUID, float],
    rng: random.Random,
) -> list[Question]:
    """Pick up to per_round unasked questions: one per section first (coverage), then the rest by
    section weight (weak sections get more). Free-text/multiple-choice mix follows the bank's own ratio."""
    remaining = [q for q in bank if q.id not in asked]
    by_section: dict[UUID, list[Question]] = {}
    for q in remaining:
        by_section.setdefault(q.section_id, []).append(q)
    for qs in by_section.values():
        rng.shuffle(qs)

    picked: list[Question] = []
    sections = list(by_section)
    rng.shuffle(sections)
    for section in sections:
        if len(picked) >= per_round:
            break
        picked.append(by_section[section].pop())

    while len(picked) < per_round:
        candidates = [s for s in sections if by_section[s]]
        if not candidates:
            break
        section = rng.choices(candidates, weights=[max(weights.get(s, 1.0), 0.01) for s in candidates])[0]
        picked.append(by_section[section].pop())

    # keep multiple-choice questions at the end of the round so the free-text ones lead
    picked.sort(key=lambda q: (q.kind == QuestionKind.MULTIPLE_CHOICE, q.position))
    return picked
