from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class AdminActionRow:
    id: UUID
    user_id: str
    action: str
    subject_id: UUID | None
    source_id: UUID | None
    detail: dict[str, Any]
    created_at: datetime


class AdminActionRepository:
    """The admin audit trail: one row per write an admin makes, and the counter the upload cap is
    measured with. Written on the connection of the request it describes, so it is committed by
    the same transaction as the change and rolled back with a refusal."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(
        self,
        *,
        user_id: str,
        action: str,
        subject_id: UUID | None = None,
        source_id: UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> UUID:
        action_id = uuid4()
        self._conn.execute(
            "INSERT INTO admin_actions (id, user_id, action, subject_id, source_id, detail)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (action_id, user_id, action, subject_id, source_id, Jsonb(detail or {})),
        )
        return action_id

    def list(self, *, subject_id: UUID | None = None, limit: int = 50) -> list[AdminActionRow]:
        """The most recent actions, newest first, optionally for one subject."""
        where = "WHERE subject_id = %s" if subject_id is not None else ""
        params = (subject_id, limit) if subject_id is not None else (limit,)
        rows = self._conn.execute(
            "SELECT id, user_id, action, subject_id, source_id, detail, created_at"
            f" FROM admin_actions {where} ORDER BY created_at DESC LIMIT %s",
            params,
        ).fetchall()
        return [AdminActionRow(**row) for row in rows]

    def count_since(self, *, user_id: str, action: str, seconds: int) -> int:
        """How many of these this admin has made in the last `seconds`. What the upload cap is:
        one admin's own recent uploads, not the deployment's."""
        row = self._conn.execute(
            "SELECT count(*) AS n FROM admin_actions"
            " WHERE user_id = %s AND action = %s AND created_at > now() - make_interval(secs => %s)",
            (user_id, action, seconds),
        ).fetchone()
        return int(row["n"])
