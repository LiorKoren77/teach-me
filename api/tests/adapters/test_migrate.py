from __future__ import annotations

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import applied_versions, available_versions, pending_versions


def test_migrations_apply_once_and_are_idempotent(migrated_database):
    conn = connect(migrated_database)
    try:
        assert applied_versions(conn) == available_versions()
        assert pending_versions(conn) == []
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        expected = {"subjects", "sources", "source_pages", "source_figures", "chunks", "jobs", "llm_usage"}
        assert expected <= tables
    finally:
        conn.close()


def test_available_versions_are_sorted_filenames():
    versions = available_versions()
    assert versions == sorted(versions)
    assert versions[0] == "0001_initial"
