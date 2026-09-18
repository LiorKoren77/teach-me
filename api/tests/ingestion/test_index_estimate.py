from __future__ import annotations

from uuid import uuid4

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Chunk
from teachme.ingestion.contextualize import ChunksOut, contextualize
from teachme.ingestion.detect_language import DetectedLanguage, detect_language
from teachme.ingestion.estimate import estimate_ingest
from teachme.ingestion.fake_responders import default_responders
from teachme.ingestion.index import index_chunks
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.read_pages import ReadPagesOutput, read_pdf_batch
from teachme.telemetry.prices import ModelPrice, PriceTable


def test_index_chunks_embeds_tokenizes_and_replaces_previous():
    embedder = FakeEmbedder(dimension=16)
    search = InMemoryChunkSearch(dimension=16)
    source_id, subject_id = uuid4(), uuid4()
    chunks = [Chunk(context="ctx", text="The biosphere and the atmosphere", page_start=0, page_end=0)]
    records = index_chunks(embedder, search, source_id, subject_id, chunks, language_code="en")
    assert len(records) == 1 and records[0].embedding_model == "fake-embed"
    assert set(records[0].tokens) == {"ctx", "biosphere", "atmosphere"}
    assert search.count(subject_id) == 1
    index_chunks(embedder, search, source_id, subject_id, chunks * 2, language_code="en")
    assert search.count(subject_id) == 2


def test_estimate_scales_with_pages():
    table = PriceTable({"m": ModelPrice(input_per_m=10, output_per_m=10)})
    small = estimate_ingest(page_count=10, model="m", prices=table)
    large = estimate_ingest(page_count=20, model="m", prices=table)
    assert large.cost_usd == 2 * small.cost_usd > 0
    assert small.page_count == 10 and small.input_tokens > small.output_tokens > 0


def test_default_responders_drive_every_ingestion_schema():
    llm = FakeLLM(default_responders())
    pages, figures = read_pdf_batch(
        llm, "fake-model", PdfBatch(first_index=3, last_index=4, data=b"%PDF"), None
    )
    assert [p.page_index for p in pages] == [3, 4] and len(figures) == 1
    assert detect_language(llm, "fake-model", pages) == "en"
    chunks = contextualize(llm, "fake-model", "S", "f.pdf", "en", pages, pages_per_batch=1)
    assert [c.page_start for c in chunks] == [3, 4]
    assert {ReadPagesOutput, DetectedLanguage, ChunksOut} <= set(default_responders())
