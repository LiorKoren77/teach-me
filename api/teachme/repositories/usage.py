from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True)
class UsageRow:
    purpose: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int
    user_id: str | None = None
    subject_id: UUID | None = None
    source_id: UUID | None = None
    attempt_id: UUID | None = None


class UsageRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def insert(self, row: UsageRow) -> None:
        self._conn.execute(
            "INSERT INTO llm_usage (id, purpose, provider, model, input_tokens, output_tokens,"
            " cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, user_id, subject_id,"
            " source_id, attempt_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(),
                row.purpose,
                row.provider,
                row.model,
                row.input_tokens,
                row.output_tokens,
                row.cache_read_tokens,
                row.cache_write_tokens,
                row.cost_usd,
                row.latency_ms,
                row.user_id,
                row.subject_id,
                row.source_id,
                row.attempt_id,
            ),
        )

    def summarize(self, *, subject_id: UUID | None = None) -> list[dict[str, Any]]:
        """Calls, tokens and cost grouped by purpose and model, optionally for one subject."""
        where = "WHERE subject_id = %s" if subject_id else ""
        params = (subject_id,) if subject_id else ()
        rows = self._conn.execute(
            "SELECT purpose, model, count(*) AS calls,"
            " sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,"
            " sum(cache_read_tokens) AS cache_read_tokens, sum(cache_write_tokens) AS cache_write_tokens,"
            " sum(cost_usd) AS cost_usd, avg(latency_ms)::int AS avg_latency_ms"
            f" FROM llm_usage {where} GROUP BY purpose, model ORDER BY purpose, model",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
