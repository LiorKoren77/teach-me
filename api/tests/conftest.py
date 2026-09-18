from __future__ import annotations

import os
from pathlib import Path

import pytest

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import apply_migrations
from teachme.container import Container
from teachme.settings import Settings

TABLES = [
    "reexplanations",
    "attempt_questions",
    "attempts",
    "part_progress",
    "llm_usage",
    "jobs",
    "questions",
    "section_content",
    "part_content",
    "glossary_translations",
    "glossary_terms",
    "sections",
    "parts",
    "outlines",
    "chunks",
    "source_figures",
    "source_pages",
    "sources",
    "subjects",
]

# A leaked idle-in-transaction connection would otherwise hang the teardown TRUNCATE for as long
# as the test runner lets it; 15s makes that failure fast and loud instead.
_LOCK_TIMEOUT = "SET lock_timeout = '15s'"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; start docker compose and export it")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    conn = connect(test_database_url)
    conn.execute(_LOCK_TIMEOUT)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return test_database_url


@pytest.fixture
def db(migrated_database: str):
    conn = connect(migrated_database)
    conn.execute(_LOCK_TIMEOUT)
    try:
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        conn.commit()
        yield conn
    finally:
        conn.rollback()
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        conn.commit()
        conn.close()


@pytest.fixture
def make_container(migrated_database: str, tmp_path: Path):
    """Builds Containers on the fake stack, closing every one on teardown - even if the test
    raises first - so a failing assertion never leaks a connection into the next test."""
    containers: list[Container] = []

    def factory(**overrides) -> Container:
        base = dict(
            database_url=migrated_database,
            llm_provider="fake",
            embeddings_provider="fake",
            reranker_provider="noop",
            file_store="local",
            local_files_dir=tmp_path / "files",
            digest_dir=tmp_path / "digest",
            write_local_bundle=True,
            job_runner="inprocess",
            enabled_languages=["he", "en", "pt"],
            allowed_upload_types=None,
        )
        base.update(overrides)
        c = Container(Settings(_env_file=None, **base))
        containers.append(c)
        return c

    try:
        yield factory
    finally:
        for c in containers:
            c.close()
