from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def connect(database_url: str, *, autocommit: bool = False) -> psycopg.Connection:
    """One connection, dict rows, explicit commits. Vectors travel as text literals
    ('[0.1,0.2]'::vector) so no type registration is needed.

    autocommit=True is for writes that must not be undone by a caller's rollback, such as
    telemetry rows recorded during a pipeline step that later fails."""
    return psycopg.connect(database_url, row_factory=dict_row, autocommit=autocommit)
