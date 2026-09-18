from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from teachme.repositories.errors import JobNotFound


@dataclass(frozen=True)
class ClaimedJob:
    """A job this caller, and no other, is now running. What `claim` hands back: everything the
    dispatcher needs, read out of the same statement that took the row, so nothing it acts on can
    have been written by a delivery that claimed it in between."""

    id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int


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

    def claim(self, job_id: UUID) -> ClaimedJob | None:
        """Take this job for running, or find it already taken. One statement: the row is locked,
        tested and moved to `running` together, so of two deliveries arriving at once exactly one
        is handed the job and a redelivery of a `done` job is handed nothing.

        `failed` is claimable because a retry is how a failed step is resumed; `running` and
        `done` are not, which is what makes the second delivery a no-op instead of a second run."""
        row = self._conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = now()"
            " WHERE id = %s AND status IN ('queued', 'failed')"
            " RETURNING id, kind, payload, attempts",
            (job_id,),
        ).fetchone()
        return None if row is None else ClaimedJob(**row)

    def set_status(self, job_id: UUID, status: str, *, error: str | None = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = %s, error = %s, updated_at = now() WHERE id = %s",
            (status, error, job_id),
        )

    def increment_attempts(self, job_id: UUID) -> None:
        self._conn.execute(
            "UPDATE jobs SET attempts = attempts + 1, updated_at = now() WHERE id = %s", (job_id,)
        )
