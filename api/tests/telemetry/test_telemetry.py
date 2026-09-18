from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.llm.fake import FakeLLM
from teachme.ports.llm import ContentPart, LLMUsage, StructuredRequest
from teachme.telemetry.prices import ModelPrice, PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder, current_usage_context, usage_context


class _Repo:
    def __init__(self):
        self.rows = []

    def insert(self, row):
        self.rows.append(row)


def test_price_table_costs():
    table = PriceTable(
        {"m": ModelPrice(input_per_m=5, output_per_m=25, cache_read_per_m=0.5, cache_write_per_m=6.25)}
    )
    usage = LLMUsage(input_tokens=1000, output_tokens=1000, cache_read_tokens=1000, cache_write_tokens=1000)
    assert round(table.cost_llm("m", usage), 6) == round(0.005 + 0.025 + 0.0005 + 0.00625, 6)
    assert table.cost_tokens("m", 2_000_000) == 10.0
    assert table.cost_llm("unknown-model", usage) == 0.0


def test_default_prices_cover_configured_models():
    table = PriceTable()
    models = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "voyage-4", "rerank-2.5", "fake-model")
    for model in models:
        assert table.price_for(model) is not None


def test_usage_context_nests_and_resets():
    assert current_usage_context().subject_id is None
    sid, src = uuid4(), uuid4()
    with usage_context(subject_id=sid):
        with usage_context(source_id=src):
            ctx = current_usage_context()
            assert ctx.subject_id == sid and ctx.source_id == src
        assert current_usage_context().source_id is None
    assert current_usage_context().subject_id is None


def test_usage_context_rejects_unknown_field():
    with pytest.raises(ValidationError):
        with usage_context(subjectid=uuid4()):
            pass


def test_usage_context_rejects_mistyped_field():
    with pytest.raises(ValidationError):
        with usage_context(subject_id="not-a-uuid"):
            pass


def test_recorder_writes_row_with_context_and_cost():
    repo = _Repo()
    recorder = UsageRecorder(repo, PriceTable({"m": ModelPrice(input_per_m=1, output_per_m=1)}))
    sid = uuid4()
    with usage_context(subject_id=sid):
        recorder.record_llm(
            purpose="p",
            provider="fake",
            model="m",
            usage=LLMUsage(input_tokens=500_000, output_tokens=500_000),
            latency_ms=12,
        )
    row = repo.rows[0]
    assert row.purpose == "p" and row.subject_id == sid and row.cost_usd == 1.0 and row.latency_ms == 12


class Out(BaseModel):
    ok: bool


def test_recording_llm_and_embedder_delegate_and_record():
    repo = _Repo()
    recorder = UsageRecorder(repo, PriceTable())
    fake_llm = FakeLLM({Out: lambda r: Out(ok=True)})
    llm = RecordingLLM(fake_llm, recorder)
    req = StructuredRequest(
        purpose="ingest.test", model="fake-model", system="s", parts=(ContentPart.of_text("x"),)
    )
    assert llm.generate_structured(req, Out).output.ok is True
    assert llm.name == "fake" and "application/pdf" in llm.capabilities().media_types
    assert llm.inner is fake_llm
    fake_embedder = FakeEmbedder(dimension=8)
    embedder = RecordingEmbedder(fake_embedder, recorder)
    assert len(embedder.embed_documents(["a", "b"]).vectors) == 2
    assert embedder.dimension == 8 and embedder.model == "fake-embed"
    assert embedder.inner is fake_embedder
    purposes = [r.purpose for r in repo.rows]
    assert purposes == ["ingest.test", "embed.documents"]
