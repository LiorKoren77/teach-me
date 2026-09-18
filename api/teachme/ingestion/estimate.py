from __future__ import annotations

from pydantic import BaseModel

from teachme.telemetry.prices import PriceTable

# Rough per-page figures for a dense textbook page read as a PDF document block (text + image)
# and then re-emitted as Markdown, followed by contextual chunking of that text.
READ_INPUT_PER_PAGE = 2500
READ_OUTPUT_PER_PAGE = 700
CHUNK_INPUT_PER_PAGE = 1200
CHUNK_OUTPUT_PER_PAGE = 900


class IngestEstimate(BaseModel):
    page_count: int
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def describe(self) -> str:
        return (
            f"{self.page_count} pages via {self.model}: about {self.input_tokens:,} input and "
            f"{self.output_tokens:,} output tokens, roughly ${self.cost_usd:.2f}"
        )


def estimate_ingest(*, page_count: int, model: str, prices: PriceTable) -> IngestEstimate:
    input_tokens = page_count * (READ_INPUT_PER_PAGE + CHUNK_INPUT_PER_PAGE)
    output_tokens = page_count * (READ_OUTPUT_PER_PAGE + CHUNK_OUTPUT_PER_PAGE)
    price = prices.price_for(model)
    cost = 0.0
    if price is not None:
        cost = (input_tokens * price.input_per_m + output_tokens * price.output_per_m) / 1_000_000
    return IngestEstimate(
        page_count=page_count,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )
