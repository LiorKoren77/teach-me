from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from teachme.adapters.db.pool import make_pool
from teachme.ports.llm import ContentPart, StructuredRequest
from teachme.repositories.jobs import JobRepository
from teachme.scope import Scope


class Out(BaseModel):
    ok: bool


def test_container_delegates_to_its_default_scope(db, make_container):
    c = make_container()
    assert c.subjects is c.scope.subjects
    assert c.pipeline is c.scope.pipeline
    assert c.scope.conn is c.conn


def test_thumbnail_service_uses_the_configured_width(db, make_container):
    c = make_container(thumbnail_width=64)
    assert c.scope.thumbnail_service.key(uuid4(), 0).endswith("-w64.png")


def test_request_scope_uses_pooled_connection_and_usage_rows_are_durable(db, make_container):
    c = make_container()
    with c.request_scope() as scope:
        assert scope.conn is not c.conn
        scope.subject_service.get_or_create("Scoped", ["he"])
        c.llm.inner.set_responder(Out, lambda req: Out(ok=True))
        c.llm.generate_structured(
            StructuredRequest(
                purpose="scope.test",
                model="fake-model",
                system="s",
                parts=(ContentPart.of_text("x"),),
            ),
            Out,
        )
        scope.conn.commit()
    assert any(r["purpose"] == "scope.test" for r in c.usage_repo.summarize())
    # the pool exists now, so the container's own repositories are reached through its CLI scope
    assert c.scope.subjects.get_by_name("Scoped") is not None


def test_request_scope_rolls_back_on_error(db, make_container):
    c = make_container()
    with pytest.raises(RuntimeError):
        with c.request_scope() as scope:
            scope.subjects.create("Rolled", ["he"])
            raise RuntimeError("boom")
    assert c.scope.subjects.get_by_name("Rolled") is None


def test_every_exit_path_returns_the_connection_to_the_pool(db, make_container, migrated_database):
    """A single-connection pool: a scope that leaked its connection would make the next one
    wait for the pool timeout instead of being served immediately."""
    c = make_container()
    c.__dict__["pool"] = make_pool(migrated_database, min_size=1, max_size=1)
    for _ in range(2):
        with c.request_scope() as scope:
            scope.subjects.list()
        with pytest.raises(RuntimeError):
            with c.request_scope() as scope:
                scope.subjects.create("Leaky", ["he"])
                raise RuntimeError("boom")
    with c.request_scope() as scope:
        assert scope.subjects.get_by_name("Leaky") is None
    stats = c.pool.get_stats()
    assert stats["pool_size"] == 1 and stats.get("requests_waiting", 0) == 0


def test_mark_job_failed_does_not_compete_for_a_pooled_connection(db, make_container, migrated_database):
    """The POST that failed runs on a thread of its own, long after the request that started it
    has its pooled connection back - or, as here, while the request still holds the only one.
    Waiting for the pool would mean the failure is never recorded, so a connection of its own is
    opened, used and closed."""
    container = make_container()
    container.__dict__["pool"] = ConnectionPool(
        migrated_database, min_size=1, max_size=1, open=True, timeout=1, kwargs={"row_factory": dict_row}
    )
    with container.pool.connection() as conn:  # the request holds the pool's only connection
        scope = Scope(container, conn)
        job_id = scope.jobs.create("ingest_source", {})
        conn.commit()
        scope.mark_job_failed(job_id, "ConnectError: nowhere")

    db.rollback()
    row = JobRepository(db).get(job_id)
    assert row["status"] == "failed" and row["error"] == "ConnectError: nowhere"


def test_a_container_knows_whether_it_is_serving_requests(db, make_container):
    container = make_container()
    assert container.has_pool is False
    with container.request_scope():
        pass
    assert container.has_pool is True
