# Stage 4: Student Frontend, Admin View, Thumbnails, Eval Harness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in student picks a subject and a language, reads a part, answers questions, sees feedback and re-explanations, and watches parts unlock; an admin sees subjects, sources and usage read-only; teaching text can point at page images; a CLI eval harness scores generation and grading against fixtures.

**Architecture:** Next.js App Router (the scaffold in this repo, Next 16), Clerk for sign-in, Tailwind, react-markdown for rendered teaching text, `@microsoft/fetch-event-source` for the re-explanation stream. All state lives on the backend; the frontend holds only the current view and refetches after each action. One hooks module per backend concern; one component per file. Right-to-left layout for Hebrew at the root. Backend gains three small pieces: a page-image endpoint (pypdfium2 render, cached in the file store), a read-only sources endpoint for students, and `teachme eval`.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, `@clerk/nextjs`, `react-markdown` + `remark-gfm`, `@microsoft/fetch-event-source`, Vitest + Testing Library for components, Playwright for one end-to-end flow; backend adds `pypdfium2`.

**Spec:** `docs/superpowers/specs/2026-09-17-teach-me-design.md` section 8 (frontend), section 9 (eval harness), section 3 (figures and thumbnails).

**Prerequisites:** Stages 1 to 3 merged. The backend runs locally with `uvicorn index:app --app-dir api --port 8000` against the fake stack, and a published subject exists (`teachme ingest`, `generate`, `publish`).

**Important for implementers:** this repository's Next.js version may differ from your training data. Before writing any Next.js code, read `node_modules/next/dist/docs/` for routing, layouts, `proxy`/middleware and client components, as `AGENTS.md` instructs. For Clerk, read the installed `@clerk/nextjs` README or fetch https://clerk.com/docs/quickstarts/nextjs before wiring the provider and route protection. Where this plan names a Next.js or Clerk API, verify it against those docs and prefer the documented current name.

---

## Conventions

- Backend tasks: as in earlier stages (venv, `pytest -q`, ruff, pydantic rule).
- Frontend tasks: `source ~/.nvm/nvm.sh && nvm use 22`, `npm run lint`, `npm run test` (Vitest), `npm run build` must pass before a commit. Components take plain props and never fetch. All fetching lives in `lib/api/*.ts` and `hooks/*.ts`. UI strings come from `lib/i18n.ts`, never inline. Student-written text is rendered as plain text only.
- Frontend calls the backend through relative `/api/...` URLs. In development `next.config.ts` rewrites `/api/:path*` to `http://localhost:8000/api/:path*`; on Vercel the Python function serves `/api` directly, so no rewrite applies there.

## File structure

```
api/teachme/adapters/pdf_render.py               render a PDF page to PNG (pypdfium2)
api/teachme/services/thumbnails.py               ThumbnailService: cache PNG per (source, page) in the file store
api/teachme/routes/pages.py                      GET /api/subjects/{id}/pages/{global_index}/image
api/teachme/routes/subjects.py                   + GET /api/subjects/{id}/sources
api/teachme/eval/__init__.py
api/teachme/eval/fixtures/{en,he,pt}/source.md   short fixture sources
api/teachme/eval/fixtures/{en,he,pt}/expected.json  expected outline bounds and graded answers
api/teachme/eval/runner.py                       EvalRunner: runs generation and grading, computes agreement
api/teachme/cli/main.py                          + eval command

next.config.ts                                   dev rewrite to the backend
app/layout.tsx                                   ClerkProvider, html dir/lang from the language cookie
app/page.tsx                                     landing: sign-in or subject list with progress
app/learn/[subjectId]/page.tsx                   learn screen
app/admin/page.tsx                               read-only admin
proxy.ts (or middleware.ts, per Next docs)       Clerk route protection for /learn and /admin
lib/i18n.ts                                      UI strings for he/en/pt + direction
lib/api/client.ts                                fetch with Clerk token, error mapping
lib/api/subjects.ts, learning.ts, admin.ts       typed API functions mirroring backend schemas
lib/api/types.ts                                 TypeScript types mirroring the backend pydantic models
lib/language.ts                                  session language preference (cookie + localStorage)
hooks/useSubjects.ts, useLearningSession.ts, useReexplainStream.ts
components/SubjectTabs.tsx, PartProgress.tsx, TeachingPane.tsx, DialogPane.tsx, QuestionCard.tsx,
components/FeedbackCard.tsx, RoundResult.tsx, SourceList.tsx, LanguagePicker.tsx, FigureThumbnail.tsx
components/__tests__/*.test.tsx
e2e/learn.spec.ts                                Playwright happy path against the fake backend
vitest.config.ts, playwright.config.ts
```

---

## Phase A: Backend additions

### Task 1: PDF page rendering and cached thumbnails

**Files:**
- Create: `api/teachme/adapters/pdf_render.py`, `api/teachme/services/thumbnails.py`, `api/teachme/routes/pages.py`
- Modify: `pyproject.toml` (add `pypdfium2>=4.30`), `api/teachme/scope.py` (thumbnail_service), `api/teachme/app.py` (mount router)
- Test: `api/tests/adapters/test_pdf_render.py`, `api/tests/services/test_thumbnails.py`, `api/tests/routes/test_pages_route.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/adapters/test_pdf_render.py`:

```python
from __future__ import annotations

from teachme.adapters.pdf_render import render_page_png
from tests.helpers import make_pdf


def test_render_page_png_returns_png_bytes_of_requested_size():
    png = render_page_png(make_pdf(2), page_index=1, width=200)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    import struct
    width, height = struct.unpack(">II", png[16:24])
    assert width == 200 and height > width  # A4 portrait
```

`api/tests/services/test_thumbnails.py`:

```python
from __future__ import annotations

from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.services.thumbnails import ThumbnailService
from tests.helpers import make_pdf


class _Sources:
    def __init__(self, pdf):
        self.pdf = pdf

    def get(self, source_id):
        from types import SimpleNamespace
        return SimpleNamespace(id=source_id, media_type="application/pdf", file_key="k", page_count=3)


def test_thumbnail_rendered_once_then_served_from_cache():
    files = InMemoryFileStore()
    files.put("k", make_pdf(3), "application/pdf")
    service = ThumbnailService(files, _Sources(None), width=120)
    from uuid import uuid4
    source_id = uuid4()
    first = service.png(source_id, page_index=2)
    assert first[:4] == b"\x89PNG"
    assert files.exists(f"thumbnails/{source_id}/002-w120.png")
    files.put("k", b"garbage", "application/pdf")  # cache must not re-render
    assert service.png(source_id, page_index=2) == first
```

`api/tests/routes/test_pages_route.py` (reuse the `api` fixture from `test_api_flow.py` by importing it):

```python
from __future__ import annotations

from tests.routes.test_api_flow import api  # noqa: F401


def test_page_image_endpoint_maps_global_index_to_source_page(api):
    client, subject, *_ = api
    response = client.get(f"/api/subjects/{subject.id}/pages/4/image")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert client.get(f"/api/subjects/{subject.id}/pages/999/image").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest -q api/tests/adapters/test_pdf_render.py api/tests/services/test_thumbnails.py api/tests/routes/test_pages_route.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add `pypdfium2>=4.30` to dependencies**, `uv pip install -e ".[dev]"`, recompile `requirements.txt`.

- [ ] **Step 4: Write `adapters/pdf_render.py`**

```python
from __future__ import annotations

import io

import pypdfium2 as pdfium


def render_page_png(pdf: bytes, *, page_index: int, width: int) -> bytes:
    """Rasterize one page to PNG at the given width (height follows the page's aspect ratio)."""
    document = pdfium.PdfDocument(pdf)
    try:
        page = document[page_index]
        page_width = page.get_width()
        scale = width / page_width
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
```

- [ ] **Step 5: Write `services/thumbnails.py`**

```python
from __future__ import annotations

from uuid import UUID

from teachme.adapters.pdf_render import render_page_png
from teachme.ports.file_store import FileNotFound, FileStore


class ThumbnailService:
    """PNG of a source page, rendered on first request and cached in the file store."""

    def __init__(self, files: FileStore, sources, width: int = 800) -> None:
        self._files = files
        self._sources = sources
        self._width = width

    def _key(self, source_id: UUID, page_index: int) -> str:
        return f"thumbnails/{source_id}/{page_index:03d}-w{self._width}.png"

    def png(self, source_id: UUID, page_index: int) -> bytes:
        key = self._key(source_id, page_index)
        try:
            return self._files.get(key)
        except FileNotFound:
            pass
        source = self._sources.get(source_id)
        if source.media_type != "application/pdf":
            raise FileNotFound(key)
        if source.page_count is not None and not 0 <= page_index < source.page_count:
            raise FileNotFound(key)
        png = render_page_png(self._files.get(source.file_key), page_index=page_index, width=self._width)
        self._files.put(key, png, "image/png")
        return png
```

- [ ] **Step 6: Write `routes/pages.py`** and mount it in `app.py`; add `thumbnail_service` to `Scope`

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from teachme.auth.clerk import CurrentUser
from teachme.ports.file_store import FileNotFound
from teachme.routes.deps import ScopeDep

router = APIRouter(prefix="/api/subjects", tags=["pages"])


@router.get("/{subject_id}/pages/{global_index}/image")
def page_image(subject_id: UUID, global_index: int, user: CurrentUser, scope: ScopeDep) -> Response:
    """Global page indices are the ones the tutorial text refers to; map them back to a source page."""
    subject = scope.subjects.get(subject_id)
    corpus = scope.learning_service.corpus_for(subject)
    if not 0 <= global_index < corpus.total_pages:
        raise HTTPException(status_code=404, detail="no such page")
    source_id, page_index = corpus.locate(global_index)
    try:
        png = scope.thumbnail_service.png(source_id, page_index)
    except FileNotFound:
        raise HTTPException(status_code=404, detail="page image unavailable") from None
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
```

Add to `LearningService` a public `corpus_for(subject)` returning `self._corpus(subject)` (it also enforces published state through `_require_published`). Add to `Scope`:

```python
    @cached_property
    def thumbnail_service(self) -> ThumbnailService:
        return ThumbnailService(self.shared.files, self.sources)
```

- [ ] **Step 7: Run to verify they pass, then commit**

Run: `pytest -q api/tests/adapters/test_pdf_render.py api/tests/services/test_thumbnails.py api/tests/routes`
Expected: all pass

```bash
git add pyproject.toml requirements.txt api/teachme/adapters/pdf_render.py api/teachme/services/thumbnails.py api/teachme/routes/pages.py api/teachme/scope.py api/teachme/app.py api/teachme/services/learning.py api/tests
git commit -m "feat: page image endpoint with cached pdf rendering"
```

---

### Task 2: Student-facing sources endpoint

**Files:**
- Modify: `api/teachme/routes/subjects.py`, `api/teachme/routes/schemas.py`
- Test: `api/tests/routes/test_api_flow.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_student_sees_read_only_source_list(api):
    client, subject, *_ = api
    sources = client.get(f"/api/subjects/{subject.id}/sources").json()
    assert sources == [{"filename": "ch1.pdf", "media_type": "application/pdf", "page_count": 6}]
```

- [ ] **Step 2: Run to verify it fails** (`404`).

- [ ] **Step 3: Implement.** In `schemas.py` add `class StudentSource(BaseModel): filename: str; media_type: str; page_count: int | None`. In `routes/subjects.py`:

```python
@router.get("/{subject_id}/sources", response_model=list[StudentSource])
def sources(subject_id: UUID, user: CurrentUser, scope: ScopeDep) -> list[StudentSource]:
    subject = scope.subjects.get(subject_id)
    if subject.state != SubjectState.PUBLISHED:
        raise NotAllowed("subject is not published")
    return [StudentSource(filename=s.filename, media_type=s.media_type, page_count=s.page_count)
            for s in scope.sources.list_by_subject(subject.id) if s.status == SourceStatus.READY]
```

(import `NotAllowed` from `teachme.services.learning`, `SourceStatus` from domain models.)

- [ ] **Step 4: Run, then commit**

```bash
git add api/teachme/routes api/tests/routes/test_api_flow.py
git commit -m "feat: read-only source list for students"
```

---

### Task 3: Eval harness

**Files:**
- Create: `api/teachme/eval/__init__.py`, `api/teachme/eval/runner.py`, `api/teachme/eval/fixtures/en/source.md`, `.../en/expected.json`, same for `he` and `pt`
- Modify: `api/teachme/cli/main.py` (eval command)
- Test: `api/tests/eval/test_runner.py`

- [ ] **Step 1: Write the fixtures.** Each `source.md` is a self-contained 400 to 800 word explanatory text in its language on one topic (English: the water cycle; Hebrew: the water cycle; Portuguese: photosynthesis), with two `> **[Figure: ...]**` blocks so figure handling is exercised. Each `expected.json`:

```json
{
  "language": "en",
  "teach_in": ["en", "he"],
  "outline": {"min_parts": 1, "max_parts": 3, "min_sections": 2},
  "answers": [
    {"question_contains": "evaporat", "answer": "Heat from the sun turns liquid water into vapour that rises.", "expected_grade": "correct"},
    {"question_contains": "evaporat", "answer": "Rain falls from clouds into the sea.", "expected_grade": "incorrect"},
    {"question_contains": "", "answer": "I like football", "expected_route": "check", "expected_grade": "off_topic"},
    {"question_contains": "", "answer": "", "expected_grade": "junk"}
  ]
}
```

Write realistic answers for each fixture in its own language; `question_contains` is a case-insensitive substring used to pick a question from the generated bank (empty means any free-text question).

- [ ] **Step 2: Write the failing test**

```python
from __future__ import annotations

from teachme.container import Container
from teachme.eval.runner import EvalRunner
from teachme.settings import Settings


def test_eval_runner_reports_metrics_with_fake_stack(db, migrated_database, tmp_path):
    settings = Settings(_env_file=None, database_url=migrated_database, llm_provider="fake", embeddings_provider="fake",
                        reranker_provider="noop", file_store="local", local_files_dir=tmp_path / "f", digest_dir=tmp_path / "d")
    c = Container(settings)
    report = EvalRunner(c).run(languages=["en"])
    assert report.fixtures[0].language == "en"
    assert report.fixtures[0].outline_ok in (True, False)
    assert 0.0 <= report.fixtures[0].grading_agreement <= 1.0
    assert report.fixtures[0].cost_usd >= 0.0
    text = report.render()
    assert "grading agreement" in text and "outline" in text
    c.close()
```

- [ ] **Step 3: Write `eval/runner.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from teachme.container import Container
from teachme.domain.models import QuestionKind

FIXTURES = Path(__file__).parent / "fixtures"


class ExpectedAnswer(BaseModel):
    question_contains: str
    answer: str
    expected_grade: str
    expected_route: str | None = None


class OutlineBounds(BaseModel):
    min_parts: int
    max_parts: int
    min_sections: int


class Fixture(BaseModel):
    language: str
    teach_in: list[str]
    outline: OutlineBounds
    answers: list[ExpectedAnswer]


class FixtureReport(BaseModel):
    language: str
    outline_ok: bool
    parts: int
    grading_agreement: float
    route_agreement: float
    relevance_false_rejects: int
    cost_usd: float
    details: list[str]


class EvalReport(BaseModel):
    fixtures: list[FixtureReport]

    def render(self) -> str:
        lines = []
        for f in self.fixtures:
            lines.append(f"[{f.language}] outline ok: {f.outline_ok} ({f.parts} parts); grading agreement: {f.grading_agreement:.0%};"
                         f" route agreement: {f.route_agreement:.0%}; false rejects: {f.relevance_false_rejects}; cost ${f.cost_usd:.4f}")
            lines += [f"    {d}" for d in f.details]
        return "\n".join(lines)


class EvalRunner:
    """Ingest a fixture source, generate, publish, then answer questions as a synthetic student and
    compare grades and routes with the fixture's expectations. Model choice is whatever settings say,
    so re-running after a settings change yields a comparison."""

    def __init__(self, container: Container) -> None:
        self.c = container

    def run(self, languages: list[str] | None = None) -> EvalReport:
        reports = []
        for folder in sorted(FIXTURES.iterdir()):
            fixture = Fixture.model_validate_json((folder / "expected.json").read_text(encoding="utf-8"))
            if languages and fixture.language not in languages:
                continue
            reports.append(self._run_fixture(folder, fixture))
        return EvalReport(fixtures=reports)

    def _run_fixture(self, folder: Path, fixture: Fixture) -> FixtureReport:
        c = self.c
        name = f"eval-{fixture.language}-{uuid4().hex[:6]}"
        subject = c.subject_service.get_or_create(name, fixture.teach_in)
        source = c.source_service.register(subject, "source.md", (folder / "source.md").read_bytes())
        c.pipeline.ingest_source(source.id)
        c.tutorial_service.generate(subject)
        subject = c.tutorial_service.publish(subject)
        outline = c.outlines.latest(subject.id)
        parts = c.outlines.parts(outline.id)
        outline_ok = fixture.outline.min_parts <= len(parts) <= fixture.outline.max_parts and all(
            len(c.outlines.sections(p.id)) >= fixture.outline.min_sections for p in parts
        )
        details: list[str] = []
        agree = routes_agree = routes_total = 0
        false_rejects = 0
        user = f"eval-user-{uuid4().hex[:6]}"
        language = fixture.teach_in[0]
        session = c.learning_service.start_part(user, subject, 0, language)
        bank = [q for q in c.questions.for_part(parts[0].id, language) if q.kind == QuestionKind.FREE_TEXT]
        for expected in fixture.answers:
            question = next((q for q in bank if expected.question_contains.lower() in q.prompt.lower()), bank[0])
            c.learning_service.begin_round(user, session.attempt_id) if c.attempts.next_unanswered(session.attempt_id) is None else None
            current = c.attempts.next_unanswered(session.attempt_id)
            # answer whatever question is current; the fixture's substring only steers which answer text we use
            result = c.learning_service.submit_answer(user, session.attempt_id, current.id, answer_text=expected.answer)
            recorded = c.attempts.get_question(current.id)
            grade = (result.grade.value if result.grade else "rejected")
            ok = grade == expected.expected_grade or (expected.expected_grade in ("junk", "off_topic") and not result.accepted)
            agree += int(ok)
            if expected.expected_route:
                routes_total += 1
                routes_agree += int(recorded.route is not None and recorded.route.value == expected.expected_route)
            if expected.expected_grade in ("correct", "partial", "incorrect") and not result.accepted:
                false_rejects += 1
            details.append(f"{expected.expected_grade:>9} -> {grade:<9} route={recorded.route.value if recorded.route else '-'} | {expected.answer[:50]}")
        usage = c.usage_repo.summarize(subject_id=subject.id)
        cost = float(sum(float(r["cost_usd"]) for r in usage))
        return FixtureReport(language=fixture.language, outline_ok=outline_ok, parts=len(parts),
                             grading_agreement=agree / max(len(fixture.answers), 1),
                             route_agreement=(routes_agree / routes_total) if routes_total else 1.0,
                             relevance_false_rejects=false_rejects, cost_usd=cost, details=details)
```

Note: with the fake stack the report exercises the plumbing; real numbers need `LLM_PROVIDER=anthropic`. Because `submit_answer` requires the current question to be open, the loop keeps answering the current question of the round rather than the matched one; the fixture's `question_contains` is informational. This is acceptable for a harness whose purpose is comparing models under identical inputs.

- [ ] **Step 4: Add the CLI command**

```python
@app.command()
def eval(language: list[str] = typer.Option(None, "--language", "-l")) -> None:
    """Run the fixture-based evaluation with the configured providers and print the report."""
    from teachme.eval.runner import EvalRunner

    c = build_container()
    c.check_ready()
    report = EvalRunner(c).run(languages=language or None)
    typer.echo(report.render())
    c.close()
```

- [ ] **Step 5: Run the test, then commit**

```bash
git add api/teachme/eval api/teachme/cli/main.py api/tests/eval
git commit -m "feat: eval harness with per-language fixtures"
```

---

## Phase B: Frontend foundation

### Task 4: Dependencies, dev rewrite, types, i18n, API client

**Files:**
- Modify: `package.json`, `next.config.ts`
- Create: `lib/api/types.ts`, `lib/i18n.ts`, `lib/language.ts`, `lib/api/client.ts`, `lib/api/subjects.ts`, `lib/api/learning.ts`, `lib/api/admin.ts`, `vitest.config.ts`, `lib/__tests__/i18n.test.ts`, `lib/__tests__/client.test.ts`

- [ ] **Step 1: Install dependencies**

```bash
source ~/.nvm/nvm.sh && nvm use 22
npm install @clerk/nextjs react-markdown remark-gfm @microsoft/fetch-event-source
npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test
```

Add scripts to `package.json`: `"test": "vitest run"`, `"test:watch": "vitest"`, `"e2e": "playwright test"`.

- [ ] **Step 2: `next.config.ts`** (dev rewrite only; verify the rewrites API name in `node_modules/next/dist/docs`)

```ts
import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (process.env.VERCEL) return [];
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
```

- [ ] **Step 3: `lib/api/types.ts`** (mirror the backend pydantic models exactly)

```ts
export type Language = "he" | "en" | "pt";
export type PartStatus = "not_started" | "learning" | "quizzing" | "reinforcing" | "passed" | "stalled";
export type Grade = "correct" | "partial" | "incorrect" | "off_topic" | "junk";
export type QuestionKind = "free_text" | "multiple_choice";

export interface SubjectSummary { id: string; name: string; languages: Language[]; parts_total: number; parts_passed: number; }
export interface PartView { part_id: string; position: number; title: string; status: PartStatus; locked: boolean; best_score: number | null; rounds_used: number; }
export interface SubjectView { subject_id: string; name: string; languages: Language[]; parts: PartView[]; }
export interface SectionContent { section_id: string; language: string; title: string; summary: string; }
export interface GlossaryEntry { slug: string; term: string; source_term: string; definition: string; }
export interface RenderedPart { position: number; title: string; body: string; key_points: string[]; sections: SectionContent[]; glossary: GlossaryEntry[]; }
export interface QuestionView { attempt_question_id: string; question_id: string; position: number; round_no: number; total_in_round: number; kind: QuestionKind; prompt: string; choices: string[] | null; }
export interface RoundResult { round_no: number; score: number; passed: boolean; status: PartStatus; rounds_left: number; weak_section_titles: string[]; }
export interface AnswerResult { accepted: boolean; grade: Grade | null; feedback: string; rejection_reason: string | null; next_question: QuestionView | null; round_result: RoundResult | null; }
export interface PartSession { part: RenderedPart; status: PartStatus; attempt_id: string | null; round_no: number; current_question: QuestionView | null; last_round: RoundResult | null; reexplanation: string | null; }
export interface StudentSource { filename: string; media_type: string; page_count: number | null; }
export interface AdminSubject { id: string; name: string; state: string; languages: Language[]; current_outline_version: number | null; }
export interface AdminSource { id: string; filename: string; media_type: string; status: string; page_count: number | null; detected_language: string | null; error: string | null; }
export interface UsageRow { purpose: string; model: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_write_tokens: number; cost_usd: number; avg_latency_ms: number; }
```

- [ ] **Step 4: `lib/i18n.ts`** and its test

```ts
import type { Language } from "./api/types";

export const LANGUAGES: { code: Language; name: string; dir: "ltr" | "rtl" }[] = [
  { code: "he", name: "עברית", dir: "rtl" },
  { code: "en", name: "English", dir: "ltr" },
  { code: "pt", name: "Português", dir: "ltr" },
];

export function directionOf(code: Language): "ltr" | "rtl" {
  return LANGUAGES.find((l) => l.code === code)?.dir ?? "ltr";
}

const STRINGS = {
  en: {
    appName: "teach-me", signIn: "Sign in", subjects: "Your subjects", noSubjects: "No published subjects yet.",
    partOf: (n: number, total: number) => `Part ${n} of ${total}`, sources: "Sources", teaching: "Teaching",
    dialog: "Dialog", startRound: "Start the questions", nextRound: "Start the next round", continue: "Continue",
    submit: "Submit answer", answerPlaceholder: "Write your answer…", passed: "Part passed", failed: "Not yet",
    score: (pct: number) => `Score: ${pct}%`, roundsLeft: (n: number) => `${n} rounds left`, stalled: "Let's start this part again",
    retry: "Start again", locked: "Locked", weakSections: "We will go over:", reexplaining: "Explaining this differently…",
    keyPoints: "Key points", figurePage: (p: number) => `Page ${p}`, language: "Language", admin: "Admin",
    questionOf: (i: number, total: number) => `Question ${i} of ${total}`, chooseOne: "Choose one",
    status: { not_started: "Not started", learning: "Reading", quizzing: "Answering", reinforcing: "Reviewing", passed: "Passed", stalled: "Stalled" } as Record<string, string>,
  },
  he: {
    appName: "teach-me", signIn: "כניסה", subjects: "המקצועות שלך", noSubjects: "אין עדיין מקצועות זמינים.",
    partOf: (n: number, total: number) => `חלק ${n} מתוך ${total}`, sources: "מקורות", teaching: "הוראה",
    dialog: "שיחה", startRound: "התחלת השאלות", nextRound: "התחלת הסבב הבא", continue: "המשך",
    submit: "שליחת תשובה", answerPlaceholder: "כתבו את תשובתכם…", passed: "החלק הושלם", failed: "עוד לא",
    score: (pct: number) => `ציון: ${pct}%`, roundsLeft: (n: number) => `נותרו ${n} סבבים`, stalled: "נתחיל את החלק מחדש",
    retry: "התחלה מחדש", locked: "נעול", weakSections: "נחזור על:", reexplaining: "מסבירים את זה בדרך אחרת…",
    keyPoints: "נקודות מפתח", figurePage: (p: number) => `עמוד ${p}`, language: "שפה", admin: "ניהול",
    questionOf: (i: number, total: number) => `שאלה ${i} מתוך ${total}`, chooseOne: "בחרו תשובה אחת",
    status: { not_started: "טרם התחיל", learning: "קריאה", quizzing: "מענה", reinforcing: "חזרה", passed: "הושלם", stalled: "נעצר" } as Record<string, string>,
  },
  pt: {
    appName: "teach-me", signIn: "Entrar", subjects: "As suas matérias", noSubjects: "Ainda não há matérias publicadas.",
    partOf: (n: number, total: number) => `Parte ${n} de ${total}`, sources: "Fontes", teaching: "Ensino",
    dialog: "Diálogo", startRound: "Começar as perguntas", nextRound: "Começar a próxima ronda", continue: "Continuar",
    submit: "Enviar resposta", answerPlaceholder: "Escreva a sua resposta…", passed: "Parte concluída", failed: "Ainda não",
    score: (pct: number) => `Pontuação: ${pct}%`, roundsLeft: (n: number) => `${n} rondas restantes`, stalled: "Vamos recomeçar esta parte",
    retry: "Recomeçar", locked: "Bloqueado", weakSections: "Vamos rever:", reexplaining: "A explicar de outra forma…",
    keyPoints: "Pontos-chave", figurePage: (p: number) => `Página ${p}`, language: "Idioma", admin: "Administração",
    questionOf: (i: number, total: number) => `Pergunta ${i} de ${total}`, chooseOne: "Escolha uma",
    status: { not_started: "Não iniciado", learning: "A ler", quizzing: "A responder", reinforcing: "A rever", passed: "Concluído", stalled: "Parado" } as Record<string, string>,
  },
};

export type Strings = (typeof STRINGS)["en"];

export function t(code: Language): Strings {
  return STRINGS[code] ?? STRINGS.en;
}
```

`lib/__tests__/i18n.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { LANGUAGES, directionOf, t } from "../i18n";

describe("i18n", () => {
  it("has the same keys for every language", () => {
    const keys = Object.keys(t("en")).sort();
    for (const { code } of LANGUAGES) expect(Object.keys(t(code)).sort()).toEqual(keys);
  });
  it("hebrew is rtl", () => {
    expect(directionOf("he")).toBe("rtl");
    expect(directionOf("pt")).toBe("ltr");
  });
});
```

- [ ] **Step 5: `lib/language.ts`** (cookie so the server layout can set `dir`, localStorage as a fallback)

```ts
import type { Language } from "./api/types";

export const LANGUAGE_COOKIE = "teachme_lang";

export function readLanguage(): Language {
  if (typeof document === "undefined") return "en";
  const match = document.cookie.match(new RegExp(`${LANGUAGE_COOKIE}=(he|en|pt)`));
  if (match) return match[1] as Language;
  try {
    const stored = window.localStorage.getItem(LANGUAGE_COOKIE);
    if (stored === "he" || stored === "en" || stored === "pt") return stored;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function writeLanguage(code: Language): void {
  document.cookie = `${LANGUAGE_COOKIE}=${code}; path=/; max-age=31536000; samesite=lax`;
  try {
    window.localStorage.setItem(LANGUAGE_COOKIE, code);
  } catch {
    /* storage unavailable */
  }
}
```

- [ ] **Step 6: `lib/api/client.ts`** and its test

```ts
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export type TokenGetter = () => Promise<string | null>;

export async function apiFetch<T>(path: string, getToken: TokenGetter, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}
```

`lib/__tests__/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";

describe("apiFetch", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds the bearer token and parses json", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    const out = await apiFetch<{ ok: number }>("/api/x", async () => "tok", { method: "POST", body: "{}" });
    expect(out.ok).toBe(1);
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("throws ApiError with the backend detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "not your attempt" }), { status: 403 }));
    await expect(apiFetch("/api/x", async () => null)).rejects.toMatchObject<Partial<ApiError>>({ status: 403, detail: "not your attempt" });
  });
});
```

- [ ] **Step 7: Typed API modules**

`lib/api/subjects.ts`:

```ts
import { apiFetch, type TokenGetter } from "./client";
import type { StudentSource, SubjectSummary, SubjectView } from "./types";

export const listSubjects = (getToken: TokenGetter) => apiFetch<SubjectSummary[]>("/api/subjects", getToken);
export const openSubject = (id: string, getToken: TokenGetter) => apiFetch<SubjectView>(`/api/subjects/${id}`, getToken);
export const listSources = (id: string, getToken: TokenGetter) => apiFetch<StudentSource[]>(`/api/subjects/${id}/sources`, getToken);
export const pageImageUrl = (subjectId: string, globalIndex: number) => `/api/subjects/${subjectId}/pages/${globalIndex}/image`;
```

`lib/api/learning.ts`:

```ts
import { apiFetch, type TokenGetter } from "./client";
import type { AnswerResult, Language, PartSession, QuestionView } from "./types";

export const startPart = (subjectId: string, position: number, language: Language, getToken: TokenGetter) =>
  apiFetch<PartSession>(`/api/subjects/${subjectId}/parts/${position}/start`, getToken, { method: "POST", body: JSON.stringify({ language }) });

export const beginRound = (attemptId: string, getToken: TokenGetter) =>
  apiFetch<QuestionView>(`/api/attempts/${attemptId}/round`, getToken, { method: "POST" });

export const submitAnswer = (
  attemptId: string, attemptQuestionId: string, answer: { answer_text?: string; answer_choice?: number }, getToken: TokenGetter,
) => apiFetch<AnswerResult>(`/api/attempts/${attemptId}/answer`, getToken, {
  method: "POST", body: JSON.stringify({ attempt_question_id: attemptQuestionId, ...answer }),
});

export const reexplainUrl = (attemptId: string) => `/api/attempts/${attemptId}/reexplain`;
```

`lib/api/admin.ts`:

```ts
import { apiFetch, type TokenGetter } from "./client";
import type { AdminSource, AdminSubject, UsageRow } from "./types";

export const adminSubjects = (getToken: TokenGetter) => apiFetch<AdminSubject[]>("/api/admin/subjects", getToken);
export const adminSources = (id: string, getToken: TokenGetter) => apiFetch<AdminSource[]>(`/api/admin/subjects/${id}/sources`, getToken);
export const adminUsage = (subjectId: string | null, getToken: TokenGetter) =>
  apiFetch<UsageRow[]>(`/api/admin/usage${subjectId ? `?subject_id=${subjectId}` : ""}`, getToken);
```

- [ ] **Step 8: `vitest.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true, setupFiles: ["./vitest.setup.ts"], include: ["**/__tests__/**/*.test.{ts,tsx}"] },
  resolve: { alias: { "@": new URL("./", import.meta.url).pathname } },
});
```

`vitest.setup.ts`: `import "@testing-library/jest-dom/vitest";`

- [ ] **Step 9: Run and commit**

Run: `npm run test && npm run lint`
Expected: 4 tests pass, lint clean.

```bash
git add package.json package-lock.json next.config.ts lib vitest.config.ts vitest.setup.ts
git commit -m "feat(web): api client, types, i18n, dev rewrite, vitest"
```

---

### Task 5: App shell with Clerk, language, landing page

**Files:**
- Create: `app/layout.tsx` (replace scaffold), `app/page.tsx` (replace scaffold), `proxy.ts` or `middleware.ts` (per Next docs), `components/LanguagePicker.tsx`, `hooks/useSubjects.ts`, `components/__tests__/LanguagePicker.test.tsx`
- Modify: `app/globals.css` (keep Tailwind import; add `[dir="rtl"]` helpers if needed), `.env.local` (Clerk keys copied from the old project; never committed)

- [ ] **Step 1: Clerk wiring.** Following the installed Clerk quickstart: wrap the root layout in `<ClerkProvider>`; create the route-protection file the docs prescribe for this Next version (`clerkMiddleware()` with a matcher protecting `/learn(.*)` and `/admin(.*)`, leaving `/` and `/api` public since the Python backend verifies its own JWTs). Environment: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` in `.env.local`.

- [ ] **Step 2: `app/layout.tsx`** reads the language cookie on the server to set `lang` and `dir`:

```tsx
import { ClerkProvider } from "@clerk/nextjs";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import "./globals.css";
import { directionOf } from "@/lib/i18n";
import { LANGUAGE_COOKIE } from "@/lib/language";
import type { Language } from "@/lib/api/types";

export const metadata = { title: "teach-me" };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const store = await cookies();
  const raw = store.get(LANGUAGE_COOKIE)?.value;
  const language: Language = raw === "he" || raw === "pt" ? raw : "en";
  return (
    <ClerkProvider>
      <html lang={language} dir={directionOf(language)}>
        <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
```

(Verify `cookies()` is async in this Next version; adjust if the docs say otherwise.)

- [ ] **Step 3: `components/LanguagePicker.tsx`** (plain props, no fetching)

```tsx
"use client";
import { LANGUAGES } from "@/lib/i18n";
import type { Language } from "@/lib/api/types";

export function LanguagePicker({ value, options, onChange, label }: {
  value: Language; options: Language[]; onChange: (code: Language) => void; label: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span>{label}</span>
      <select className="rounded border px-2 py-1" value={value} onChange={(e) => onChange(e.target.value as Language)} aria-label={label}>
        {LANGUAGES.filter((l) => options.includes(l.code)).map((l) => (
          <option key={l.code} value={l.code}>{l.name}</option>
        ))}
      </select>
    </label>
  );
}
```

Test `components/__tests__/LanguagePicker.test.tsx`: renders only the offered options, calls `onChange` with the chosen code.

- [ ] **Step 4: `hooks/useSubjects.ts`**

```ts
"use client";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { listSubjects } from "@/lib/api/subjects";
import type { SubjectSummary } from "@/lib/api/types";

export function useSubjects() {
  const { getToken, isSignedIn } = useAuth();
  const [subjects, setSubjects] = useState<SubjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!isSignedIn) return;
    listSubjects(getToken).then(setSubjects).catch((e) => setError(String(e.message ?? e)));
  }, [isSignedIn, getToken]);
  return { subjects, error };
}
```

- [ ] **Step 5: `app/page.tsx`**: signed-out shows the app name and a Clerk `<SignInButton mode="modal">`; signed-in shows `<UserButton />`, the `LanguagePicker` (options: all three; writes the cookie and reloads so the layout direction updates), the subject list as cards linking to `/learn/{id}` with a `parts_passed/parts_total` bar, an "Admin" link (the page itself enforces the role server-side; the link is harmless for students), and the `noSubjects` message when empty. Use `t(language)` for every string.

- [ ] **Step 6: Run and commit**

Run: `npm run test && npm run lint && npm run build`
Expected: pass. Then start `npm run dev` with the backend running and confirm sign-in and the subject list render (manual check, describe what you saw in the report).

```bash
git add app proxy.ts middleware.ts components hooks 2>/dev/null; git add -A app components hooks lib
git commit -m "feat(web): clerk shell, language picker, subject landing page"
```

---

## Phase C: Learn screen

### Task 6: Teaching side: SubjectTabs, PartProgress, TeachingPane, FigureThumbnail, SourceList

**Files:**
- Create: `components/SubjectTabs.tsx`, `components/PartProgress.tsx`, `components/TeachingPane.tsx`, `components/FigureThumbnail.tsx`, `components/SourceList.tsx`, tests for `PartProgress` and `TeachingPane`

- [ ] **Step 1: Write the failing component tests**

`components/__tests__/PartProgress.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PartProgress } from "../PartProgress";
import { t } from "@/lib/i18n";

const parts = [
  { part_id: "a", position: 0, title: "A", status: "passed", locked: false, best_score: 80, rounds_used: 1 },
  { part_id: "b", position: 1, title: "B", status: "reinforcing", locked: false, best_score: 20, rounds_used: 1 },
  { part_id: "c", position: 2, title: "C", status: "not_started", locked: true, best_score: null, rounds_used: 0 },
] as const;

describe("PartProgress", () => {
  it("renders one step per part with status labels and locks", () => {
    render(<PartProgress parts={[...parts]} current={1} strings={t("en")} onSelect={() => {}} />);
    expect(screen.getByText("Part 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /A/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /C/ })).toBeDisabled();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Reviewing")).toBeInTheDocument();
  });
});
```

`components/__tests__/TeachingPane.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TeachingPane } from "../TeachingPane";
import { t } from "@/lib/i18n";

describe("TeachingPane", () => {
  it("renders markdown and turns page references into thumbnails", () => {
    render(<TeachingPane title="Intro" body={"# Heading\n\nLook at page 12.\n\n- a"} keyPoints={["k1"]} pageRefs={[12]}
                         subjectId="s1" strings={t("en")} reexplanation={null} />);
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByText("k1")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Page 12" })).toHaveAttribute("src", "/api/subjects/s1/pages/12/image");
  });
  it("shows the reexplanation above the teaching text when present", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} pageRefs={[]} subjectId="s1" strings={t("en")} reexplanation="## Again" />);
    expect(screen.getByRole("heading", { name: "Again" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail** (`npm run test` reports missing modules).

- [ ] **Step 3: Implement the components**

`SubjectTabs.tsx`: props `{ subjects: SubjectSummary[]; activeId: string }`; renders a horizontal tab list of `next/link` links to `/learn/{id}`, the active one highlighted, with `aria-current="page"`.

`PartProgress.tsx`: props `{ parts: PartView[]; current: number; strings: Strings; onSelect: (position: number) => void }`; renders `strings.partOf(current + 1, parts.length)` and one `<button>` per part showing its title and `strings.status[status]`, disabled when `locked`, visually distinct for passed / current / locked. Buttons call `onSelect(position)`.

`FigureThumbnail.tsx`: props `{ subjectId: string; pageIndex: number; label: string }`; renders `<img>` with `src={pageImageUrl(subjectId, pageIndex)}`, `alt={label}`, lazy loading, a fixed max width, and a click handler that opens the image URL in a new tab.

`TeachingPane.tsx`: props `{ title; body; keyPoints; pageRefs: number[]; subjectId; strings; reexplanation: string | null }`. Renders the re-explanation (if any) in a highlighted box using `react-markdown` with `remark-gfm`, then the title, the body via `react-markdown` + `remark-gfm`, a "Key points" list, and one `FigureThumbnail` per entry in `pageRefs` (label `strings.figurePage(page)`) in a horizontal strip after the body. Page references come from the backend later; for now the page derives `pageRefs` by scanning the body for the pattern `page (\d+)` in English, `עמוד (\d+)` in Hebrew and `página (\d+)` in Portuguese (helper `extractPageRefs(body: string): number[]` in `lib/pageRefs.ts`, unit tested with one example per language). Student text is never passed to this component.

`SourceList.tsx`: props `{ sources: StudentSource[]; strings: Strings }`; a titled list of filenames with page counts, read-only.

- [ ] **Step 4: Run and commit**

```bash
npm run test && npm run lint
git add components lib
git commit -m "feat(web): teaching pane, part progress, figure thumbnails, source list"
```

---

### Task 7: Dialog side: QuestionCard, FeedbackCard, RoundResult, DialogPane, hooks, learn page

**Files:**
- Create: `components/QuestionCard.tsx`, `components/FeedbackCard.tsx`, `components/RoundResult.tsx`, `components/DialogPane.tsx`, `hooks/useLearningSession.ts`, `hooks/useReexplainStream.ts`, `app/learn/[subjectId]/page.tsx`, tests for `QuestionCard` and `DialogPane`

- [ ] **Step 1: Write the failing tests**

`components/__tests__/QuestionCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QuestionCard } from "../QuestionCard";
import { t } from "@/lib/i18n";

const base = { attempt_question_id: "aq", question_id: "q", position: 1, round_no: 1, total_in_round: 5 };

describe("QuestionCard", () => {
  it("free text: submits trimmed text and disables while busy", async () => {
    const onSubmit = vi.fn();
    render(<QuestionCard question={{ ...base, kind: "free_text", prompt: "Why?", choices: null }} busy={false} strings={t("en")} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByRole("textbox"), "  because  ");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(onSubmit).toHaveBeenCalledWith({ answer_text: "because" });
  });
  it("multiple choice: submits the chosen index and renders prompt as plain text", async () => {
    const onSubmit = vi.fn();
    render(<QuestionCard question={{ ...base, kind: "multiple_choice", prompt: "<b>Pick</b>", choices: ["a", "b"] }} busy={false} strings={t("en")} onSubmit={onSubmit} />);
    expect(screen.getByText("<b>Pick</b>")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "b" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(onSubmit).toHaveBeenCalledWith({ answer_choice: 1 });
  });
});
```

`components/__tests__/DialogPane.test.tsx`: renders the "Start the questions" button in `learning` status, a `QuestionCard` when a question is present, a `FeedbackCard` after an answer, a `RoundResult` with the passed/failed label and `weak_section_titles`, and the "Start again" button when stalled. Use `t("en")` and assert the visible labels.

- [ ] **Step 2: Implement**

`QuestionCard.tsx`: props `{ question: QuestionView; busy: boolean; strings: Strings; onSubmit: (answer: { answer_text?: string; answer_choice?: number }) => void }`. Shows `strings.questionOf(position + 1, total_in_round)`, the prompt in a `<p>` (text node, never `dangerouslySetInnerHTML`), a `<textarea>` for free text with `strings.answerPlaceholder` and a max length of 1500, or radio buttons for choices, and a submit button disabled when `busy` or when the answer is empty. Clears the textarea after submit.

`FeedbackCard.tsx`: props `{ result: AnswerResult; strings: Strings }`. Shows the grade as a coloured label (correct green, partial amber, incorrect red, rejections grey) and the feedback text as plain text; for a rejection shows the fixed backend message only.

`RoundResult.tsx`: props `{ result: RoundResult; strings: Strings; onContinue: () => void }`. Shows `strings.passed` or `strings.failed`, `strings.score(Math.round(score * 100))`, `strings.roundsLeft(rounds_left)` when not passed and not stalled, the weak section titles under `strings.weakSections`, and a button: `strings.continue` (passed), `strings.nextRound` (reinforcing, enabled only after the re-explanation stream finished, passed in as `canContinue`), or `strings.retry` (stalled).

`DialogPane.tsx`: props `{ session: PartSession; question: QuestionView | null; lastAnswer: AnswerResult | null; roundResult: RoundResult | null; busy: boolean; streaming: boolean; strings: Strings; onStartRound; onSubmit; onContinue }`. Chooses what to render from the props: start button, question card, feedback card, round result, or stalled retry. No fetching.

`hooks/useLearningSession.ts`: owns the flow for one part: state `{ session, question, lastAnswer, roundResult, busy, error }`, actions `open(position)`, `startRound()`, `submit(answer)`, `continueAfterRound()` (passed: re-open subject and move to the next unlocked part; reinforcing: start next round; stalled: re-open the part which creates a fresh attempt). Every action calls the API through `lib/api/learning.ts` with `getToken` from Clerk and stores the response; after a round result it refetches the subject view so the progress strip updates.

`hooks/useReexplainStream.ts`: given `attemptId` and `enabled`, uses `fetchEventSource(reexplainUrl(attemptId), { headers: { Authorization } , onmessage })`; appends `delta` payloads to `text`, and on `done` replaces `text` with the rendered payload and sets `finished`. Aborts on unmount.

`app/learn/[subjectId]/page.tsx` (client component): reads the subject id from params, the language from `readLanguage()` narrowed to the subject's languages, loads the subject view and sources, renders the layout from the spec: header row with `SubjectTabs` and `PartProgress`, main column with `TeachingPane` (top) and `DialogPane` (bottom), right column with `SourceList`, stacking on narrow screens (`grid grid-cols-1 lg:grid-cols-[1fr_280px]`). The re-explanation stream starts when the round result status is `reinforcing`, its text feeds `TeachingPane.reexplanation`, and `RoundResult.canContinue` becomes true when it finishes.

- [ ] **Step 3: Run tests, lint, build; manual check against the running fake backend**: open a subject, read part 1, start the questions, answer, see feedback, finish a round, see the result and the progress strip update. Describe what you saw.

```bash
git add components hooks app lib
git commit -m "feat(web): dialog pane, learning session hook, re-explanation stream, learn screen"
```

---

## Phase D: Admin, tests, deployment

### Task 8: Admin page

**Files:**
- Create: `app/admin/page.tsx`, `hooks/useAdmin.ts`, `components/UsageTable.tsx`, `components/__tests__/UsageTable.test.tsx`

- [ ] **Step 1: Test**: `UsageTable` renders one row per usage row with formatted cost (`$0.0123`) and a total row.

- [ ] **Step 2: Implement**: `useAdmin` loads `adminSubjects`, and for a selected subject `adminSources` and `adminUsage`. The page shows the subject list with state and version, the selected subject's sources with status and errors, and the `UsageTable`. A 403 from the backend renders a plain "admin role required" message. No upload control (stage 5, optional).

```bash
git add app/admin hooks components
git commit -m "feat(web): read-only admin page"
```

---

### Task 9: End-to-end test against the fake backend

**Files:**
- Create: `playwright.config.ts`, `e2e/learn.spec.ts`, `e2e/auth.setup.ts` (or Clerk testing token approach), `scripts/e2e-backend.sh`

- [ ] **Step 1: Backend for e2e.** `scripts/e2e-backend.sh` starts the API with the fake stack against the local test database, seeds one subject (ingest, generate, publish with the fake providers) and exports its id to `e2e/.subject-id`. Since the frontend uses Clerk, follow Clerk's testing guidance (`@clerk/testing` with `clerkSetup` and a test user) for sign-in in Playwright; if that cannot be configured in this environment, mark the spec `test.skip` with a message and report it as a concern rather than faking auth in production code.

- [ ] **Step 2: `e2e/learn.spec.ts`**: sign in, open the seeded subject, read part 1, start the questions, answer every question of the round (fill textarea or pick a radio), assert the round result appears and the progress strip shows part 1 passed (the fake grader returns correct).

- [ ] **Step 3: Run `npm run e2e`**, commit.

```bash
git add playwright.config.ts e2e scripts
git commit -m "test(web): playwright happy path"
```

---

### Task 10: Remove the scaffold leftovers, docs, verification, merge

- [ ] **Step 1: Remove scaffold-only files** that the new pages replaced (default `app/page.tsx` content, scaffold images in `public/` that are unused). Confirm `grep -rniE "insurellm|ideagen|\bsaas\b" --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git --exclude-dir=docs .` returns nothing.

- [ ] **Step 2: README**: add "Running the app locally" (backend + frontend commands, fake stack env), the Clerk setup notes (publishable/secret keys, JWKS URL for the backend, session-token role claim), and the route map.

- [ ] **Step 3: Verify everything**: `npm run lint && npm run test && npm run build`, `ruff check api && pytest -q` (backend), `npm run e2e` if configured.

- [ ] **Step 4: Merge**

```bash
git add -A && git commit -m "docs: stage 4 run instructions"
git checkout main && git merge --ff-only stage-4-frontend && git push origin main
```

---

### Task 11: Vercel deployment of stages 1 to 4 (operational)

- [ ] Rename the Vercel project to `teach-me` and `vercel link` (dashboard step; report if not possible from the CLI).
- [ ] Provision Marketplace Postgres and Vercel Blob through the `vercel:marketplace` skill; set `DATABASE_URL`, `BLOB_READ_WRITE_TOKEN`, `FILE_STORE=vercel_blob`, `LLM_PROVIDER=anthropic`, `EMBEDDINGS_PROVIDER=voyage`, `RERANKER_PROVIDER=voyage`, `ANTHROPIC_API_KEY` (service-account key with expiry), `VOYAGE_API_KEY`, `CLERK_JWKS_URL`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` with `vercel env add`; `vercel env pull .env.local`.
- [ ] `teachme migrate` against the hosted database; ingest, generate and publish one real short PDF from the CLI (read the printed estimate first).
- [ ] `vercel` (preview) then `vercel --prod`; open the deployment, sign in, run one part end to end; check `teachme usage` afterwards and record the per-student cost of that run in the plan under `## Pilot cost`.
- [ ] Federation (spec section 9) is the follow-up before real students arrive; it is not part of this plan.

---

## Self-review against the spec

- Section 8: routes `/`, `/learn/[subjectId]`, `/admin` (Tasks 5, 7, 8); layout with tabs, progress strip, teaching over dialog, right source pane, stacking on narrow screens (Task 7); components one per file with plain props (Tasks 6, 7, 8); hooks per concern with Clerk token and SSE (Tasks 4, 7); language choice remembered and RTL at the root (Tasks 4, 5); UI strings from one translations file (Task 4); thumbnails on page references (Tasks 1, 6); one question at a time, feedback, rejections reopen the box, failed round streams the re-explanation, passed round unlocks (Task 7); student text rendered as plain text (Task 7); no free chat, no client-side scoring, no persistence beyond language (all).
- Section 9 eval harness: Task 3.
- Deferred: admin upload pane (stage 5, optional), federation (before students).
