from __future__ import annotations

from teachme.domain.models import RelevanceBand, Route

_ROUTES = {
    RelevanceBand.JUNK: Route.REJECT_JUNK,
    RelevanceBand.HIGH: Route.GRADER,
    RelevanceBand.UNCERTAIN: Route.CHECK,
    RelevanceBand.LOW: Route.CHECK,
}


def route_for_band(band: RelevanceBand) -> Route:
    """Lexical score alone never rejects a real attempt: everything below HIGH gets the model check."""
    return _ROUTES[band]
