from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.ports.llm import LLMUsage
from teachme.repositories.usage import UsageRepository, UsageRow
from teachme.telemetry.prices import PriceTable


class UsageContext(BaseModel):
    """Who and what a call was for. Set by services, read by the recorder."""

    model_config = ConfigDict(frozen=True)

    subject_id: UUID | None = None
    source_id: UUID | None = None
    user_id: str | None = None
    attempt_id: UUID | None = None


# UsageContext is frozen/immutable, so sharing this single instance as the ContextVar default
# is safe despite ruff's general warning against mutable defaults.
_DEFAULT_USAGE_CONTEXT = UsageContext()
_current: ContextVar[UsageContext] = ContextVar("teachme_usage_context", default=_DEFAULT_USAGE_CONTEXT)


def current_usage_context() -> UsageContext:
    return _current.get()


@contextmanager
def usage_context(**fields: object) -> Iterator[None]:
    """Nest freely; inner fields override, everything else is inherited."""
    merged = _current.get().model_copy(update=fields)
    token = _current.set(merged)
    try:
        yield
    finally:
        _current.reset(token)


class UsageRecorder:
    def __init__(self, repo: UsageRepository, prices: PriceTable) -> None:
        self._repo = repo
        self._prices = prices

    def record_llm(
        self, *, purpose: str, provider: str, model: str, usage: LLMUsage, latency_ms: int
    ) -> UsageRow:
        row = self._row(
            purpose=purpose,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=self._prices.cost_llm(model, usage),
        )
        self._repo.insert(row)
        return row

    def record_embedding(
        self, *, purpose: str, provider: str, model: str, tokens: int, latency_ms: int
    ) -> UsageRow:
        row = self._row(
            purpose=purpose,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            input_tokens=tokens,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=self._prices.cost_tokens(model, tokens),
        )
        self._repo.insert(row)
        return row

    @staticmethod
    def _row(**fields: object) -> UsageRow:
        ctx = current_usage_context()
        return UsageRow(
            user_id=ctx.user_id,
            subject_id=ctx.subject_id,
            source_id=ctx.source_id,
            attempt_id=ctx.attempt_id,
            **fields,  # type: ignore[arg-type]
        )
