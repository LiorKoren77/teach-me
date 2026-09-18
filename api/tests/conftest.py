from __future__ import annotations

import os

import pytest

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import apply_migrations

TABLES = ["llm_usage", "jobs", "chunks", "source_figures", "source_pages", "sources", "subjects"]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; start docker compose and export it")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    conn = connect(test_database_url)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return test_database_url


@pytest.fixture
def db(migrated_database: str):
    conn = connect(migrated_database)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        conn.commit()
        conn.close()
