from __future__ import annotations

from teachme.adapters.db.pool import make_pool


def test_pool_yields_working_dict_row_connections(migrated_database):
    pool = make_pool(migrated_database, min_size=1, max_size=2)
    try:
        with pool.connection() as conn:
            row = conn.execute("SELECT 1 AS one").fetchone()
            assert row == {"one": 1}
    finally:
        pool.close()
