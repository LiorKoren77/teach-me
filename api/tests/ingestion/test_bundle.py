from __future__ import annotations

from uuid import UUID, uuid4

from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.domain.models import Chunk, ChunkRecord, Figure, Page
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug


def test_bundle_slug_is_ascii_and_unique_for_hebrew_names():
    sid = UUID("12345678-0000-0000-0000-000000000000")
    assert bundle_slug("History ch. 3", sid) == "history-ch-3-12345678"
    assert bundle_slug("היסטוריה", sid) == "item-12345678"


def test_prefixed_store_maps_keys():
    inner = InMemoryFileStore()
    store = PrefixedFileStore(inner, "digest/")
    store.put("a/b.md", b"x", "text/markdown")
    assert inner.get("digest/a/b.md") == b"x"
    assert store.get("a/b.md") == b"x" and store.exists("a/b.md")
    assert store.list_keys("a/") == ["a/b.md"]
    store.delete("a/b.md")
    assert not inner.exists("digest/a/b.md")


def test_writer_writes_every_store_and_reader_round_trips(tmp_path):
    memory = InMemoryFileStore()
    local = LocalFileStore(tmp_path)
    writer = BundleWriter([memory, local], subject_slug="geo-1234abcd")
    pages = [
        Page(page_index=0, printed_number="12", text="# Earth\n\nText."),
        Page(page_index=1, printed_number=None, text="More."),
    ]
    figures = [Figure(page_index=0, ordinal=0, kind="map", caption="World", description="A map.")]
    chunks = [
        Chunk(context="c1", text="Text.", page_start=0, page_end=0),
        Chunk(context="c2", text="More.", page_start=1, page_end=1),
    ]
    meta = SourceMeta(
        source_id=uuid4(),
        filename="ch1.pdf",
        media_type="application/pdf",
        size=10,
        page_count=2,
        vision_pages=2,
        language="en",
        models={"read_pages": "fake-model"},
        embedding_model="fake-embed",
    )
    records = [
        ChunkRecord(
            id=uuid4(),
            source_id=meta.source_id,
            subject_id=uuid4(),
            chunk=c,
            embedding=(0.5, 0.5),
            embedding_model="fake-embed",
            tokens=("t",),
        )
        for c in chunks
    ]
    writer.write_meta("ch1-abcd1234", meta)
    writer.write_pages("ch1-abcd1234", pages)
    writer.write_figures("ch1-abcd1234", figures)
    writer.write_chunks("ch1-abcd1234", chunks)
    writer.write_embeddings("ch1-abcd1234", records)

    assert (tmp_path / "geo-1234abcd" / "ch1-abcd1234" / "pages" / "001.md").is_file()
    assert memory.exists("geo-1234abcd/ch1-abcd1234/chunks.jsonl")

    reader = BundleReader(memory, "geo-1234abcd/ch1-abcd1234")
    assert reader.meta() == meta
    assert reader.pages() == pages
    assert reader.figures() == figures
    assert reader.chunks() == chunks
    embeddings = reader.embeddings()
    assert embeddings is not None and embeddings[1].vector == (0.5, 0.5) and embeddings[1].index == 1

    local_reader = BundleReader(LocalFileStore(tmp_path / "geo-1234abcd" / "ch1-abcd1234"), "")
    assert local_reader.pages() == pages


def test_reader_without_embeddings_returns_none():
    memory = InMemoryFileStore()
    BundleWriter([memory], "s").write_chunks("x", [Chunk(context="c", text="t", page_start=0, page_end=0)])
    assert BundleReader(memory, "s/x").embeddings() is None
