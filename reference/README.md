# reference/

Code kept only as a migration source. Nothing here is imported by the
application and nothing here is deployed.

- `rag/`: an Insurellm agentic RAG implementation (Claude contextual chunking,
  Voyage embeddings and reranking, BM25, reciprocal rank fusion, tool-runner
  agent). Its retrieval pieces are being migrated into `api/teachme/` with
  subject-neutral prompts. This folder is deleted when stage 1 of the design
  spec is complete.
