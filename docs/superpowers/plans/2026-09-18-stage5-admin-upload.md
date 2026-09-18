# Stage 5 (optional): Admin Upload, Background Jobs on Vercel, Federation, AWS Worker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Optional by decision (spec section 2, section 10). Build it only if operating through the CLI turns out to be a chore. Written now so the decision can be made with the cost in view.

**Goal:** An admin uploads sources, triggers generation and publishes from the browser; ingestion and generation run as background jobs on Vercel without exceeding function duration limits; production authenticates to Anthropic through Workload Identity Federation instead of a stored key; the same jobs can run on AWS through an SQS worker.

**Architecture:** No new concepts. The HTTP upload route calls the same `SourceService.register` the CLI calls and enqueues the same `ingest_source` job. A `vercel_function` job runner adapter self-invokes a `/api/jobs/run` endpoint with a shared secret; the pipeline gains `run_next_step`, so each invocation performs one resumable step and re-enqueues the next, which keeps every function call well inside the duration limit. An SQS worker command consumes the identical messages on AWS. Federation is an identity-token provider adapter fed by the `x-vercel-oidc-token` request header.

**Tech Stack:** As before, plus `python-multipart` (FastAPI file uploads) and `httpx2` (already a dependency through the Anthropic SDK) for the self-invocation.

**Spec:** sections 5 (upload path reuses the pipeline), 8 (admin pane), 9 (federation, AWS readiness), 10 (stage 5).

**Prerequisites:** Stages 1 to 4 merged and deployed.

**Estimated size:** 9 tasks, roughly 40% backend, 40% frontend, 20% operations.

---

## File structure

```
api/teachme/ingestion/pipeline.py                 + run_next_step(source_id) -> bool
api/teachme/adapters/job_runner/vercel_function.py  self-invoking runner
api/teachme/adapters/identity/__init__.py
api/teachme/adapters/identity/vercel_oidc.py      identity token from the request header (contextvar)
api/teachme/adapters/identity/aws.py              identity token from a file (EKS/IRSA), thin wrapper
api/teachme/adapters/llm/anthropic.py             + credentials= for federation
api/teachme/container.py                          + federation wiring, runner selection
api/teachme/routes/jobs.py                        POST /api/jobs/run (secret-protected)
api/teachme/routes/admin_sources.py               upload, delete, reingest, generate, publish, capabilities
api/teachme/routes/schemas.py                     + AdminJob, Capabilities
api/teachme/cli/main.py                           + worker (SQS consumer)
api/teachme/settings.py                           + job_runner "vercel_function", job_runner_secret, self_base_url,
                                                    federation ids, vercel_oidc flag
vercel.ts                                         function maxDuration for api/index.py
app/admin/page.tsx                                + upload pane, actions
components/UploadPane.tsx, SourceRow.tsx
hooks/useAdminActions.ts
```

---

### Task 1: One-step pipeline execution

**Files:** modify `api/teachme/ingestion/pipeline.py`; test `api/tests/ingestion/test_pipeline.py` (append)

- Add `run_next_step(source_id) -> bool` that performs exactly one step (extract, chunk, or index) based on the resume point, commits, and returns `True` when more steps remain. `ingest_source` becomes `while self.run_next_step(source_id): pass` plus the final reload, so CLI behaviour is unchanged.
- Test: after `run_next_step` once, status is `chunking` and pages exist; after twice, `indexing`; after three times, `ready` and the function returns `False`. A failure inside one step marks `failed` with the right `resume_status`, same as today.

Commit: `refactor: pipeline exposes run_next_step for job-sized execution`

---

### Task 2: Generation as a job

**Files:** modify `api/teachme/services/tutorial.py`, `api/teachme/scope.py`; test `api/tests/services/test_tutorial_service.py` (append)

- Split `TutorialService.generate` into `plan_generation(subject, ...) -> list[GenerationUnit]` (outline+glossary unit, then one unit per part and language) and `run_unit(unit)`. `generate` runs all units in order (CLI). Job handlers: `generate_subject` (creates the outline unit, then enqueues one `generate_unit` job per part and language), `generate_unit`. Units are idempotent (regenerating a part's content replaces it).
- Register both handlers in `Scope.job_runner` next to `ingest_source`.

Commit: `feat: tutorial generation as idempotent job units`

---

### Task 3: Self-invoking Vercel job runner and the jobs endpoint

**Files:** create `api/teachme/adapters/job_runner/vercel_function.py`, `api/teachme/routes/jobs.py`; modify `settings.py`, `scope.py`, `app.py`, `vercel.ts`; tests `api/tests/adapters/test_vercel_function_runner.py`, `api/tests/routes/test_jobs_route.py`

- Settings: `job_runner: Literal["inprocess", "sqs", "vercel_function"]`, `job_runner_secret: SecretStr | None`, `self_base_url: str | None` (Vercel sets `VERCEL_URL`; the adapter uses `https://{VERCEL_URL}` when `self_base_url` is unset).
- `VercelFunctionJobRunner(base_url, secret, jobs)`: `enqueue` creates the job row (`queued`) and POSTs `{job_id, kind, payload}` to `{base_url}/api/jobs/run` with header `x-job-secret`, in a daemon thread with a short timeout, never waiting for completion. A failed POST marks the job `failed` with the error.
- `POST /api/jobs/run`: rejects a missing or wrong secret with 401 (constant-time compare); loads the job; marks `running`; calls the handler; for `ingest_source` calls `pipeline.run_next_step` and, if more remains, re-enqueues the same job payload; marks `done`/`failed`. Each invocation does one step, so a 400-page book becomes many short calls.
- `vercel.ts`: set the Python function's `maxDuration` to the plan's maximum (check the account plan; 300 s is the default) so a single read-pages batch always fits.
- Tests: the runner posts the right body and header (stub HTTP), marks failure on connection error; the endpoint enforces the secret and runs one step per call (fake stack).

Commit: `feat: self-invoking vercel job runner and jobs endpoint`

---

### Task 4: Admin source routes

**Files:** create `api/teachme/routes/admin_sources.py`; modify `schemas.py`, `app.py`, `pyproject.toml` (`python-multipart`); test `api/tests/routes/test_admin_sources.py`

Routes (all `AdminUser`):
- `GET /api/admin/capabilities` -> `{accepted_media_types: [...]}` from `SourceService.accepted_media_types()` for the file picker.
- `POST /api/admin/subjects/{id}/sources` multipart `file`: reads bytes (Vercel accepts request bodies up to 100 MB), `register`, `enqueue("ingest_source")`, returns `AdminSource` plus `job_id`. 415 on unaccepted type (from `UnsupportedMediaType`), 409 when published (`SubjectLocked`).
- `DELETE /api/admin/sources/{id}`; `POST /api/admin/sources/{id}/reingest`; `GET /api/admin/jobs/{id}` -> `AdminJob {id, kind, status, attempts, error}`.
- `POST /api/admin/subjects/{id}/generate` -> enqueues `generate_subject`; `POST /api/admin/subjects/{id}/publish` and `/unpublish` -> `TutorialService`.
- Tests through `TestClient` with the admin role override: upload a `make_pdf(2)` file, poll the job (in-process runner completes synchronously), source becomes `ready`; a `.zip` gets 415; a student gets 403.

Commit: `feat: admin upload, reingest, delete, generate and publish routes`

---

### Task 5: Admin upload pane (frontend)

**Files:** create `components/UploadPane.tsx`, `components/SourceRow.tsx`, `hooks/useAdminActions.ts`; modify `app/admin/page.tsx`, `lib/api/admin.ts`, `lib/api/types.ts`, `lib/i18n.ts`; tests `components/__tests__/UploadPane.test.tsx`

- `UploadPane`: file input whose `accept` comes from `/api/admin/capabilities`, disabled while the subject is published, upload button, per-file progress derived from polling `GET /api/admin/subjects/{id}/sources` every 3 s while any source is not `ready`/`failed`; shows status, page count, language, error.
- `SourceRow`: delete and reingest buttons (confirm dialog), hidden when published.
- Subject actions: Generate, Publish, Unpublish, with the `tutorial status` summary (needs `GET /api/admin/subjects/{id}/status` mirroring `TutorialService.status`; add it to Task 4).
- On the learn screen, admins see the pane in the right column for draft subjects only (spec section 8 layout); students never see it.

Commit: `feat(web): admin upload pane and subject actions`

---

### Task 6: Workload Identity Federation for production

**Files:** create `api/teachme/adapters/identity/vercel_oidc.py`, `aws.py`; modify `adapters/llm/anthropic.py`, `container.py`, `settings.py`, `app.py`; tests `api/tests/adapters/test_identity.py`

- Settings: `anthropic_federation_rule_id`, `anthropic_organization_id`, `anthropic_service_account_id`, `anthropic_workspace_id` (all optional), `identity_provider: Literal["none", "vercel_oidc", "file"]`, `identity_token_file`.
- `vercel_oidc.py`: a `ContextVar[str | None]` for the current request's token; a FastAPI middleware in `app.py` copies the `x-vercel-oidc-token` header into it; `VercelOidcIdentity()` is a zero-argument callable returning the current token or raising a clear error when absent (CLI runs must use a key or a file).
- `aws.py`: `FileIdentity(path)` returning the file contents (fresh read each call, matching the SDK's rotation semantics).
- `AnthropicLLM(credentials=...)`: when the container has federation settings and an identity provider, build `WorkloadIdentityCredentials(identity_token_provider=<callable>, federation_rule_id=..., organization_id=..., service_account_id=..., workspace_id=...)` and pass `credentials=` to `Anthropic(...)`; otherwise fall back to `api_key`.
- Console steps (operations, not code): register the Vercel team issuer `https://oidc.vercel.com/<team>` as a Custom OIDC issuer with discovery; raise its maximum token lifetime to 2 hours; create a rule matching claims `project_id` = the project id and `environment` = `production`, scope `workspace:inference`, target a service account; verify a real Vercel token carries no `jti` claim; set the four `ANTHROPIC_*` federation variables in Vercel; then delete the production API key.
- Tests: the context var round trip; the container picks federation when configured and a key otherwise (construct the client with a stub to assert which arguments were passed).

Commit: `feat: workload identity federation via vercel oidc header`

---

### Task 7: SQS worker for AWS

**Files:** modify `api/teachme/cli/main.py`; create `api/teachme/adapters/job_runner/sqs_worker.py`; test with moto

- `SqsWorker(queue_url, region, handlers, jobs)`: long-polls, for each message loads the job, runs the handler (one step for `ingest_source`, re-enqueuing when more remains), deletes the message on success, leaves it for redelivery on failure with attempts incremented, stops after `max_messages` or on SIGTERM.
- `teachme worker --once` processes what is queued and exits (testable with moto); without `--once` it loops.

Commit: `feat: sqs worker consuming the same job messages`

---

### Task 8: Rate limits and abuse controls for uploads

- Per-admin upload cap per hour in settings (`max_uploads_per_hour`), enforced in the route through the `jobs` table timestamps.
- Reject files above `max_upload_bytes` (default 50 MB) before reading the body fully (check `Content-Length`).
- Audit line in `llm_usage`'s neighbour: a new `admin_actions` table (who, what, when) written by every admin route. Migration `0004_admin_actions.sql`.

Commit: `feat: upload limits and admin action audit`

---

### Task 9: Deploy and verify

- Preview deployment with `JOB_RUNNER=vercel_function`, a generated `JOB_RUNNER_SECRET`, `SELF_BASE_URL` unset.
- Upload a 20-page PDF from the admin pane; watch the source move through statuses; generate; publish; run one part as a student.
- Confirm in `teachme usage` that costs are attributed and in the Vercel logs that no function call exceeded its duration.
- Switch production to federation (Task 6 operations), redeploy, repeat one upload, delete the API key.

---

## Decision aid

Choose stage 5 when at least one of these is true: material changes more often than monthly; someone other than the developer must add material; more than three subjects are live. Otherwise the CLI path costs nothing and this plan stays on the shelf.
