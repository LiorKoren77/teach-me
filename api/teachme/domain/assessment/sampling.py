from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from uuid import UUID

from teachme.domain.models import Question, QuestionKind


def sample_round(
    bank: Sequence[Question],
    *,
    asked: AbstractSet[UUID],
    per_round: int,
    weights: Mapping[UUID, float],
    rng: random.Random,
) -> list[Question]:
    """Pick up to per_round questions never asked in this attempt.

    Guaranteed, for a bank that can supply them:
    - no repeats: only questions outside `asked` are drawn;
    - the round's free-text/multiple-choice split mirrors the whole bank's, rounded to whole
      questions, and a bucket that runs dry is topped up from the other one;
    - coverage: within each bucket the first pass takes one question per section, in descending
      section weight, so a weak section is reached even when there are more sections than
      questions in the round; the rng only breaks ties between equal weights;
    - the remaining questions are drawn per section with probability proportional to its weight;
    - free-text questions lead the round and multiple-choice ones close it.

    Deterministic for a seeded rng.
    """
    remaining = [q for q in bank if q.id not in asked]
    if per_round <= 0 or not remaining:
        return []

    mc_of_bank = sum(1 for q in bank if q.kind == QuestionKind.MULTIPLE_CHOICE) / len(bank)
    target_mc = round(per_round * mc_of_bank)

    multiple_choice = _by_section(remaining, QuestionKind.MULTIPLE_CHOICE, rng, keep=True)
    free_text = _by_section(remaining, QuestionKind.MULTIPLE_CHOICE, rng, keep=False)

    picked = _draw(multiple_choice, target_mc, weights, rng)
    picked += _draw(free_text, per_round - len(picked), weights, rng)
    picked += _draw(multiple_choice, per_round - len(picked), weights, rng)  # free text ran dry

    picked.sort(key=lambda q: (q.kind == QuestionKind.MULTIPLE_CHOICE, q.position))
    return picked


def _by_section(
    questions: Sequence[Question], kind: QuestionKind, rng: random.Random, *, keep: bool
) -> dict[UUID, list[Question]]:
    """One shuffled stack per section, holding the questions of that kind (or all the others)."""
    stacks: dict[UUID, list[Question]] = {}
    for question in questions:
        if (question.kind == kind) is keep:
            stacks.setdefault(question.section_id, []).append(question)
    for stack in stacks.values():
        rng.shuffle(stack)
    return stacks


def _draw(
    stacks: dict[UUID, list[Question]],
    target: int,
    weights: Mapping[UUID, float],
    rng: random.Random,
) -> list[Question]:
    """Coverage first (heaviest section first), then weighted draws. Mutates `stacks`."""
    if target <= 0:
        return []
    picked: list[Question] = []
    for section in _heaviest_first(stacks, weights, rng):
        if len(picked) >= target:
            break
        if stacks[section]:
            picked.append(stacks[section].pop())
    while len(picked) < target:
        candidates = [section for section, stack in stacks.items() if stack]
        if not candidates:
            break
        section = rng.choices(candidates, weights=[_weight(weights, s) for s in candidates])[0]
        picked.append(stacks[section].pop())
    return picked


def _heaviest_first(
    stacks: Mapping[UUID, list[Question]], weights: Mapping[UUID, float], rng: random.Random
) -> list[UUID]:
    """Sections by descending weight; the rng decides only between sections of equal weight."""
    ordered = [(-_weight(weights, section), rng.random(), section) for section in stacks]
    ordered.sort()
    return [section for _, _, section in ordered]


def _weight(weights: Mapping[UUID, float], section: UUID) -> float:
    """An unweighted section counts as 1; a non-positive weight never becomes impossible."""
    return max(weights.get(section, 1.0), 0.01)
