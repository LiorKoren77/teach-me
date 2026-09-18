from __future__ import annotations

import pytest
from pydantic import BaseModel

from teachme.adapters.db.pool import make_pool
from teachme.ports.llm import ContentPart, StructuredRequest


class Out(BaseModel):
    ok: bool


def test_container_delegates_to_its_default_scope(db, make_container):
    c = make_container()
    assert c.subjects is c.scope.subjects
    assert c.pipeline is c.scope.pipeline
    assert c.scope.conn is c.conn


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
    assert c.subjects.get_by_name("Scoped") is not None


def test_request_scope_rolls_back_on_error(db, make_container):
    c = make_container()
    with pytest.raises(RuntimeError):
        with c.request_scope() as scope:
            scope.subjects.create("Rolled", ["he"])
            raise RuntimeError("boom")
    assert c.subjects.get_by_name("Rolled") is None


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
