# Anthropic agentic RAG implementation

An Insurellm RAG assistant built on the Anthropic stack, as a counterpart to
`pro_implementation/` (OpenAI/litellm) and `implementation/` (LangChain).

| Concern | Choice |
|---|---|
| Generation, chunking, contextualising | Claude Opus 5 (`claude-opus-5`), adaptive thinking |
| Embeddings | Voyage `voyage-4` — Anthropic does not sell an embedding model and [recommends Voyage](https://platform.claude.com/docs/en/build-with-claude/embeddings) |
| Reranking | Voyage `rerank-2.5` |
| Lexical index | BM25 (`rank_bm25`) over the same contextualised chunks |
| Vector store | Chroma, in `../claude_db` |

## Why this shape

It follows Anthropic's [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
findings, which measure each layer against a plain-embedding baseline:

| Pipeline | Retrieval failure rate |
|---|---|
| Contextual embeddings | −35% |
| + contextual BM25 | −49% |
| + reranking | −67% |

All three layers are implemented. Anthropic also found 20 chunks to outperform 5
or 10, and reranked 150 candidates down to 20 — hence `RETRIEVAL_K = 150`,
`FINAL_K = 20`.

## Ingest (`ingest.py`)

```
fetch_documents → process_document (Claude) → embed (Voyage) + BM25 index
```

`process_document` makes one structured call per document. Claude splits it into
overlapping chunks and, **seeing the whole document**, writes a 50–100 token blurb
situating each chunk within it. That blurb is prepended to the chunk before both
indexes are built — which is what lets an otherwise context-free chunk ("the fee
rose 8%") be retrieved at all.

Anthropic's write-up makes one call *per chunk* against a cached document. One
structured call per document gives each chunk the same whole-document visibility
for a small fraction of the requests; the system prompt is cached either way.

Outputs: the Chroma collection in `../claude_db`, and `../claude_bm25.pkl`. The
BM25 corpus is pickled and the index rebuilt on load, so it can't go stale
against a different `rank_bm25` version.

## Answer (`answer.py`)

Claude gets a `search_knowledge_base` tool and drives retrieval itself via
`client.beta.messages.tool_runner` — choosing queries, reading results, and
searching again for multi-hop questions. Each search is hybrid:

```
query → [Voyage dense ∥ BM25 lexical] → reciprocal rank fusion → voyage rerank-2.5 → top 20
```

RRF is used rather than score blending because a cosine similarity and a BM25
score are not on comparable scales.

Public API is unchanged from the sibling implementations, so `app.py` and
`evaluation/eval.py` work by changing only the import:

- `answer_question(question, history) -> (answer, chunks)` — `chunks` accumulates
  everything the agent retrieved across all its searches, deduplicated.
- `fetch_context(question, history) -> chunks` — one direct hybrid search, so
  retrieval can be measured independently of the agent.

## Setup

Needs `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in `.env`. Then:

```bash
cd claude_implementation && python ingest.py
```

## Notes

- Requires `anthropic>=1.5`. The 0.x SDK has no `output_config`/`effort` and no
  `messages.parse`, both of which this code uses.
- `../claude_db` is deliberately separate from `../preprocessed_db`: Voyage
  embeddings are 1024-dim, OpenAI's `text-embedding-3-large` is 3072-dim, so the
  two cannot share a Chroma collection.
- `run_agent` is intentionally not `@retry`-wrapped — retrying it would replay
  every tool call and LLM call in the loop against a half-built transcript.
