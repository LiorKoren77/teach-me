from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from teachme.ports.llm import LLMUsage

log = logging.getLogger(__name__)


class ModelPrice(BaseModel):
    """USD per million tokens."""

    model_config = ConfigDict(frozen=True)

    input_per_m: float
    output_per_m: float
    cache_read_per_m: float = 0.0
    cache_write_per_m: float = 0.0


# Anthropic first-party rates as of 2026-06. Voyage rates: verify at voyageai.com/pricing and
# override through PriceTable(prices=...) if they differ; they are small relative to Claude.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(
        input_per_m=5.0, output_per_m=25.0, cache_read_per_m=0.5, cache_write_per_m=6.25
    ),
    "claude-sonnet-5": ModelPrice(
        input_per_m=2.0, output_per_m=10.0, cache_read_per_m=0.2, cache_write_per_m=2.5
    ),
    "claude-haiku-4-5": ModelPrice(
        input_per_m=1.0, output_per_m=5.0, cache_read_per_m=0.1, cache_write_per_m=1.25
    ),
    "voyage-4": ModelPrice(input_per_m=0.12, output_per_m=0.0),
    "rerank-2.5": ModelPrice(input_per_m=0.05, output_per_m=0.0),
    "fake-model": ModelPrice(input_per_m=0.0, output_per_m=0.0),
    "fake-embed": ModelPrice(input_per_m=0.0, output_per_m=0.0),
}


class PriceTable:
    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = dict(prices) if prices is not None else dict(DEFAULT_PRICES)
        self._warned: set[str] = set()

    def price_for(self, model: str) -> ModelPrice | None:
        price = self._prices.get(model)
        if price is None and model not in self._warned:
            log.warning("no price configured for model %r; recording cost 0", model)
            self._warned.add(model)
        return price

    def cost_llm(self, model: str, usage: LLMUsage) -> float:
        price = self.price_for(model)
        if price is None:
            return 0.0
        return (
            usage.input_tokens * price.input_per_m
            + usage.output_tokens * price.output_per_m
            + usage.cache_read_tokens * price.cache_read_per_m
            + usage.cache_write_tokens * price.cache_write_per_m
        ) / 1_000_000

    def cost_tokens(self, model: str, tokens: int) -> float:
        price = self.price_for(model)
        return 0.0 if price is None else tokens * price.input_per_m / 1_000_000
