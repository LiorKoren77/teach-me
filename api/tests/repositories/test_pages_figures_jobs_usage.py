from __future__ import annotations

import json
from uuid import uuid4

from teachme.domain.models import Figure, Page
from teachme.repositories.figures import FigureRepository
from teachme.repositories.jobs import JobRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository, UsageRow


def _source(db):
    subject = SubjectRepository(db).create(f"S-{uuid4()}", ["en"])
    return subject, SourceRepository(db).create(subject.id, "a.pdf", "application/pdf", "k", 1)


def test_pages_replace_and_list_in_order(db):
    _, source = _source(db)
    repo = PageRepository(db)
    repo.replace(
        source.id,
        [
            Page(page_index=1, printed_number="2", text="second"),
            Page(page_index=0, printed_number="1", text="first"),
        ],
    )
    assert [p.text for p in repo.list(source.id)] == ["first", "second"]
    repo.replace(source.id, [Page(page_index=0, printed_number=None, text="only")])
    assert [p.text for p in repo.list(source.id)] == ["only"]


def test_figures_replace_and_list(db):
    _, source = _source(db)
    repo = FigureRepository(db)
    repo.replace(
        source.id,
        [
            Figure(page_index=3, ordinal=0, kind="map", caption="Earth 1850", description="A world map"),
            Figure(page_index=1, ordinal=0, kind="photo", caption="", description="A port"),
        ],
    )
    figures = repo.list(source.id)
    assert [(f.page_index, f.kind) for f in figures] == [(1, "photo"), (3, "map")]


def test_jobs_create_status_attempts(db):
    repo = JobRepository(db)
    job_id = repo.create("ingest_source", {"source_id": "abc"})
    job = repo.get(job_id)
    assert job["kind"] == "ingest_source"
    assert job["payload"] == {"source_id": "abc"}
    assert job["status"] == "queued"
    repo.set_status(job_id, "running")
    repo.increment_attempts(job_id)
    repo.set_status(job_id, "failed", error="nope")
    job = repo.get(job_id)
    assert job["status"] == "failed" and job["attempts"] == 1 and job["error"] == "nope"


def test_jobs_fail_stale_running_leaves_a_fresh_one_alone(db):
    """An invocation that hit the function's duration limit leaves its row `running` forever;
    the sweep is what turns that into a `failed` row a later delivery can claim again."""
    repo = JobRepository(db)
    stale = repo.create("ingest_source", {})
    fresh = repo.create("ingest_source", {})
    repo.set_status(stale, "running")
    repo.set_status(fresh, "running")
    db.execute("UPDATE jobs SET updated_at = now() - interval '20 minutes' WHERE id = %s", (stale,))

    assert repo.fail_stale_running(300) == [stale]
    assert repo.get(stale)["status"] == "failed"
    assert repo.get(stale)["error"] == "invocation exceeded its duration"
    assert repo.get(fresh)["status"] == "running"
    assert repo.fail_stale_running(300) == []  # nothing left to sweep


def test_usage_insert_and_summarize(db):
    subject, source = _source(db)
    repo = UsageRepository(db)
    for tokens in (100, 300):
        repo.insert(
            UsageRow(
                purpose="ingest.read_pages",
                provider="anthropic",
                model="claude-opus-5",
                input_tokens=tokens,
                output_tokens=10,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=0.001,
                latency_ms=5,
                subject_id=subject.id,
                source_id=source.id,
            )
        )
    repo.insert(
        UsageRow(
            purpose="ingest.embed",
            provider="voyage",
            model="voyage-4",
            input_tokens=50,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=0.0001,
            latency_ms=1,
            subject_id=subject.id,
        )
    )
    summary = repo.summarize(subject_id=subject.id)
    by_purpose = {row["purpose"]: row for row in summary}
    assert by_purpose["ingest.read_pages"]["calls"] == 2
    assert by_purpose["ingest.read_pages"]["input_tokens"] == 400
    assert float(by_purpose["ingest.read_pages"]["cost_usd"]) == 0.002
    assert by_purpose["ingest.embed"]["model"] == "voyage-4"

    json.dumps(summary)
    for row in summary:
        assert isinstance(row["cost_usd"], float)
        assert isinstance(row["calls"], int)
        assert isinstance(row["input_tokens"], int)
        assert isinstance(row["output_tokens"], int)
        assert isinstance(row["cache_read_tokens"], int)
        assert isinstance(row["cache_write_tokens"], int)
        assert isinstance(row["avg_latency_ms"], int)
