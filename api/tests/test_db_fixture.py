from __future__ import annotations

from uuid import uuid4

from teachme.adapters.db.engine import connect
from tests.conftest import db as db_fixture


def test_db_fixture_truncates_leftovers_before_yielding(migrated_database):
    """A row committed outside the fixture (e.g. left over from an interrupted
    run) must not be visible to the next test that uses the `db` fixture."""
    leftover_conn = connect(migrated_database)
    try:
        leftover_conn.execute(
            "INSERT INTO subjects (id, name, state, languages) VALUES (%s, %s, %s, %s)",
            (uuid4(), "leftover-from-interrupted-run", "draft", ["en"]),
        )
        leftover_conn.commit()
    finally:
        leftover_conn.close()

    generator = db_fixture.__wrapped__(migrated_database)
    fixture_conn = next(generator)
    try:
        row = fixture_conn.execute("SELECT count(*) AS n FROM subjects").fetchone()
        assert row["n"] == 0
    finally:
        try:
            next(generator)
        except StopIteration:
            pass
