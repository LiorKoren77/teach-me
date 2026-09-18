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
teachme jobs sweep                                    # unstick jobs no invocation is coming back for
teachme eval --language en                            # score generation and grading against the fixtures
```

`generate --content-only` keeps the current outline and glossary and only regenerates teaching
text and questions; `generate --part N` (repeatable) regenerates just those part positions,
reusing the current outline version. `publish` picks the newest complete outline version (every
enabled language fully generated). `tutorial show --draft` renders the latest version whether or
not it has been published, instead of the published one. The subject digest bundle is written
under `digest/<subject slug>/v<outline version>/`: `outline.json`, `glossary.json`,
`glossary.<lang>.json`, `parts/NN.<lang>.md`, `questions.<lang>.jsonl`.

## Frontend

```bash
source ~/.nvm/nvm.sh && nvm use 22   # the version in .nvmrc
npm install
npm run dev                          # with the API on :8000, see "Running the API locally"
npm run lint && npm run test && npm run build
```

Environment (in `.env.local`, never committed; placeholders live in `.env.example`):

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Clerk publishable key. Public by design, but the app
  will not sign anyone in without it. With no key at all `next build` still succeeds, because
  the root layout reads the language cookie and every route is therefore rendered on demand.
- `CLERK_SECRET_KEY` - Clerk secret key, used by the proxy to verify sessions.
- `NEXT_PUBLIC_CLERK_SIGN_IN_URL` / `..._SIGN_UP_URL` and the matching
  `..._FALLBACK_REDIRECT_URL`s - optional, commented out in `.env.example`: unset, Clerk uses its
  hosted pages, which is what this app does.
- `BACKEND_URL` - optional; where `next dev` sends `/api/*`, default `http://localhost:8000`.
  `next.config.ts` adds that rewrite unless `VERCEL` is set, since on Vercel the Python
  function serves `/api` itself.

The backend needs `CLERK_JWKS_URL` for the same Clerk instance (see "Authentication"); the
frontend only ever calls relative `/api/...` URLs and attaches the session token as a bearer.

Conventions: components take plain props and never fetch; all fetching lives in `lib/api/*.ts`
and `hooks/*.ts`; every UI string comes from `lib/i18n.ts` (he, en, pt) and the root layout sets
`<html lang dir>` from the `teachme_lang` cookie, so Hebrew renders right-to-left. Tests are
Vitest plus Testing Library (`npm run test`), one Playwright flow (`npm run e2e`).

### End-to-end tests

`npm run e2e` runs `playwright.config.ts`: chromium only, `e2e/learn.spec.ts` signs in, opens a
seeded subject, reads part 1 and answers a full round. Two `webServer` entries own the process
lifecycle - `scripts/e2e-backend.sh` (the API on the fake stack against the local Postgres *test*
database) and `npm run dev` (the frontend) - both left alone (`reuseExistingServer`) if already
running outside CI.

One-time setup:

- `npx playwright install chromium` - downloads a browser binary from Microsoft's and Google's
  CDNs; it needs outbound access to those hosts specifically (a sandbox that only allows the npm
  registry, for instance, cannot reach them). Without it `npm run e2e` fails to launch the
  browser rather than skipping.
- `npm install --save-dev @clerk/testing` - Clerk's own Playwright helpers
  (`clerkSetup`/`setupClerkTestingToken`), which get a Testing Token so the sign-in form is not
  blocked by bot protection in a headless browser. Not a committed dependency: the spec imports
  it dynamically, only once Clerk credentials are configured (see below), so `npm run e2e`
  without them never needs it installed.
- Clerk test credentials: a real test user in the same Clerk instance the app is using, plus
  `CLERK_SECRET_KEY` (already needed for the app itself), `E2E_CLERK_USER_USERNAME` and
  `E2E_CLERK_USER_PASSWORD` in the environment `npm run e2e` runs in. Without all three the spec
  reports itself **skipped** (`test.skip`), not failed - this is the expected result in an
  environment with no Clerk keys at all.
- `scripts/e2e-backend.sh` reuses the Python venv `api/` is installed into (see "Running the API
  locally"); set `TEACHME_VENV` if it is not at the default sibling-checkout path. It seeds one
  small subject (a two-page generated PDF, ingested/generated/published on `LLM_PROVIDER=fake
  EMBEDDINGS_PROVIDER=fake RERANKER_PROVIDER=noop`) into `DATABASE_URL`'s `teachme_test`
  database, idempotently - safe to run on its own via `npm run e2e:seed` to check the seed step
  without starting the server.

`proxy.ts` (Next 16's replacement for `middleware.ts`) runs `clerkMiddleware()` and makes an
optimistic check on `/learn` and `/admin`. Clerk Core 3 deprecated route-matcher protection
because path matching can diverge from routing, so each protected page also checks for itself.

`/learn/[subjectId]` is that kind of page: a server component that calls `await auth.protect()`
before rendering the client screen - subject tabs and the part strip on top, the teaching text
above the tutor dialog, the sources on the right, stacked on narrow screens. Two contracts in it
are worth naming. Page references come from the part: `page_refs` on the rendered part holds the
global 0-based page indices to show thumbnails for, and `page_labels` the number each of those
pages prints, which is what the thumbnail is captioned with. The thumbnail images come from `/api/subjects/{id}/pages/{n}/image`,
which accepts a bearer token only - an `<img src>` cannot send one, so `hooks/usePageImage.ts`
fetches each page through the API client and hands the browser an object URL instead. And
the re-explanation shows its notice for as long as the stream is open, because the API generates
the whole re-explanation before it sends a byte (see "Re-explanation stream"); the next round
stays disabled until the `done` event arrives, and the text stays on screen through that round,
since it is keyed on the failed round rather than on the round result the screen is holding.

The dialog shows the feedback for the answer just graded together with the next question, rather
than one after the other as the spec's wording suggests: the API answers a submit with both, and
holding the question back would cost a round trip and a second wait for nothing.

The Admin link is offered only to a reader whose session token carries the admin role
(`lib/role.ts` reads the same `role` claim the API verifies); the page and every route behind it
check for themselves regardless.

`/admin` is the CLI's ingest/generate/publish loop in a page. `hooks/useAdminActions.ts` owns all
of it - uploading, deleting and re-ingesting sources, generating, publishing and unpublishing -
and both its polls, so `components/UploadPane.tsx`, `SourceRow.tsx` and `SubjectActions.tsx` stay
plain: while any source is not yet `ready` or `failed` the source list is re-read every 3 s, and a
job started by generate or re-ingest is followed through `GET /api/admin/jobs/{id}` until it is
done or failed. The file picker's `accept` comes from `GET /api/admin/capabilities`, never from a
list written here, so it offers exactly what the backend will take - and the backend still refuses
an unaccepted type with 415, which `lib/api/errors.ts` maps like any other failure (413 and 415
have their own messages). Uploads go through `apiUpload` in `lib/api/client.ts`: one `FormData`
with the session bearer and no explicit Content-Type, since only the browser knows the multipart
boundary. Publish is disabled unless the status endpoint says `publishable`; a published subject
locks its own sources, so the upload control and the per-source buttons disappear rather than fail.
The same pane appears in the right column of `/learn/[subjectId]` for an admin reading a draft
subject, and for nobody else - with no subject id the hook makes no request at all, so a student's
session never touches an admin route.

Failed requests are shown, not printed: `lib/api/errors.ts` maps an `ApiError` status (401, 403,
409, 429, anything else) to a key in the `errors` block of `lib/i18n.ts`, `hooks/useApiError.ts`
sends the backend's `detail` to `console.debug`, and a 401 goes to Clerk's `redirectToSignIn()`
rather than to a message the reader can do nothing with.

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
| GET | `/api/admin/capabilities` | admin | What the file picker may offer: the media types this deployment's LLM adapter can read (narrowed by `ALLOWED_UPLOAD_TYPES`) and `MAX_UPLOAD_BYTES`. |
| POST | `/api/admin/subjects/{subject_id}/sources` | admin | Upload one file (multipart field `file`) to a draft subject: registers it and queues its ingestion. Answers with the source plus the `job_id`. `415` for a type that cannot be read, `413` for a body over `MAX_UPLOAD_BYTES`, `409` when the subject is published. |
| DELETE | `/api/admin/sources/{source_id}` | admin | Remove a source, its pages, figures, chunks, thumbnails and file. `204` with no body; `409` when the subject is published. |
| POST | `/api/admin/sources/{source_id}/reingest` | admin | Re-run a source through the pipeline from the start; answers with the `job_id`. |
| GET | `/api/admin/jobs/{job_id}` | admin | One job's `kind`, `status` (`queued`/`running`/`done`/`failed`), `attempts` and `error` - what the upload pane polls. |
| POST | `/api/admin/subjects/{subject_id}/generate` | admin | Queue a `generate_subject` job for a draft subject; answers with the `job_id`. |
| GET | `/api/admin/subjects/{subject_id}/status` | admin | `TutorialService.status` for the pane: per-language parts ready, questions, failed parts, and whether (and which version) it can publish. |
| POST | `/api/admin/subjects/{subject_id}/publish` | admin | Publish the newest complete outline version; answers with the updated subject. |
| POST | `/api/admin/subjects/{subject_id}/unpublish` | admin | Return the subject to draft; answers with the updated subject. Idempotent: a subject that is already a draft is a `200` with itself, not a refusal. |
| POST | `/api/jobs/run` | the deployment itself | Runs one unit of a queued job. No Clerk session: the only credential is the `x-job-secret` header, compared against `JOB_RUNNER_SECRET` in constant time. See "Background jobs". |

The `RenderedPart` a `/start` (or a learn route) returns carries `page_refs`: the global page
indices of the pages whose figures the teaching text points at, written by the generator rather
than scraped out of the prose. They are exactly the indices `GET /api/subjects/{subject_id}/pages/{global_index}/image`
takes, so the client can show a page thumbnail next to the text without parsing it; the prose
itself names pages by their printed number, which is not a corpus index.


### Admin upload

The admin pane does over HTTP exactly what the CLI does: `POST .../sources` calls the same
`SourceService.register` and queues the same `ingest_source` job as `teachme ingest`, so no part
of ingestion knows which of the two put the file there. An upload that declares a `Content-Length`
over `MAX_UPLOAD_BYTES` is refused with `413` by a middleware in front of the router, before the
body is read at all - it has to be there, because FastAPI parses the whole multipart form before
the endpoint's first line runs. A chunked body declares no length, so those are measured after
the form is parsed and refused with the same `413`; the bytes have been received by then, which
is as early as anything can tell. An upload is refused by the service when
the type is one the configured LLM adapter cannot read (`415`) or the subject is published
(`409`) - a published subject is locked against upload, delete, reingest and generate, though its
sources stay visible. The response carries the registered source and the `job_id` to poll at
`GET /api/admin/jobs/{job_id}`; the pane follows the source's own status rather than that job,
because ingestion is resumable and behind the `vercel_function` runner takes several jobs to
finish. Generate, publish and unpublish are the same `TutorialService` calls `teachme tutorial`
makes, and `.../status` prints the same numbers `teachme tutorial status` does.

### Background jobs

Ingestion and generation are queued as jobs (`jobs` table) and run by the runner `JOB_RUNNER`
selects:

- `inprocess` (default, and what the CLI and the tests use) runs the handler in the calling
  thread, so `teachme ingest` blocks until the source is ready.
- `vercel_function` is the serverless answer to having no worker: the request creates the job row,
  commits it, and posts `{job_id, kind, payload}` to `{SELF_BASE_URL}/api/jobs/run` with the
  `x-job-secret` header (a read timeout means delivered, not failed - the receiving invocation is
  still working). `SELF_BASE_URL` unset means `https://{VERCEL_URL}`, so a preview deployment
  calls itself rather than production.
- `sqs` enqueues the identical message for an AWS worker.

`POST /api/jobs/run` does **one** unit of work per invocation. For `ingest_source` that unit is
one *read batch* during extraction - `PAGES_PER_READ_BATCH` pages, one vision call - and then one
chunking step and one indexing step; when more remains the endpoint enqueues a fresh job for the
rest. So an 8-page source read 3 at a time is 5 invocations, and a 400-page book is ~70 short ones
rather than one that outlives the function's duration limit. `generate_subject` and
`generate_unit` are already job-sized. Extraction resumes at the first page it has no row for, so
a step that never came back costs at most the batch it was reading.

The job row is claimed in a single statement (`UPDATE ... WHERE status IN ('queued','failed')`),
which both increments `attempts` and makes the delivery exclusive: a redelivery of a job that is
already `running` or `done` answers `200 {"status": "skipped"}` with no `next_job_id`, so it is
not retried and the work is not repeated. An invocation killed by the duration limit writes
nothing on its way out, so every delivery first sweeps rows left `running` for longer than
`JOB_STALE_AFTER_SECONDS` (default 300) and marks them `failed`, which is also what makes them
claimable again; `teachme jobs sweep` runs the same sweep by hand.

Who waits for that POST depends on who is posting. `/api/jobs/run` hands the next step over
**inline**, before it answers: Vercel is free to freeze an instance the moment its response goes
out, and a POST left on a thread would take the rest of the ingestion with it. It costs the
runner's one-second read timeout, not the step the next invocation runs. An admin route - upload,
reingest, generate - still posts from a daemon thread it never waits on, so the browser is not
held while a job starts. **The residual risk is that first hand-over**: if the instance is frozen
between the response and the POST, the job row stays `queued` and nothing comes for it. That is
what `requeue_stale_queued` is for - `teachme jobs kick` posts every job queued for longer than
`JOB_STALE_AFTER_SECONDS` again (and `teachme jobs sweep` does that plus the `running` sweep), so
a cron or an operator recovers it. The re-post touches `updated_at`, so two sweeps a moment apart
do not deliver the same job twice.

`vercel.json` sets `maxDuration: 300` on `api/index.py`. **That ceiling depends on the account
plan** - 300 s needs Pro or above; on Hobby the deploy is rejected or the value is clamped, so
lower it to what the plan allows. Sizing is honest about what has to fit: one invocation holds
one read batch, so `PAGES_PER_READ_BATCH` x the per-page read latency of `MODEL_READ_PAGES` must
fit `maxDuration` (and `JOB_STALE_AFTER_SECONDS` should match it). Lower `PAGES_PER_READ_BATCH`
on a slower model or a tighter plan.

### Error statuses

`api/teachme/routes/errors.py` maps domain exceptions to HTTP status codes (most specific class
wins when one refusal subclasses another):

| Status | Error | Covers |
| --- | --- | --- |
| 401 | *(`current_user`, not a domain error)* | No `Authorization` header, a scheme other than `Bearer`, a token that cannot be verified against the configured JWKS, or a verified token with no `sub` claim. The Clerk guard is built with `auto_error=False` precisely so this status - and this body - comes from us rather than the SDK's `403 Forbidden`. |
| 400 | `UnknownJobKind` | A queued job names a kind this deployment cannot run - a job row left behind by an older version, or a queue shared with a deployment that knows kinds this one does not. The job row is marked `failed` before the status is returned. |
| 404 | `NotFound` | The subject, source, attempt, question or other resource does not exist. |
| 403 | `NotAllowed` | The caller does not own the attempt, the part is locked, the language is not one the subject teaches *and* this deployment enables (`ENABLED_LANGUAGES`), or (via `require_role`) the caller's role does not permit an admin route. |
| 429 | `RateLimited` | A `NotAllowed` subclass: the caller submitted more answers/rejections than `MAX_ANSWERS_PER_MINUTE` allows in the last minute. |
| 409 | `LearningError` (and `IllegalTransition`, `GenerationError`, `SubjectLocked`) | A state-machine refusal - e.g. re-explaining outside `REINFORCING`, an illegal part-status transition, or a subject locked against generation/ingestion. |
| 409 | `QuestionClosed` | A `LearningError` subclass: the question is not open for answering - it already carries a grade, or it belongs to another attempt. A conflict with the state of the round, which is why it is not the `403` a foreign attempt gets. |
| 409 | `InvalidChoice` | A `LearningError` subclass: a multiple-choice submission that is not one of the question's options - no choice at all, or an index past the last one (the route refuses a negative index as a `422`). |
| 409 | `UnmappedQuestion` | An answered row referencing a question that is no longer in the part's bank. The foreign key cascades, so this is a guard rather than a path a request normally takes - but it names the row instead of surfacing as a `500`. |
| 413 | `UploadTooLarge` | An admin upload whose bytes exceed `MAX_UPLOAD_BYTES`, when it arrives chunked and so declares no length. A declared `Content-Length` over the limit is answered with the same status by the middleware in front of the router, which never reaches this error. |
| 415 | `UnsupportedMediaType` | An upload whose type the configured LLM adapter cannot read, or which `ALLOWED_UPLOAD_TYPES` excludes. `GET /api/admin/capabilities` lists what it would accept. |
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
teachme eval --keep                # skip teardown; leave the fixture subjects published
```

Each fixture is a folder under `api/teachme/eval/fixtures/<language>/`:

- `source-1.md`, `source-2.md`, ... - one or more one-page markdown sources on one topic in that
  language (a text source is always ingested as a single page), two `> **[Figure: ...]**` blocks
  between them so figure handling is exercised, and at least two files so the outline has more
  than one section to check;
- `expected.json` (or `expected.yaml`) - the languages to generate, the bounds a sane outline
  falls within, and a list of answers a synthetic student gives with the grade each deserves.
  Validated by the pydantic models in `api/teachme/eval/fixtures.py`, which also checks that the
  spec's `language` matches the folder name, so a malformed or misplaced fixture is named rather
  than half-run.

A run ingests each fixture's sources into a freshly named subject of its own, generates and
publishes it, then answers its generated questions - each expected answer as a separate synthetic
student, so one answer's grade never changes which questions the next is asked. The report names,
per fixture, whether the outline fell within bounds, how often the recorded grade matched the
expected one, how often the route matched (an answer the model check rejected counts as having
reached the check), how many genuine attempts the relevance gate refused anyway, and what the
whole fixture cost. Every call goes through the configured providers under the usual usage
context, so `teachme usage` accounts for an eval run like any other work. Once a fixture is
scored, its subject is unpublished, its sources deleted and its row dropped, so an eval subject
never lingers in a student's `GET /api/subjects` - `--keep` skips that teardown and prints the
kept subject names, for inspecting a run's output by hand.

On the fake stack (`LLM_PROVIDER=fake`) the run mostly exercises the plumbing rather than any
model's judgement - the fake grader credits word overlap with the expected answer, so an
agreement number here is not a measure of grading quality until the harness runs against
`LLM_PROVIDER=anthropic` - but the shipped fixtures are still calibrated to reach 100% grading
agreement even on the fake stack, so a regression in the plumbing itself still shows up.

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

## Deployment

Deploying stages 1-4 to Vercel is operational work, not part of this repo's automated setup;
the full checklist (and the running record of the pilot's per-student cost) lives in Task 11 of
`docs/superpowers/plans/2026-09-18-stage4-frontend.md`. The notes below are what actually changes
versus the local run described above.

- **Project**: rename the Vercel project to `teach-me` in the dashboard (the CLI cannot rename an
  existing project), then `vercel link` to it.
- **API function**: `vercel.json` rewrites every `/api/*` request to `/api/index`, which is
  `api/index.py` - a Python function hosting the same FastAPI app the local `uvicorn` command
  runs (see "Running the API locally"). `next.config.ts`'s dev-only rewrite does not run there:
  it is skipped whenever `VERCEL` is set, which Vercel sets on every build and invocation. Before
  deploying, check the installed dependency footprint under `api/` (`requirements.txt`, generated
  by `uv pip compile pyproject.toml`, currently 100 resolved packages) against Vercel's Python
  function size limit; trim unused extras if a deploy gets close to it.
- **Marketplace resources**: provision Postgres and Vercel Blob storage through the
  `vercel:marketplace` skill (or the dashboard) - this wires `DATABASE_URL` and
  `BLOB_READ_WRITE_TOKEN` into the project automatically.
- **Backend environment variables** (`vercel env add`; see `.env.example` and "Stage 3 settings"
  above for the full set): `DATABASE_URL`, `BLOB_READ_WRITE_TOKEN`, `FILE_STORE=vercel_blob`,
  `LLM_PROVIDER=anthropic`, `EMBEDDINGS_PROVIDER=voyage`, `RERANKER_PROVIDER=voyage`,
  `ANTHROPIC_API_KEY` (a service-account key with an expiry, not a personal one),
  `VOYAGE_API_KEY`, `THUMBNAIL_WIDTH` (optional; defaults to 800), `CLERK_JWKS_URL`,
  `CLERK_SECRET_KEY`.
- **Frontend environment variables**: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`
  (the same Clerk instance and secret as the backend's). See "Frontend" above for what each does
  and which ones stay unset.
- **Clerk setup**: one Clerk instance backs both `CLERK_JWKS_URL` (backend) and the
  publishable/secret key pair (frontend); see "Authentication". Its session-token template must
  add the custom claim `"role": "{{user.public_metadata.role}}"` - without it every token is
  treated as a student and admin routes refuse with `403` (see "Authentication" and "Stage 3
  settings").
- After `vercel env pull .env.local`, run `teachme migrate` against the hosted database before
  the first deploy, then `vercel` (preview) and `vercel --prod`; ingest, generate and publish one
  real short PDF from the CLI and sign in to run one part end to end before trusting it with
  students. Run `teachme usage` afterwards to see what that run cost.
- The admin upload pane (stage 5) is deliberately out of scope for this deployment - see Task 11
  and "Self-review against the spec" in the plan.

### Workload identity federation

Production can authenticate to Anthropic with the OIDC token Vercel signs for each invocation
instead of a long-lived API key: the SDK exchanges that token for a short-lived access token, so
there is no key to leak or rotate. `CarryVercelOidcToken` (in `api/teachme/app.py`) copies the
`x-vercel-oidc-token` header of the request being served into a context variable, and
`VercelOidcIdentity` hands it to the SDK whenever a new access token has to be minted. It works
only inside a request: a CLI run, the SQS worker or any other process authenticates with
`IDENTITY_PROVIDER=file` (a file re-read on every exchange) or with an API key.

The steps below are **operator steps** - console and `vercel env` work, not code. Do them in
order; the key is deleted last, once a federated request has actually succeeded.

1. In the Anthropic console, register the Vercel team issuer `https://oidc.vercel.com/<team>` as
   a **custom OIDC issuer**, with discovery (the console fetches the JWKS from the issuer's
   `/.well-known/openid-configuration`).
2. Raise that issuer's **maximum token lifetime to 2 hours**: Vercel's tokens are valid for
   longer than the default, and an issuer whose limit is below the token's rejects every
   exchange.
3. Create a **federation rule** on the issuer matching the claims `project_id` (this project's
   id) and `environment` = `production`, with scope `workspace:inference`, targeting the service
   account that production should act as. Claims that are not matched are not checked, so both
   are needed: without `environment` a preview deployment would mint production tokens.
4. Verify a real Vercel token carries **no `jti` claim** (decode one from a deployment, e.g. the
   header on a request in the function logs). The exchange rejects an assertion the issuer
   replay-protects with a `jti` it does not recognise, and this is the cheapest way to find that
   out before switching production over.
5. Set the environment variables in Vercel (production only): `IDENTITY_PROVIDER=vercel_oidc`,
   `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID` (a raw UUID),
   `ANTHROPIC_SERVICE_ACCOUNT_ID`, `ANTHROPIC_WORKSPACE_ID`. Redeploy, then run one real model
   call through the app (ingest a short PDF) and confirm it succeeds.
6. **Delete the production API key** in the console and remove `ANTHROPIC_API_KEY` from the
   production environment. Until then both credentials exist and the key is what would be used if
   federation were misconfigured, which is exactly what step 5 is meant to rule out.

The container refuses to start when only half of this is configured - federation ids without an
`IDENTITY_PROVIDER`, or a provider without the ids - rather than failing on the first model call.
