from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from teachme.repositories.usage import UsageRepository


class UsageSummaryRow(BaseModel):
    purpose: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    avg_latency_ms: int


class UsageService:
    def __init__(self, usage: UsageRepository) -> None:
        self._usage = usage

    def summary(self, subject_id: UUID | None = None) -> list[UsageSummaryRow]:
        return [UsageSummaryRow.model_validate(row) for row in self._usage.summarize(subject_id=subject_id)]

    @staticmethod
    def format_table(rows: list[UsageSummaryRow]) -> str:
        if not rows:
            return "no usage recorded"
        header = (
            f"{'purpose':<26} {'model':<18} {'calls':>6} {'in':>10} {'out':>9} {'cache_rd':>9} {'usd':>9}"
        )
        lines = [header, "-" * len(header)]
        total = 0.0
        for r in rows:
            total += r.cost_usd
            lines.append(
                f"{r.purpose:<26} {r.model:<18} {r.calls:>6} {r.input_tokens:>10,} {r.output_tokens:>9,}"
                f" {r.cache_read_tokens:>9,} {r.cost_usd:>9.4f}"
            )
        lines.append(f"{'total':<26} {'':<18} {'':>6} {'':>10} {'':>9} {'':>9} {total:>9.4f}")
        return "\n".join(lines)
