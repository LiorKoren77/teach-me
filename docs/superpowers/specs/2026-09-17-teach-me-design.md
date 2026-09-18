# teach-me: design specification

Date: 2026-09-17
Status: approved in conversation, pending written review

## 1. Purpose

teach-me turns textbook material into a guided tutorial with an assessment
dialog. An admin ingests PDFs (and images or text files) for a subject. The
system digests them, writes a tutorial split into parts, teaches each part in
the student's chosen language, asks questions, grades the answers, re-explains
weak sections, and keeps asking until the student passes. Students see their
progress per part.

Source material may be in one language (for example Portuguese) and teaching in
another (for example Hebrew). Key terminology is then shown in both languages.

## 2. Decisions taken

These were decided in the design conversation and are not open.

| Topic | Decision |
|---|---|
| Hosting now | Vercel: Next.js frontend, Python FastAPI function under `api/`, Marketplace Postgres with pgvector, Vercel Blob |
| Hosting later | Must be movable to AWS. Storage, jobs and database sit behind ports with adapters; S3 and SQS adapters ship from day one |
| LLM provider | Anthropic first, through the official SDK. Other providers later as adapters behind the same port. No LangChain or LiteLLM in the core |
| Models per call site | Opus 5 for outline, teaching text, question bank, re-explanation, contextual chunking and page reading. Sonnet 5 for grading. Haiku 4.5 for the relevance check. All configurable |
| Embeddings | Voyage `voyage-4`, reranker `rerank-2.5`. Embedding model is a pinned infrastructure choice recorded on every chunk |
| Auth | Clerk. Two roles, admin and student, carried as a role claim from Clerk public metadata |
| Anthropic credentials | Service-account API key with expiry during development. Workload Identity Federation from Vercel's OIDC issuer in production, before students arrive. Voyage and Clerk keys remain environment variables |
| Sources | Belong to subjects, not students. Uploaded by admins only |
| Subject lifecycle | Draft (sources editable, admin-only visible) and published (sources locked, visible to students) |
| Ingestion path | Command-line first, run by an operator against the hosted database. HTTP upload route, Vercel job runner and admin upload pane are stage 5, **optional**, decided later |
| Tutorial generation | Once per subject, outline version and language. Shared by all students. All enabled languages generated at publish |
| Languages | Hebrew, English, Portuguese for teaching. Source language may be anything Claude reads |
| Question format | Mix, mostly free text, roughly four free text to one multiple choice |
| Dialog | Strict: tutor asks, student answers. No free chat. Reconsidered after cost is measured |
| Progress | Per student, subject and part. Parts unlock in order. Passed at 50% of a round by default, at most 3 rounds by default, 5 questions per round by default. All subject settings |
| Answer relevance | Lexical scorer (no model) routes to grader, to a Haiku check, or to rejection. Never rejects on lexical score alone |
| Figures | Every page is read by Claude so figures, maps and diagrams are described and referenced by page |
| Portability of digested material | LLM outputs are written as a Markdown/JSON digest bundle; the database is a derived index. Export and import commands round-trip the bundle |
| Repository | New repository `LiorKoren77/teach-me` under the personal GitHub account, never the company account. Python package name `teachme` |
| Frontend router | Next.js App Router |

## 3. Architecture

### 3.1 Dependency rule

Four layers. Dependencies point one way: routes -> services -> domain and
ports. Adapters implement ports. One composition root builds adapters from
settings. Domain modules do no I/O. Vendor SDKs are imported only in adapters.

### 3.2 Module layout

Small modules, one responsibility each, adapters wherever more than one
implementation is possible.

```
api/index.py             FastAPI app factory, mounts routers (Vercel entry)
api/teachme/
  settings.py            env -> typed Settings; every model and adapter choice
  container.py           composition root: one adapter per port from Settings

  ports/                 Protocol classes only, one file per port, zero logic
    llm.py               generate_structured / stream_text / run_with_tools / capabilities
    embeddings.py        embed_documents / embed_query
    reranker.py          rerank
    file_store.py        put / get / delete / signed_url
    job_runner.py        enqueue(job_name, payload)
    chunk_search.py      dense / lexical / upsert / delete_by_source

  adapters/              one sub-package per port, one file per implementation
    llm/anthropic.py                    (openai.py, litellm.py later, same shape)
    embeddings/voyage.py
    reranker/voyage.py   reranker/noop.py
    file_store/local.py  file_store/vercel_blob.py  file_store/s3.py
    job_runner/inprocess.py  job_runner/vercel_function.py  job_runner/sqs.py
    chunk_search/pgvector.py
    identity/vercel_oidc.py  identity/aws.py   (identity-token providers for federation)
    db/engine.py         db/migrations/

  domain/                pure logic, no I/O, no SDKs
    models.py            Subject, Source, Page, Figure, Part, Section, GlossaryTerm,
                         Question, Attempt, AttemptQuestion, PartProgress
    languages.py         registry: he / en / pt with name, direction, stopwords, notes
    text/normalize.py    unicode normalization, tokenization, stopwords, Hebrew prefixes
    relevance/scorer.py  answer -> score, band, signals
    relevance/router.py  band -> grader | haiku | reject
    glossary/render.py   resolve {{term:slug|words}} placeholders
    assessment/scoring.py        round score, weak-section selection
    assessment/sampling.py       question selection weighted toward weak sections
    assessment/transitions.py    part status state machine
    retrieval/fusion.py          reciprocal rank fusion

  ingestion/             admin-time pipeline, one step per module
    extract.py           dispatch on media type -> page texts + figures
    pdf_pages.py         split PDF into page batches; render page images
    read_pages.py        Claude reads a batch: text, printed page number, figures
    detect_language.py   one structured call per source
    contextualize.py     Claude contextual chunking with page ranges
    index.py             embed chunks, write through ChunkSearch
    bundle.py            read/write the digest bundle
    pipeline.py          ingest_source(source_id) with status transitions and resume

  retrieval/
    hybrid.py            dense + lexical -> fusion -> rerank
    tool.py              search_knowledge_base tool for the grader, scoped to a subject

  generation/            one module per LLM output type, one prompt file each
    prompts/             outline.md, glossary.md, glossary_translate.md,
                         teaching.md, questions.md, reexplain.md
    outline.py           sources -> parts and sections with page ranges
    glossary.py          full text -> key terms; per-language translation
    teaching.py          part -> localized title, teaching text, key points, section summaries
    question_bank.py     part -> questions with rubric, key terms, exact values
    reexplain.py         weak sections + wrong answers -> alternative explanation
    validate.py          code checks on every generated object; one retry with errors

  grading/
    relevance_check.py   Haiku on-topic classifier
    grader.py            Sonnet grading with rubric, glossary and search tool

  services/              use cases; the only layer touching both ports and repositories
    subjects.py  sources.py  tutorial.py  learning.py  progress.py  usage.py

  repositories/          Postgres persistence, one file per aggregate
    subjects.py  sources.py  pages.py  figures.py  chunks.py  outlines.py
    content.py  glossary.py  questions.py  progress.py  attempts.py  jobs.py  usage.py

  auth/
    clerk.py             JWT verification, current_user dependency
    roles.py             role claim, require_admin dependency

  routes/                thin FastAPI routers, request/response schemas only
    subjects.py  learning.py  progress.py  pages.py (thumbnails)  admin.py (read-only)

  telemetry/
    usage.py             one row per LLM or embedding call
    prices.py            price table per model

  cli/
    main.py              ingest / generate / publish / export / import / usage / eval
```

Tests mirror the layout under `api/tests/`. Fakes for every port live in
`api/tests/fakes/` and double as the reference implementation of each port's
contract; each real adapter runs the same contract test file.

### 3.3 Existing code

`reference/rag/` holds the Insurellm agentic RAG code this project grew from.
Its contextual chunking becomes `ingestion/contextualize.py`, its hybrid search
and fusion become `retrieval/` and `domain/retrieval/fusion.py`, and its Voyage
calls move behind the embeddings and reranker ports. Prompts are rewritten to
be subject-neutral. The folder is deleted when stage 1 is complete.

## 4. Data model

Postgres with pgvector. UUID ids. Clerk user ids stored as strings; no user
table until a preference needs one.

**Subject and sources**

- `subjects`: name, state (draft | published), enabled languages, pass
  threshold, max rounds, questions per round, bank size per part, gloss
  frequency (first | every | never), current outline version, created by.
- `sources`: subject, filename, media type, file key, size, page count,
  detected language, status (uploaded | extracting | chunking | indexing |
  ready | failed), error text, pages read by vision count.
- `source_pages`: source, page index, printed page number, text (Markdown with
  inline figure blocks).
- `source_figures`: source, page index, ordinal, kind, caption, description.
- `chunks`: source, subject, content (situating context + original text), page
  range, embedding vector, embedding model name, lexical token column built by
  `domain/text/normalize.py` and indexed with the `simple` text-search config.

**Tutorial structure, language independent**

- `outlines`: subject, version, model.
- `parts`: outline, position, page references.
- `sections`: part, position, page references.
- `glossary_terms`: outline, slug, source-language term, definition, page refs.

**Tutorial content, per language**

- `part_content`: part, language, title, teaching text with placeholders, key
  points, status (generating | ready | failed).
- `section_content`: section, language, title, one-paragraph summary.
- `glossary_translations`: term, language, term text.
- `questions`: section, language, kind (free_text | multiple_choice), prompt,
  expected answer, rubric points, key terms (target and source forms), exact
  values, choices and correct choice.

**Student state**

- `part_progress`: user, subject, part, outline version, status, best score,
  rounds used, last activity. Unique (user, part).
- `attempts`: user, part, language, round number, status (active | passed |
  failed), started, finished.
- `attempt_questions`: attempt, question, position, answer text, relevance
  score, band, route, relevance-check verdict, grade (correct | partial |
  incorrect | off_topic | junk), rubric points covered, feedback, answered at.
- `reexplanations`: attempt, section ids, language, body with placeholders,
  model.

**Operations**

- `jobs`: kind, payload, status, attempt count, error.
- `llm_usage`: purpose, provider, model, input tokens, output tokens, cache
  read, cache write, cost, latency, optional user / subject / source /
  attempt.

Rules enforced by the schema: progress rows carry the outline version so
regeneration makes old progress visibly stale; chunks carry the embedding model
name so a changed setting is detected at query time.

## 5. Ingestion pipeline (stage 1)

**Entry.** `teachme ingest --subject NAME [--language he,en,pt] FILES...`
registers each file as a source, stores it through the file store, and calls
`ingest_source`. A later HTTP route calls the same function through a job
runner; the pipeline does not know the caller.

**Accepted media types** come from the LLM adapter's `capabilities()`. The
Anthropic adapter declares PDF, PNG, JPEG, GIF, WebP, plain text and Markdown.
Settings may narrow, never widen, that set. The command and any future upload
route both reject other types before storing anything.

**Steps.** Each step persists its output and advances the source status before
the next step starts; re-running resumes from the recorded status.

1. **Extract.** PDFs are split into page batches sized to stay well inside the
   output limit and sent as native PDF documents. Images are sent as images.
   Text files become one page. For every page Claude returns, as structured
   output: transcribed text as Markdown in the source language, the printed
   page number if visible, and a list of figures with kind, caption and a
   description of what the figure shows. Figure descriptions are written into
   the page text as marked blocks and stored in `source_figures`. Every page
   goes through Claude; there is no text-layer-only path, because figures live
   on text-layer pages too. A per-source page cap and a cost estimate with
   confirmation guard the spend.
2. **Detect language.** One structured call over a sample of pages; stored on
   the source; passed to later prompts.
3. **Contextualize.** Contextual chunking: pages are grouped into batches sent
   with surrounding pages as context; each chunk gets a 50-100 token situating
   context in the source language and records its page range. Full coverage of
   the input is validated in code.
4. **Index.** Chunks are embedded in batches and written with vector, lexical
   tokens and embedding model name in one insert.
5. **Ready.** Page count and vision statistics recorded.

**Digest bundle.** Every step writes its output to the bundle before the
database. From the command line the bundle also lands in a local folder.

```
digest/<subject>/<source>/
  meta.json          language, models, pipeline version, page count
  pages/023.md       page text with figure blocks
  figures.json
  chunks.jsonl       context, original text, page range (before embedding)
  embeddings.jsonl   chunk id, model name, vector
digest/<subject>/v<outline version>/
  outline.json
  glossary.json  glossary.<lang>.json
  parts/02.<lang>.md
  questions.<lang>.jsonl
```

`teachme export` writes a bundle from the database; `teachme import` loads one,
re-embedding only if the embedding model differs. Moving hosts is copy plus
import. Raw sources and local bundles are gitignored.

**Idempotency.** Re-ingesting a source deletes its pages, figures and chunks by
source id first. Deleting a source removes file, pages, figures and chunks in
one transaction. Both are refused while the subject is published.

**Failure.** Bounded retries with backoff inside each step. A step that still
fails marks the source failed with the error and does not stop other sources in
the same command. Non-zero exit if any source failed.

## 6. Tutorial generation (stage 2)

`teachme generate --subject NAME [--language X] [--part N] [--content-only]`
requires all sources ready. Every call writes to the bundle and the database
and logs usage tagged with subject and step. The full page text of the subject
is placed in a cached prompt prefix shared across all calls of a run.

1. **Outline.** One structured call with all pages in reading order plus the
   subject name: ordered parts, sections per part, page ranges for each.
   Guidance: 3-6 parts per chapter, one idea per section. Per-source outline
   plus merge if the input exceeds the context window.
2. **Glossary.** One structured call: key terms with slug, source-language
   form, definition, pages. Then one small call per enabled language producing
   the target-language form of each term.
3. **Teaching text**, per part and language. Input: the part's pages, the
   outline, the glossary, the target language. Output: localized title,
   teaching body as Markdown with placeholders, key points, per-section
   localized titles and summaries. Prompt asks for teaching not summarizing,
   figures referenced by page, strictly within the material.
4. **Question bank**, per part and language. Input: pages, teaching text,
   glossary. Output per question: section, kind, prompt, expected answer, 2-3
   rubric points, key terms including synonyms and the source-language form,
   exact values for factual questions, choices for multiple choice. Ratio
   about 4:1 free text to multiple choice. Bank size defaults to five times
   questions per round.

**Placeholders.** The model writes natural target-language prose and marks key
terms as `{{term:slug|words as written}}`. `domain/glossary/render.py` resolves
them: when teaching language differs from source language it appends the
source-language term, for example `הביוספרה (biosfera)`; when they match it
emits the words alone. Frequency per the subject setting. Rendering is
server-side; the resolved glossary is also returned for hover definitions.

**Validation** (`generation/validate.py`), before anything is stored: every
question's section exists; every page reference is inside the source; every
section has the minimum number of questions; no empty teaching text; every
placeholder resolves; every term has a translation in every enabled language.
A failure re-runs that single call once with the errors appended; a second
failure marks that item failed and the command reports it. Nothing partial is
published.

**Versions.** A full regenerate creates a new outline version. Content-only or
per-part regeneration reuses the current version. `teachme publish` switches
the subject to the newest complete version and resets progress for that
subject if the version changed.

## 7. Learning loop (stage 3)

Code-controlled state machine in `services/learning.py`. The model is called at
three fixed points only: relevance check, grading, re-explanation.

**Endpoints** (student identity from Clerk): list published subjects with
progress; open subject in a language; start part; begin round; submit answer;
continue after a failed round (streams the re-explanation). Stateless between
calls; everything needed is in the attempt.

**Transitions** (`domain/assessment/transitions.py`): not_started -> learning
on open; learning -> quizzing on first round; quizzing -> passed |
reinforcing | stalled after a round; reinforcing -> quizzing on next round;
stalled -> learning on explicit retry with a fresh attempt. Locked is derived:
a part is locked until the previous part is passed.

**Sampling.** Never repeats a question within an attempt. Round one spreads
across sections evenly. Later rounds weight by wrong answers with at least one
question per section. Preserves the free-text / multiple-choice ratio.

**Answering.** Multiple choice is graded in code. Free text goes through the
relevance chain:

- Junk (empty, over length cap, punctuation or URL only, repeated characters):
  rejected, no model call.
- Scorer signals: key-term fuzzy hits; exact-value match (sends short factual
  answers straight to high); topic overlap with section vocabulary after
  stopwords; question echo counts as neutral; too-short answers fall to
  uncertain, never low.
- High band: straight to grader. Uncertain and low: Haiku check (on_topic |
  off_topic | unclear); off_topic rejected without grading; others graded.
- Every outcome stored on the attempt question with score, band, route and
  verdicts. Thresholds per language in settings, tuned from this data.

**Grading.** One structured Sonnet call: question, expected answer, rubric,
glossary, answer wrapped as data, with the subject-scoped search tool available
when the rubric is not enough. Output: correct | partial | incorrect, rubric
points covered, missed section concepts, one or two sentences of feedback in
the session language that do not reveal the full answer during an active
round. Grader also returns off_topic as a backstop.

**Scoring.** Correct 1, partial 0.5, else 0. Pass at or above the subject
threshold. Best score updated always.

**Reinforcement.** Weakest sections (cap 3, settings) -> one Opus call with
their pages, original teaching text and the student's wrong answers ->
alternative explanation with new framing, analogy, worked example, same
placeholders. Streamed and stored. Next round samples with weak-section weights.

**Stalled.** After the round cap: plain message and a retry option that starts
a fresh attempt. Nothing is permanently locked.

**Limits.** Answer length cap; per-student submission rate limit; one active
attempt per student per part. Junk and off-topic count as wrong.

## 8. Student frontend (stage 4)

Next.js App Router, Clerk, Tailwind, react-markdown, SSE client.

**Routes.** `/` sign-in and published subjects with progress. `/learn/[subjectId]`
the working screen. `/admin` read-only for the admin role: subjects, sources
with status, usage summaries.

**Learn screen layout.**

```
┌──────────────────────────────────────────────┬───────────────┐
│ Subject tabs · Part progress  Part 3 of 5    │  Sources      │
├──────────────────────────────────────────────┤  ch3.pdf ✓    │
│ TEACHING: teaching text or re-explanation,   │  atlas.pdf ✓  │
│ glossed terms, figure refs with thumbnails   │               │
├──────────────────────────────────────────────┤  (upload:     │
│ DIALOG: question, answer box, feedback,      │   stage 5,    │
│ round result                                 │   optional)   │
└──────────────────────────────────────────────┴───────────────┘
```

Right pane stacks under the main area on narrow screens.

**Components**, one file each: SubjectTabs, PartProgress, TeachingPane,
DialogPane, QuestionCard (free text and multiple choice variants),
FeedbackCard, RoundResult, SourceList, LanguagePicker, FigureThumbnail. Plain
props, no fetching.

**Data layer.** One hooks module per backend concern wrapping authenticated
fetch with the Clerk token. Streams use the SSE client. All session state is
server-side; the frontend refetches the attempt after each submit.

**Language and direction.** Session language chosen from the subject's enabled
languages, last choice remembered in the browser. Document direction switches
to RTL for Hebrew at the layout root. UI labels from a small translations file
for the three languages; tutorial content arrives localized.

**Figures.** FigureThumbnail requests a rendered page image from a backend
endpoint that renders on demand with a permissively licensed renderer and
caches in the file store. Click opens the full page.

**Dialog behavior.** One question at a time. Submit locks the box, shows
feedback, continue loads the next question or round result. Rejections show a
fixed message and reopen the box. Failed round: score, streamed re-explanation
into the teaching pane, offer to start the next round. Passed round: score, next
part unlocks. Student text rendered as plain text, never Markdown.

**Absent by decision.** No free chat box. No client-side scoring. No local
persistence beyond language preference.

## 9. Configuration, deployment, measurement, evaluation

**Settings.** One typed module reads the environment: adapter per port, model
per call site, database URL, file store, enabled languages, relevance
thresholds per language, limits (answer length, rate limits, page cap,
reinforcement cap), price table. Missing required values fail at startup by
name.

**Local development.** Docker Compose Postgres with pgvector; local file store;
in-process job runner; personal Anthropic key in `.env.local`. Fake adapters
selectable through settings so the stack runs with no keys for frontend work.

**Vercel.** Python function entry unchanged. `requirements.txt` pinned.
Marketplace Postgres and Vercel Blob provisioned when reached; connection
details as Vercel environment variables. Migrations run from the command line
before deploys; startup refuses to serve on a schema mismatch. Anthropic
credentials move to Workload Identity Federation before students arrive:
Vercel team OIDC issuer registered as a custom OIDC issuer with discovery;
rule matches on `project_id` claim and `environment=production`; issuer
maximum token lifetime raised to 2 hours; identity token read from the
`x-vercel-oidc-token` request header and handed to the SDK as a callable;
confirm the Vercel token carries no `jti` claim during setup; local
development stays on a key.

**AWS readiness.** S3 file store and SQS job runner with contract tests against
a local emulator; same Postgres schema on RDS; AWS identity-token provider.
Nothing else names a host.

**Cost measurement.** Every LLM and embedding call writes a usage row.
`teachme usage` and the admin page summarize per subject (one-off cost of a
book), per attempt (recurring cost per student) and per relevance route (what
the lexical and Haiku layers save).

**Evaluation harness.** `teachme eval`: one short fixture source per language,
an ideal outline, graded student answers including off-topic and junk. Reports
outline agreement, grading agreement, relevance false-reject rate and cost.
Changing a model in settings and re-running yields a comparison table.

**Security.** Clerk on every request; admin routes require the role claim;
students reach only published subjects and their own rows, enforced in
repositories by user id; student text is data in prompts and plain text in
renders; rate limits and length caps; no answer text or secrets in usage rows
or logs.

## 10. Stages

1. Ingestion library and CLI, hosted database, file store, digest bundle,
   usage telemetry, settings and container, all ports with first adapters
   including S3 and SQS. Delete `reference/rag/` at the end.
2. Tutorial generation: outline, glossary, teaching text, question bank,
   validation, versions, publish.
3. Learning loop: endpoints, transitions, sampling, relevance chain, grading,
   reinforcement, progress, limits.
4. Student frontend, admin read-only page, page thumbnails, eval harness
   wired to real fixtures.
5. Optional, decided later: HTTP upload route, Vercel job runner, admin upload
   pane.

## 11. Risks on record

- Postgres full-text has no Hebrew stemmer; lexical search relies on the
  normalizer's prefix stripping. Adequate for chapter-sized subjects; the eval
  harness shows if not.
- Relevance thresholds start as guesses; they are logged from day one.
- Vercel function duration bounds on-demand paths; ingestion and generation run
  from the command line by design.
- Figure descriptions are the model's words; page thumbnails are the
  mitigation.
- Vercel OIDC token reuse depends on the token carrying no `jti` claim;
  verified during federation setup.
