from __future__ import annotations

from teachme.domain.models import PartStatus

_ALLOWED: dict[PartStatus, frozenset[PartStatus]] = {
    PartStatus.NOT_STARTED: frozenset({PartStatus.LEARNING}),
    # STALLED from LEARNING or REINFORCING is the exhausted-bank exit: there is nothing left to
    # ask in this attempt, and a stalled part can always be started over.
    PartStatus.LEARNING: frozenset({PartStatus.LEARNING, PartStatus.QUIZZING, PartStatus.STALLED}),
    PartStatus.QUIZZING: frozenset({PartStatus.PASSED, PartStatus.REINFORCING, PartStatus.STALLED}),
    PartStatus.REINFORCING: frozenset({PartStatus.QUIZZING, PartStatus.STALLED}),
    PartStatus.STALLED: frozenset({PartStatus.LEARNING}),
    PartStatus.PASSED: frozenset(),
}


class IllegalTransition(Exception):
    def __init__(self, current: PartStatus, target: PartStatus) -> None:
        super().__init__(f"cannot move part from {current.value} to {target.value}")


def assert_transition(current: PartStatus, target: PartStatus) -> None:
    if target not in _ALLOWED[current]:
        raise IllegalTransition(current, target)


def after_round(*, score: float, threshold: int, rounds_used: int, max_rounds: int) -> PartStatus:
    """score in [0,1]; threshold in percent. Pass at or above; otherwise reinforce while rounds remain.

    The range is checked rather than trusted: a percent passed where a fraction belongs would
    pass every part, and a negative score would stall every one.
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be a fraction in [0, 1], got {score}")
    if score * 100 >= threshold:
        return PartStatus.PASSED
    if rounds_used >= max_rounds:
        return PartStatus.STALLED
    return PartStatus.REINFORCING
