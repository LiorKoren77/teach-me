from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import MIGRATIONS_DIR, SchemaOutOfDate, available_versions
from teachme.app import create_app

STALE_DATABASE = "teachme_stale_schema"


def _drop(admin, name: str) -> None:
    # FORCE: the pool of a failed startup may still hold a connection to the scratch database.
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def stale_database_url(test_database_url: str):
    """A scratch database carrying every migration but the last one: what a deployment looks
    like when the code is ahead of the database."""
    admin = connect(test_database_url, autocommit=True)
    try:
        _drop(admin, STALE_DATABASE)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(STALE_DATABASE)))
    finally:
        admin.close()
    url = make_conninfo(test_database_url, dbname=STALE_DATABASE)
    conn = connect(url)
    try:
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for version in available_versions()[:-1]:
            conn.execute((MIGRATIONS_DIR / f"{version}.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()
    finally:
        conn.close()
    yield url
    admin = connect(test_database_url, autocommit=True)
    try:
        _drop(admin, STALE_DATABASE)
    finally:
        admin.close()


def test_startup_refuses_to_serve_on_a_schema_mismatch(stale_database_url, make_container):
    """An API serving a database that is behind would fail per request, in whatever half-broken
    way the missing table happens to break; startup refuses instead."""
    app = create_app(make_container(database_url=stale_database_url))
    with pytest.raises(SchemaOutOfDate) as info:
        with TestClient(app):
            pass
    assert info.value.pending == available_versions()[-1:]


def test_startup_succeeds_on_a_current_schema(db, make_container):
    app = create_app(make_container())
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
