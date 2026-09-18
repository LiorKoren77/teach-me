# teach-me

Turns textbook material into a guided tutorial with an assessment dialog.
An admin ingests PDFs for a subject; the system digests them, teaches each part
in the student's chosen language (Hebrew, English or Portuguese), asks
questions, grades answers, re-explains weak sections and tracks progress.

- Frontend: Next.js (App Router), Clerk, Tailwind
- Backend: Python FastAPI under `api/`, Claude via the Anthropic SDK, Voyage
  embeddings, Postgres with pgvector
- Design: `docs/superpowers/specs/2026-09-17-teach-me-design.md`

## Operator quick start

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e ".[dev]"
docker compose up -d                      # local Postgres with pgvector
cp .env.example .env.local                # fill in keys; or `vercel env pull .env.local`
teachme migrate
teachme subject create "History ch. 3" --languages he,en
teachme ingest --subject "History ch. 3" sources/*.pdf
teachme usage --subject "History ch. 3"
```

Set `LLM_PROVIDER=fake EMBEDDINGS_PROVIDER=fake RERANKER_PROVIDER=noop` to run the whole pipeline
without any API key. `docker-compose.yml` maps the container's Postgres to host port 5433 (a native
Postgres commonly occupies 5432 on the dev machine). Tests:
`TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5433/teachme_test pytest -q`.
