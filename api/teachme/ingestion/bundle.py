from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import Chunk, ChunkRecord, Figure, Page
from teachme.ports.file_store import FileNotFound, FileStore

PIPELINE_VERSION = 1
_PAGE_HEADER = re.compile(r'^<!-- teach-me page index=(\d+) printed=(null|"(.*?)") -->\n\n', re.DOTALL)


class SourceMeta(BaseModel):
    """meta.json: everything needed to re-import the source without the original file."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    filename: str
    media_type: str
    size: int
    page_count: int
    vision_pages: int
    language: str | None
    models: dict[str, str]
    embedding_model: str | None = None
    pipeline_version: int = PIPELINE_VERSION


class ChunkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    context: str
    text: str
    page_start: int
    page_end: int


class EmbeddingRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    chunk_id: UUID
    model: str
    vector: tuple[float, ...]


def slugify(name: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug or "item"


def bundle_slug(name: str, identifier: UUID) -> str:
    """Readable and unique even for non-Latin names: `<slug>-<first 8 hex of id>`."""
    return f"{slugify(name)}-{str(identifier)[:8]}"


def page_filename(page_index: int) -> str:
    return f"pages/{page_index + 1:03d}.md"


class BundleWriter:
    def __init__(self, stores: Sequence[FileStore], subject_slug: str) -> None:
        self._stores = list(stores)
        self._subject_slug = subject_slug

    def prefix(self, source_slug: str) -> str:
        return f"{self._subject_slug}/{source_slug}"

    def write_meta(self, source_slug: str, meta: SourceMeta) -> None:
        self._write(source_slug, "meta.json", meta.model_dump_json(indent=2).encode(), "application/json")

    def write_pages(self, source_slug: str, pages: Sequence[Page]) -> None:
        for page in pages:
            printed = "null" if page.printed_number is None else json.dumps(page.printed_number)
            body = f"<!-- teach-me page index={page.page_index} printed={printed} -->\n\n{page.text}"
            self._write(source_slug, page_filename(page.page_index), body.encode(), "text/markdown")

    def write_figures(self, source_slug: str, figures: Sequence[Figure]) -> None:
        payload = json.dumps([f.model_dump() for f in figures], ensure_ascii=False, indent=2)
        self._write(source_slug, "figures.json", payload.encode(), "application/json")

    def write_chunks(self, source_slug: str, chunks: Sequence[Chunk]) -> None:
        rows = [
            ChunkRow(index=i, context=c.context, text=c.text, page_start=c.page_start, page_end=c.page_end)
            for i, c in enumerate(chunks)
        ]
        self._write(source_slug, "chunks.jsonl", _jsonl(rows), "application/x-ndjson")

    def write_embeddings(self, source_slug: str, records: Sequence[ChunkRecord]) -> None:
        rows = [
            EmbeddingRow(index=i, chunk_id=r.id, model=r.embedding_model, vector=r.embedding)
            for i, r in enumerate(records)
        ]
        self._write(source_slug, "embeddings.jsonl", _jsonl(rows), "application/x-ndjson")

    def _write(self, source_slug: str, relative: str, data: bytes, content_type: str) -> None:
        key = f"{self.prefix(source_slug)}/{relative}"
        for store in self._stores:
            store.put(key, data, content_type)


class BundleReader:
    """Reads one source bundle from any store. `prefix` is '' when the store is rooted at the bundle."""

    def __init__(self, store: FileStore, prefix: str) -> None:
        self._store = store
        self._prefix = prefix.strip("/")

    def _key(self, relative: str) -> str:
        return f"{self._prefix}/{relative}" if self._prefix else relative

    def meta(self) -> SourceMeta:
        return SourceMeta.model_validate_json(self._store.get(self._key("meta.json")))

    def pages(self) -> list[Page]:
        pages: list[Page] = []
        for key in self._store.list_keys(self._key("pages/")):
            raw = self._store.get(key).decode("utf-8")
            match = _PAGE_HEADER.match(raw)
            if match is None:
                raise ValueError(f"{key} has no teach-me page header")
            printed = None if match.group(2) == "null" else json.loads(match.group(2))
            pages.append(
                Page(page_index=int(match.group(1)), printed_number=printed, text=raw[match.end() :])
            )
        return sorted(pages, key=lambda p: p.page_index)

    def figures(self) -> list[Figure]:
        return [
            Figure.model_validate(item) for item in json.loads(self._store.get(self._key("figures.json")))
        ]

    def chunks(self) -> list[Chunk]:
        rows = _read_jsonl(self._store.get(self._key("chunks.jsonl")), ChunkRow)
        rows.sort(key=lambda r: r.index)
        return [
            Chunk(context=r.context, text=r.text, page_start=r.page_start, page_end=r.page_end) for r in rows
        ]

    def embeddings(self) -> list[EmbeddingRow] | None:
        try:
            data = self._store.get(self._key("embeddings.jsonl"))
        except FileNotFound:
            return None
        rows = _read_jsonl(data, EmbeddingRow)
        rows.sort(key=lambda r: r.index)
        return rows

    def has_chunks(self) -> bool:
        return self._store.exists(self._key("chunks.jsonl"))


def _jsonl(rows: Sequence[BaseModel]) -> bytes:
    return ("".join(row.model_dump_json() + "\n" for row in rows)).encode("utf-8")


def _read_jsonl[T: BaseModel](data: bytes, model: type[T]) -> list[T]:
    return [model.model_validate_json(line) for line in data.decode("utf-8").splitlines() if line.strip()]
