from __future__ import annotations

from uuid import uuid4

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import (
    applied_versions,
    apply_migrations,
    available_versions,
    ensure_schema_current,
    pending_versions,
)


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


def test_reads_do_not_create_tables_or_commit_callers_transaction(db):
    subject_id = uuid4()
    db.execute(
        "INSERT INTO subjects (id, name, state, languages) VALUES (%s, %s, %s, %s)",
        (subject_id, "uncommitted", "draft", ["en"]),
    )

    pending_versions(db)
    ensure_schema_current(db)
    db.rollback()

    row = db.execute("SELECT 1 FROM subjects WHERE id = %s", (subject_id,)).fetchone()
    assert row is None


def test_applied_versions_and_pending_versions_are_read_only(migrated_database):
    conn = connect(migrated_database)
    try:
        conn.execute("DROP TABLE schema_migrations")
        conn.commit()

        before = conn.execute("SELECT to_regclass('schema_migrations') AS reg").fetchone()["reg"]
        assert before is None

        assert applied_versions(conn) == []
        assert pending_versions(conn) == available_versions()

        after = conn.execute("SELECT to_regclass('schema_migrations') AS reg").fetchone()["reg"]
        assert after is None
    finally:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for version in available_versions():
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (version,),
            )
        conn.commit()
        conn.close()


def test_apply_migrations_takes_an_advisory_lock(migrated_database):
    conn = connect(migrated_database)
    executed: list[str] = []
    real_execute = conn.execute

    def spy_execute(query, *args, **kwargs):
        executed.append(query)
        return real_execute(query, *args, **kwargs)

    conn.execute = spy_execute
    try:
        assert apply_migrations(conn) == []
        assert any("pg_advisory_xact_lock" in query for query in executed)
    finally:
        conn.close()
