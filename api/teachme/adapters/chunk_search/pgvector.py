from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Chunk, ChunkHit, ChunkRecord

_HIT_COLUMNS = "id, source_id, context, text, page_start, page_end"


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def parse_vector(text: str) -> tuple[float, ...]:
    return tuple(float(v) for v in text.strip("[]").split(",") if v)


class PgVectorChunkSearch:
    """Chunks table: vector(1024) for dense search, tsvector('simple') for lexical search.
    Tokens are produced by teachme.domain.text.normalize so they match the relevance scorer."""

    name = "pgvector"

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def dimension(self) -> int:
        row = self._conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
        return int(row["atttypmod"])

    def upsert(self, records: Sequence[ChunkRecord]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (id, source_id, subject_id, context, text, page_start, page_end,"
                " embedding, embedding_model, tokens)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, to_tsvector('simple', %s))"
                " ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id,"
                " subject_id = EXCLUDED.subject_id,"
                " context = EXCLUDED.context, text = EXCLUDED.text, page_start = EXCLUDED.page_start,"
                " page_end = EXCLUDED.page_end, embedding = EXCLUDED.embedding,"
                " embedding_model = EXCLUDED.embedding_model, tokens = EXCLUDED.tokens",
                [
                    (
                        r.id,
                        r.source_id,
                        r.subject_id,
                        r.chunk.context,
                        r.chunk.text,
                        r.chunk.page_start,
                        r.chunk.page_end,
                        vector_literal(r.embedding),
                        r.embedding_model,
                        " ".join(r.tokens),
                    )
                    for r in records
                ],
            )

    def delete_by_source(self, source_id: UUID) -> None:
        self._conn.execute("DELETE FROM chunks WHERE source_id = %s", (source_id,))

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]:
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, subject_id, embedding::text AS embedding, embedding_model,"
            " array_to_string(tsvector_to_array(tokens), ' ') AS tokens"
            " FROM chunks WHERE source_id = %s ORDER BY page_start, page_end",
            (source_id,),
        ).fetchall()
        return [
            ChunkRecord(
                id=row["id"],
                source_id=row["source_id"],
                subject_id=row["subject_id"],
                chunk=Chunk(
                    context=row["context"],
                    text=row["text"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                ),
                embedding=parse_vector(row["embedding"]),
                embedding_model=row["embedding_model"],
                tokens=tuple(row["tokens"].split()) if row["tokens"] else (),
            )
            for row in rows
        ]

    def count(self, subject_id: UUID) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM chunks WHERE subject_id = %s", (subject_id,)
        ).fetchone()
        return int(row["n"])

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]:
        literal = vector_literal(vector)
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, 1 - (embedding <=> %(v)s::vector) AS score"
            " FROM chunks WHERE subject_id = %(sid)s ORDER BY embedding <=> %(v)s::vector LIMIT %(k)s",
            {"v": literal, "sid": subject_id, "k": k},
        ).fetchall()
        return [_row_to_hit(row) for row in rows]

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]:
        if not tokens:
            return []
        query = " | ".join("'" + t.replace("'", "''") + "'" for t in tokens if t)
        if not query:
            return []
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, ts_rank_cd(tokens, to_tsquery('simple', %(q)s)) AS score"
            " FROM chunks WHERE subject_id = %(sid)s AND tokens @@ to_tsquery('simple', %(q)s)"
            " ORDER BY score DESC LIMIT %(k)s",
            {"q": query, "sid": subject_id, "k": k},
        ).fetchall()
        return [_row_to_hit(row) for row in rows]


def _row_to_hit(row: dict) -> ChunkHit:
    return ChunkHit(
        chunk_id=row["id"],
        source_id=row["source_id"],
        content=f"{row['context']}\n\n{row['text']}",
        page_start=row["page_start"],
        page_end=row["page_end"],
        score=float(row["score"]),
    )
