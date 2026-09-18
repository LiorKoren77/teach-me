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
teachme export --subject "History ch. 3" --out digest-export
teachme import digest-export/<source-folder> --subject "History ch. 3 copy"
teachme source delete <source-id>
teachme source reingest <source-id>
teachme generate --subject "History ch. 3"            # outline, glossary, teaching text, questions, all languages
teachme tutorial status --subject "History ch. 3"
teachme tutorial show --subject "History ch. 3" --language he --part 0
teachme publish --subject "History ch. 3"             # locks sources, students can see it
```

`generate --content-only` keeps the current outline and glossary and only regenerates teaching
text and questions; `generate --part N` (repeatable) regenerates just those part positions,
reusing the current outline version. `publish` picks the newest complete outline version (every
enabled language fully generated). `tutorial show --draft` renders the latest version whether or
not it has been published, instead of the published one. The subject digest bundle is written
under `digest/<subject slug>/v<outline version>/`: `outline.json`, `glossary.json`,
`glossary.<lang>.json`, `parts/NN.<lang>.md`, `questions.<lang>.jsonl`.

Set `LLM_PROVIDER=fake EMBEDDINGS_PROVIDER=fake RERANKER_PROVIDER=noop` to run the whole pipeline
without any API key. `docker-compose.yml` maps the container's Postgres to host port 5433 (a native
Postgres commonly occupies 5432 on the dev machine). Tests:
`TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5433/teachme_test pytest -q`.
On Vercel, `vercel.json` routes every `/api/*` request to the FastAPI function.
