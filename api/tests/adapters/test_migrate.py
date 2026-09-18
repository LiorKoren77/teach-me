from __future__ import annotations

import threading
from uuid import uuid4

import psycopg
import pytest

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import (
    applied_versions,
    apply_migrations,
    available_versions,
    ensure_schema_current,
    pending_versions,
)

_ADVISORY_LOCK_KEY = 7241965


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


def test_apply_migrations_takes_and_releases_a_session_advisory_lock(migrated_database):
    conn = connect(migrated_database)
    executed: list[str] = []
    real_execute = conn.execute

    def spy_execute(query, *args, **kwargs):
        executed.append(query)
        return real_execute(query, *args, **kwargs)

    conn.execute = spy_execute
    try:
        assert apply_migrations(conn) == []
        assert any("pg_advisory_lock" in query and "xact" not in query for query in executed)
        assert any("pg_advisory_unlock" in query for query in executed)
    finally:
        conn.close()


def test_apply_migrations_blocks_while_another_connection_holds_the_lock(migrated_database):
    """The lock must be session-scoped and cover the whole run: it is taken before the
    migrations loop and only released once apply_migrations is completely done, so a second
    connection racing to migrate blocks for as long as the first one holds it."""
    holder = connect(migrated_database)
    holder.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
    holder.commit()

    conn = connect(migrated_database)
    result: list[list[str]] = []

    def run() -> None:
        result.append(apply_migrations(conn))

    thread = threading.Thread(target=run)
    thread.start()
    try:
        thread.join(timeout=1)
        assert thread.is_alive(), "apply_migrations returned before the lock was released"
    finally:
        holder.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
        holder.commit()
        holder.close()

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result == [[]]
    conn.close()


def test_tutorial_tables_exist(migrated_database):
    conn = connect(migrated_database)
    try:
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        assert {
            "outlines",
            "parts",
            "sections",
            "glossary_terms",
            "glossary_translations",
            "part_content",
            "section_content",
            "questions",
        } <= tables
        assert "0002_tutorial" in applied_versions(conn)
    finally:
        conn.close()


def test_gloss_frequency_check_rejects_an_unknown_frequency(db):
    assert "0003_gloss_frequency_check" in applied_versions(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO subjects (id, name, state, languages, gloss_frequency) VALUES (%s, %s, %s, %s, %s)",
            (uuid4(), "bad-frequency", "draft", ["en"], "sometimes"),
        )
    db.rollback()
