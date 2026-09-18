from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def connect(database_url: str) -> psycopg.Connection:
    """One connection, dict rows, explicit commits. Vectors travel as text literals
    ('[0.1,0.2]'::vector) so no type registration is needed."""
    return psycopg.connect(database_url, row_factory=dict_row)
