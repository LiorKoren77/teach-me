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
teachme eval --language en                            # score generation and grading against the fixtures
```

`generate --content-only` keeps the current outline and glossary and only regenerates teaching
text and questions; `generate --part N` (repeatable) regenerates just those part positions,
reusing the current outline version. `publish` picks the newest complete outline version (every
enabled language fully generated). `tutorial show --draft` renders the latest version whether or
not it has been published, instead of the published one. The subject digest bundle is written
under `digest/<subject slug>/v<outline version>/`: `outline.json`, `glossary.json`,
`glossary.<lang>.json`, `parts/NN.<lang>.md`, `questions.<lang>.jsonl`.

## API

### Running the API locally

```bash
docker compose up -d && teachme migrate                 # once
DATABASE_URL=postgresql://teachme:teachme@localhost:5433/teachme \
  LLM_PROVIDER=fake EMBEDDINGS_PROVIDER=fake RERANKER_PROVIDER=noop \
  uvicorn index:app --app-dir api --reload --port 8000
curl localhost:8000/api/health
```

`api/index.py` is the file Vercel rewrites every `/api/*` request to, so the local server and the
deployment serve the same application. Startup checks the schema on a pooled connection and
refuses to serve at all when the database is behind the code (`teachme migrate` has not been run
against it), rather than failing one request at a time. `LLM_PROVIDER=fake EMBEDDINGS_PROVIDER=fake
RERANKER_PROVIDER=noop` runs the whole pipeline, including the learning loop, without any API key.
`docker-compose.yml` maps the container's Postgres to host port 5433 (a native Postgres commonly
occupies 5432 on the dev machine). Tests:
`TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5433/teachme_test pytest -q`. On Vercel,
`vercel.json` routes every `/api/*` request to the FastAPI function.

### Authentication

Every route except `/api/health` needs a Clerk session token: set `CLERK_JWKS_URL` to the
instance's JWKS endpoint and send `Authorization: Bearer <token>`. Without `CLERK_JWKS_URL` set,
no guard is built at all and those routes answer `503` rather than trust the caller. The Clerk
session-token template must add a custom claim `"role": "{{user.public_metadata.role}}"` -
without it every token is treated as a student, since a missing `role` claim falls back to
`student`, and admin routes will refuse with `403`. Tests never reach Clerk - they override the
`current_user` dependency.

### Routes

| Method | Path | Caller | Purpose |
| --- | --- | --- | --- |
| GET | `/api/health` | anyone | Liveness check; no auth required. |
| GET | `/api/subjects` | student | List published subjects (in this deployment's enabled languages) with the caller's per-part progress. |
| GET | `/api/subjects/{subject_id}` | student | Open a subject: its parts, each with the caller's progress and lock state, and the languages it can be taken in here (those it teaches, filtered by this deployment's enabled languages). |
| POST | `/api/subjects/{subject_id}/parts/{position}/start` | student | Start or resume the caller's attempt at a part; returns the rendered part text and current session state. |
| POST | `/api/attempts/{attempt_id}/round` | student | Sample and begin the attempt's next round of questions. |
| POST | `/api/attempts/{attempt_id}/answer` | student | Submit an answer (free text or multiple-choice) for the current question; grades it and returns the next question or the round result. |
| GET | `/api/attempts/{attempt_id}/reexplain` | student | Server-sent-event stream that re-explains the weak sections of a failed round. |
| GET | `/api/subjects/{subject_id}/sources` | student | The material a published subject teaches from: filename, media type and page count of each fully ingested source. Deliberately narrower than the admin list - no ids, no ingestion status, no error text, and never a file key. |
| GET | `/api/subjects/{subject_id}/pages/{global_index}/image` | student | PNG of one page of a published subject's material, by the global page index its teaching text refers to. Rendered from the PDF on first request and cached in the file store under `thumbnails/{source_id}/NNN-w{width}.png`, so a page is rasterized at most once. |
| GET | `/api/admin/subjects` | admin | List every subject regardless of publication state. |
| GET | `/api/admin/subjects/{subject_id}/sources` | admin | List a subject's ingested sources and their status. |
| GET | `/api/admin/usage` | admin | Model/embedding usage and cost summary, optionally filtered by `subject_id`. |

### Error statuses

`api/teachme/routes/errors.py` maps domain exceptions to HTTP status codes (most specific class
wins when one refusal subclasses another):

| Status | Error | Covers |
| --- | --- | --- |
| 401 | *(`current_user`, not a domain error)* | No `Authorization` header, a scheme other than `Bearer`, a token that cannot be verified against the configured JWKS, or a verified token with no `sub` claim. The Clerk guard is built with `auto_error=False` precisely so this status - and this body - comes from us rather than the SDK's `403 Forbidden`. |
| 404 | `NotFound` | The subject, source, attempt, question or other resource does not exist. |
| 403 | `NotAllowed` | The caller does not own the attempt, the part is locked, the language is not one the subject teaches *and* this deployment enables (`ENABLED_LANGUAGES`), or (via `require_role`) the caller's role does not permit an admin route. |
| 429 | `RateLimited` | A `NotAllowed` subclass: the caller submitted more answers/rejections than `MAX_ANSWERS_PER_MINUTE` allows in the last minute. |
| 409 | `LearningError` (and `IllegalTransition`, `GenerationError`, `SubjectLocked`) | A state-machine refusal - e.g. re-explaining outside `REINFORCING`, an illegal part-status transition, or a subject locked against generation/ingestion. |
| 409 | `QuestionClosed` | A `LearningError` subclass: the question is not open for answering - it already carries a grade, or it belongs to another attempt. A conflict with the state of the round, which is why it is not the `403` a foreign attempt gets. |
| 409 | `InvalidChoice` | A `LearningError` subclass: a multiple-choice submission that is not one of the question's options - no choice at all, or an index past the last one (the route refuses a negative index as a `422`). |
| 409 | `UnmappedQuestion` | An answered row referencing a question that is no longer in the part's bank. The foreign key cascades, so this is a guard rather than a path a request normally takes - but it names the row instead of surfacing as a `500`. |
| 422 | *(FastAPI's built-in request validation, not in this table)* | A malformed request body - e.g. `AnswerRequest` requires exactly one of `answer_text`/`answer_choice`, and rejects neither or both. |

Anything not listed here is a bug and stays a `500` with no detail, so internals never leak to
the client.

### Re-explanation stream (SSE)

`GET /api/attempts/{attempt_id}/reexplain` returns `text/event-stream`. The model is generated and
persisted to completion before any events are sent, then replayed to the client:

- zero or more `delta` events, each `{"text": "..."}` - one per chunk the model produced, glossary
  placeholders still unresolved;
- one final `done` event, `{"text": "...", "truncated": bool, "round_no": int}` - `text` is the
  whole re-explanation rendered for the reader's language (placeholders resolved), `truncated` is
  true when the model stopped at its token ceiling, and `round_no` is the failed round it
  reinforces.

#### Buffered today, live-streamed later

The stream is buffered, not live. `_reexplain_events` runs the whole thing - the Opus call, the
insert and its commit, and the glossary rendering of the final text - before the response body
starts, collecting the model's chunks in a list; only then are they replayed as `delta` events
followed by `done`. The reason is error handling: while nothing has been sent, a refusal or a
provider failure can still become a status code with our error body, whereas once the response
has started it could only arrive as a broken stream.

What that costs: the client gets no bytes at all until the Opus call has finished, so `delta`
events carry no information the `done` event does not, and any intermediary with a
time-to-first-byte timeout (a proxy, a CDN, a serverless platform's own limit) can cut the
request off before the first event - which looks to the student like a re-explanation that never
arrives, even though the row was committed and a retry serves it from the round's cache.

The follow-up is to stream as the model produces it: the model call runs in a worker thread whose
`on_delta` pushes onto a queue, the route's generator drains that queue and yields each chunk as a
`delta` event, the row is committed after the model returns and before `done` is emitted, and a
refusal or `LLMError` mid-stream rolls the transaction back and emits an `error` event instead of
`done`. Retries stay free because the re-explanation is cached per round: a stream cut off after
the commit is replayed from the stored row, and one cut off before it re-generates exactly once,
the attempt row being locked for the duration.

### Evaluation harness

`teachme eval` scores generation and grading against fixtures instead of against a live subject,
so two model or prompt choices can be compared on identical inputs:

```bash
teachme eval                       # every shipped fixture: en, he, pt
teachme eval --language en -l he   # repeatable
teachme eval --fixtures my-cases   # a folder of fixture folders of your own
```

Each fixture is a folder under `api/teachme/eval/fixtures/<language>/`:

- `source.md` - a few hundred words on one topic in that language, with two
  `> **[Figure: ...]**` blocks so figure handling is exercised;
- `expected.json` (or `expected.yaml`) - the languages to generate, the bounds a sane outline
  falls within, and a list of answers a synthetic student gives with the grade each deserves.
  Validated by the pydantic models in `api/teachme/eval/fixtures.py`, so a malformed fixture is
  named rather than half-run.

A run ingests each source into a freshly named subject of its own, generates and publishes it,
then answers its generated questions - each expected answer as a separate synthetic student, so
one answer's grade never changes which questions the next is asked. The report names, per
fixture, whether the outline fell within bounds, how often the recorded grade matched the
expected one, how often the route matched (an answer the model check rejected counts as having
reached the check), how many genuine attempts the relevance gate refused anyway, and what the
whole fixture cost. Every call goes through the configured providers under the usual usage
context, so `teachme usage` accounts for an eval run like any other work.

On the fake stack (`LLM_PROVIDER=fake`) the run exercises the plumbing rather than any model's
judgement: the fake grader credits word overlap with the expected answer, so agreement numbers
mean nothing until the harness runs against `LLM_PROVIDER=anthropic`. The fixtures' outline
bounds allow a single part with a single section because a text source is ingested as one page.

### Stage 3 settings

New settings from `api/teachme/settings.py` (env names as in `.env.example`):

- `MODEL_GRADER` (`model_grader`) - model used to grade free-text answers against the rubric.
- `MODEL_RELEVANCE_CHECK` (`model_relevance_check`) - cheap model used for the on-topic check between the lexical scorer and the grader.
- `MODEL_REEXPLAIN` (`model_reexplain`) - model used to generate the re-explanation of weak sections.
- `MAX_ANSWER_CHARS` (`max_answer_chars`) - free-text answers longer than this are rejected as junk before any model call.
- `MAX_ANSWERS_PER_MINUTE` (`max_answers_per_minute`) - per-student rate limit on answers and rejections combined.
- `MAX_REJECTIONS_PER_QUESTION` (`max_rejections_per_question`) - how many junk/off-topic rejections a question tolerates before it is auto-graded and closed.
- `REINFORCE_SECTIONS_CAP` (`reinforce_sections_cap`) - maximum number of weak sections covered by one re-explanation.
- `CORPUS_CACHE_MAX_ENTRIES` (`corpus_cache_max_entries`) - rendered subject corpora kept in the per-process cache before the least recently used one is evicted (section vocabularies get a multiple of this). Loading is locked per key, so rendering one subject's corpus never blocks a request for another.
- `THUMBNAIL_WIDTH` (`thumbnail_width`, 64-2400) - width in pixels a source page is rasterized to for `GET .../pages/{index}/image`. Part of the cache key (`thumbnails/{source_id}/NNN-w{width}.png`), so changing it does not invalidate images already cached at the old width.
- `RELEVANCE_HIGH` / `RELEVANCE_LOW` (`relevance_high` / `relevance_low`) - lexical relevance-score thresholds: at or above `high` an answer skips the model check; below `low` it is `LOW`.
- `RELEVANCE_THRESHOLDS` (`relevance_thresholds`) - per-language JSON overrides of the two thresholds above (the lexical score is not equally generous in every language).
- `CLERK_JWKS_URL` (`clerk_jwks_url`) - Clerk's JWKS endpoint; unset means no auth guard is built and every authenticated route answers `503`.
