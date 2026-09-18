from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from teachme.repositories.errors import JobNotFound


class JobRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, kind: str, payload: dict[str, Any]) -> UUID:
        job_id = uuid4()
        self._conn.execute(
            "INSERT INTO jobs (id, kind, payload, status) VALUES (%s, %s, %s, 'queued')",
            (job_id, kind, Jsonb(payload)),
        )
        return job_id

    def get(self, job_id: UUID) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT id, kind, payload, status, attempts, error, result FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return dict(row)

    def set_result(self, job_id: UUID, result: dict[str, Any]) -> None:
        """What this job decided, kept for a redelivery of the same message to reuse. Written as
        soon as the decision is made rather than when the job finishes, so a delivery that dies
        half way through still hands its successor the same answer."""
        self._conn.execute(
            "UPDATE jobs SET result = %s, updated_at = now() WHERE id = %s", (Jsonb(result), job_id)
        )

    def has_done(self, kind: str, payload: dict[str, Any]) -> bool:
        """Whether this exact job - same kind, same payload - has already run to completion. What
        a redelivered fan-out asks before enqueuing a unit a previous delivery already finished."""
        row = self._conn.execute(
            "SELECT 1 AS found FROM jobs WHERE kind = %s AND payload = %s AND status = 'done' LIMIT 1",
            (kind, Jsonb(payload)),
        ).fetchone()
        return row is not None

    def set_status(self, job_id: UUID, status: str, *, error: str | None = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = %s, error = %s, updated_at = now() WHERE id = %s",
            (status, error, job_id),
        )

    def increment_attempts(self, job_id: UUID) -> None:
        self._conn.execute(
            "UPDATE jobs SET attempts = attempts + 1, updated_at = now() WHERE id = %s", (job_id,)
        )
