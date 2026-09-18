from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(database_url: str, *, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    """Pooled connections with dict rows, for the request path. The CLI keeps a single connection."""
    return ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=True,
        kwargs={"row_factory": dict_row},
    )
