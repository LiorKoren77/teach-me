# Stage 2: Tutorial Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a subject's ingested sources, generate and cache one outline (parts and sections), a glossary with per-language translations, teaching text per part and language with glossary placeholders, and a question bank per part and language; validate everything in code; version outlines; publish and unpublish subjects; all from the `teachme` CLI.

**Architecture:** Same ports-and-adapters layout as stage 1. New `generation/` package with one module per LLM output type and one prompt file each, a `validate.py` that re-runs a call once with the validation errors appended, a `corpus.py` that renders the subject's full page text as a cached prompt prefix, a pure `domain/glossary/render.py` that resolves `{{term:slug|words}}` placeholders, four new repositories, a `TutorialService` orchestrating generation and publishing, and CLI commands. The LLM port gains an optional `cached_context` so the corpus is a stable cached prefix across every generation call.

**Tech Stack:** As stage 1. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-17-teach-me-design.md` sections 4 (tutorial structure and content tables), 6 (generation) and the glossary addition.

**Prerequisite:** Stage 1 complete (`docs/superpowers/plans/2026-09-17-stage1-ingestion.md`), so `teachme ingest` produces ready sources with pages in `source_pages`.

---

## Conventions

Same as stage 1: work in `/home/frtlx/liorkoren77/teach-me`, `source .venv/bin/activate`, `pytest -q` (DB tests need `TEST_DATABASE_URL`), commit per task with the given message, pydantic for anything serialized or validated at a boundary, keyword-only construction of pydantic models, no vendor SDK outside `adapters/`.

Stage 1 names used below and their locations:
- `teachme.ports.llm`: `LLMProvider`, `StructuredRequest`, `ContentPart`, `StructuredResult`, `LLMUsage`, `T`
- `teachme.adapters.llm.anthropic.AnthropicLLM`, `teachme.adapters.llm.fake.FakeLLM` (constructor takes `dict[type[BaseModel], Responder]`, records `.calls`)
- `teachme.domain.models`: `Frozen`, `Subject`, `SubjectState`, `Source`, `SourceStatus`, `Page`
- `teachme.repositories.subjects.SubjectRepository`, `.sources.SourceRepository`, `.pages.PageRepository`
- `teachme.ingestion.bundle`: `bundle_slug(name, id)`, `BundleWriter` pattern (stores + slug), `_jsonl` helper shape
- `teachme.ingestion.prompts.load_prompt(name)` reads `ingestion/prompts/<name>.md`; stage 2 adds a parallel `generation/prompts/__init__.py`
- `teachme.container.Container` with `cached_property` members and `check_ready()`
- `teachme.cli.main.app` (typer) with `build_container()`
- `teachme.telemetry.usage.usage_context(subject_id=...)`
- Test fixtures in `api/tests/conftest.py`: `db`, `migrated_database`; `TABLES` list must be extended with the new tables.

## File structure

```
api/teachme/adapters/db/migrations/0002_tutorial.sql
api/teachme/domain/models.py                  + Outline, Part, Section, GlossaryTerm, GlossaryTranslation,
                                                PartContent, SectionContent, Question, QuestionKind, ContentStatus
api/teachme/domain/glossary/__init__.py
api/teachme/domain/glossary/render.py         placeholder parsing and rendering
api/teachme/ports/llm.py                      + StructuredRequest.cached_context
api/teachme/adapters/llm/anthropic.py         two system blocks when cached_context is set
api/teachme/repositories/outlines.py          outlines, parts, sections
api/teachme/repositories/glossary.py          glossary_terms, glossary_translations
api/teachme/repositories/content.py           part_content, section_content
api/teachme/repositories/questions.py         questions
api/teachme/generation/__init__.py
api/teachme/generation/prompts/__init__.py    load_prompt for generation/prompts/*.md
api/teachme/generation/prompts/{outline,outline_merge,glossary,glossary_translate,teaching,questions}.md
api/teachme/generation/corpus.py              SubjectCorpus: pages of all sources rendered once
api/teachme/generation/validate.py            generate_validated(): one retry with errors appended
api/teachme/generation/outline.py
api/teachme/generation/glossary.py
api/teachme/generation/teaching.py
api/teachme/generation/question_bank.py
api/teachme/generation/fake_responders.py     responders for every generation schema
api/teachme/generation/bundle.py              SubjectBundleWriter: outline.json, glossary*.json, parts/, questions.*.jsonl
api/teachme/services/tutorial.py              TutorialService: generate, status, publish, unpublish
api/teachme/container.py                      + repositories, TutorialService
api/teachme/cli/main.py                       + generate, publish, unpublish, tutorial show
api/tests/...                                 one test file per module, named in each task
```

---

### Task 1: Tutorial schema migration and domain models

**Files:**
- Create: `api/teachme/adapters/db/migrations/0002_tutorial.sql`
- Modify: `api/teachme/domain/models.py`, `api/tests/conftest.py`
- Test: `api/tests/domain/test_tutorial_models.py`, `api/tests/adapters/test_migrate.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/adapters/test_migrate.py`:

```python
def test_tutorial_tables_exist(migrated_database):
    conn = connect(migrated_database)
    try:
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        assert {
            "outlines", "parts", "sections", "glossary_terms", "glossary_translations",
            "part_content", "section_content", "questions",
        } <= tables
        assert "0002_tutorial" in applied_versions(conn)
    finally:
        conn.close()
```

Create `api/tests/domain/test_tutorial_models.py`:

```python
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from teachme.domain.models import ContentStatus, Question, QuestionKind, Section


def test_question_multiple_choice_requires_choices_and_correct_index():
    with pytest.raises(ValidationError):
        Question(
            id=uuid4(), section_id=uuid4(), language="he", kind=QuestionKind.MULTIPLE_CHOICE, prompt="?",
            expected_answer="a", rubric=("r",), key_terms=("k",), exact_values=(), choices=None, correct_choice=None,
        )
    ok = Question(
        id=uuid4(), section_id=uuid4(), language="he", kind=QuestionKind.MULTIPLE_CHOICE, prompt="?",
        expected_answer="a", rubric=("r",), key_terms=("k",), exact_values=(), choices=("a", "b"), correct_choice=0,
    )
    assert ok.choices == ("a", "b")


def test_free_text_question_has_no_choices():
    q = Question(
        id=uuid4(), section_id=uuid4(), language="en", kind=QuestionKind.FREE_TEXT, prompt="Why?",
        expected_answer="Because", rubric=("r1", "r2"), key_terms=("why",), exact_values=(),
    )
    assert q.choices is None and q.correct_choice is None


def test_section_page_range_ordering():
    with pytest.raises(ValidationError):
        Section(id=uuid4(), part_id=uuid4(), position=0, page_start=5, page_end=2)


def test_content_status_values():
    assert [s.value for s in ContentStatus] == ["generating", "ready", "failed"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest -q api/tests/domain/test_tutorial_models.py api/tests/adapters/test_migrate.py`
Expected: FAIL with `ImportError` for the new names and a failing table assertion.

- [ ] **Step 3: Write `0002_tutorial.sql`**

```sql
CREATE TABLE outlines (
  id         uuid PRIMARY KEY,
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  version    int  NOT NULL,
  model      text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subject_id, version)
);

CREATE TABLE parts (
  id         uuid PRIMARY KEY,
  outline_id uuid NOT NULL REFERENCES outlines(id) ON DELETE CASCADE,
  position   int  NOT NULL,
  title      text NOT NULL,
  page_start int  NOT NULL,
  page_end   int  NOT NULL,
  UNIQUE (outline_id, position)
);

CREATE TABLE sections (
  id         uuid PRIMARY KEY,
  part_id    uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  position   int  NOT NULL,
  title      text NOT NULL,
  page_start int  NOT NULL,
  page_end   int  NOT NULL,
  UNIQUE (part_id, position)
);

CREATE TABLE glossary_terms (
  id          uuid PRIMARY KEY,
  outline_id  uuid NOT NULL REFERENCES outlines(id) ON DELETE CASCADE,
  slug        text NOT NULL,
  source_term text NOT NULL,
  definition  text NOT NULL,
  pages       int[] NOT NULL,
  UNIQUE (outline_id, slug)
);

CREATE TABLE glossary_translations (
  term_id  uuid NOT NULL REFERENCES glossary_terms(id) ON DELETE CASCADE,
  language text NOT NULL,
  term     text NOT NULL,
  PRIMARY KEY (term_id, language)
);

CREATE TABLE part_content (
  part_id    uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  language   text NOT NULL,
  title      text NOT NULL,
  body       text NOT NULL,
  key_points text[] NOT NULL,
  status     text NOT NULL,
  model      text NOT NULL,
  error      text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (part_id, language)
);

CREATE TABLE section_content (
  section_id uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  language   text NOT NULL,
  title      text NOT NULL,
  summary    text NOT NULL,
  PRIMARY KEY (section_id, language)
);

CREATE TABLE questions (
  id              uuid PRIMARY KEY,
  section_id      uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  language        text NOT NULL,
  kind            text NOT NULL,
  prompt          text NOT NULL,
  expected_answer text NOT NULL,
  rubric          text[] NOT NULL,
  key_terms       text[] NOT NULL,
  exact_values    text[] NOT NULL,
  choices         text[],
  correct_choice  int,
  position        int NOT NULL
);
CREATE INDEX questions_section_language_idx ON questions(section_id, language);
```

- [ ] **Step 4: Append the models to `api/teachme/domain/models.py`**

```python
class ContentStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class QuestionKind(StrEnum):
    FREE_TEXT = "free_text"
    MULTIPLE_CHOICE = "multiple_choice"


class Outline(Frozen):
    id: UUID
    subject_id: UUID
    version: int
    model: str


class _PageRange(Frozen):
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> _PageRange:
        if self.page_end < self.page_start:
            raise ValueError("page_end must not precede page_start")
        return self


class Part(_PageRange):
    id: UUID
    outline_id: UUID
    position: int = Field(ge=0)
    title: str


class Section(_PageRange):
    id: UUID
    part_id: UUID
    position: int = Field(ge=0)
    title: str = ""


class GlossaryTerm(Frozen):
    id: UUID
    outline_id: UUID
    slug: str
    source_term: str
    definition: str
    pages: tuple[int, ...]


class GlossaryTranslation(Frozen):
    term_id: UUID
    language: str
    term: str


class PartContent(Frozen):
    part_id: UUID
    language: str
    title: str
    body: str  # Markdown with {{term:slug|words}} placeholders
    key_points: tuple[str, ...]
    status: ContentStatus
    model: str
    error: str | None = None


class SectionContent(Frozen):
    section_id: UUID
    language: str
    title: str
    summary: str


class Question(Frozen):
    id: UUID
    section_id: UUID
    language: str
    kind: QuestionKind
    prompt: str
    expected_answer: str
    rubric: tuple[str, ...]
    key_terms: tuple[str, ...]
    exact_values: tuple[str, ...]
    choices: tuple[str, ...] | None = None
    correct_choice: int | None = None
    position: int = 0

    @model_validator(mode="after")
    def _choices_match_kind(self) -> Question:
        if self.kind == QuestionKind.MULTIPLE_CHOICE:
            if not self.choices or len(self.choices) < 2:
                raise ValueError("multiple choice needs at least two choices")
            if self.correct_choice is None or not 0 <= self.correct_choice < len(self.choices):
                raise ValueError("correct_choice must index into choices")
        elif self.choices is not None or self.correct_choice is not None:
            raise ValueError("free text questions carry no choices")
        return self
```

Add `model_validator` to the pydantic import at the top of the file: `from pydantic import BaseModel, ConfigDict, Field, model_validator`.

- [ ] **Step 5: Extend `TABLES` in `api/tests/conftest.py`** so truncation covers the new tables (order matters for readability only; CASCADE handles dependencies):

```python
TABLES = [
    "llm_usage", "jobs", "questions", "section_content", "part_content", "glossary_translations",
    "glossary_terms", "sections", "parts", "outlines", "chunks", "source_figures", "source_pages",
    "sources", "subjects",
]
```

- [ ] **Step 6: Run to verify they pass**

Run: `pytest -q api/tests/domain/test_tutorial_models.py api/tests/adapters/test_migrate.py`
Expected: all pass (the migration fixture applies `0002_tutorial` on a fresh test database; if the test database already had `0001` applied, `apply_migrations` applies only `0002`).

- [ ] **Step 7: Commit**

```bash
git add api/teachme/adapters/db/migrations/0002_tutorial.sql api/teachme/domain/models.py api/tests/conftest.py api/tests/domain/test_tutorial_models.py api/tests/adapters/test_migrate.py
git commit -m "feat: tutorial schema migration and domain models"
```

---

### Task 2: Outline, glossary, content and question repositories

**Files:**
- Create: `api/teachme/repositories/outlines.py`, `glossary.py`, `content.py`, `questions.py`
- Test: `api/tests/repositories/test_tutorial_repos.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import (
    ContentStatus,
    GlossaryTerm,
    GlossaryTranslation,
    PartContent,
    Question,
    QuestionKind,
    SectionContent,
)
from teachme.repositories.content import ContentRepository
from teachme.repositories.glossary import GlossaryRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.subjects import SubjectRepository


def _outline(db):
    subject = SubjectRepository(db).create(f"S-{uuid4()}", ["he", "en"])
    repo = OutlineRepository(db)
    outline = repo.create(subject.id, model="fake-model")
    p1 = repo.add_part(outline.id, position=0, title="Intro", page_start=0, page_end=3)
    p2 = repo.add_part(outline.id, position=1, title="Deep", page_start=4, page_end=9)
    s1 = repo.add_section(p1.id, position=0, title="What", page_start=0, page_end=1)
    s2 = repo.add_section(p1.id, position=1, title="Why", page_start=2, page_end=3)
    s3 = repo.add_section(p2.id, position=0, title="How", page_start=4, page_end=9)
    return subject, repo, outline, (p1, p2), (s1, s2, s3)


def test_outline_versions_and_structure(db):
    subject, repo, outline, parts, sections = _outline(db)
    assert outline.version == 1
    second = repo.create(subject.id, model="fake-model")
    assert second.version == 2
    assert repo.latest(subject.id).version == 2
    assert repo.get_version(subject.id, 1) == outline
    assert [p.title for p in repo.parts(outline.id)] == ["Intro", "Deep"]
    assert [s.title for s in repo.sections(parts[0].id)] == ["What", "Why"]
    assert repo.get_part(parts[1].id).page_end == 9
    assert repo.get_section(sections[2].id).part_id == parts[1].id
    assert [s.position for s in repo.sections_of_outline(outline.id)] == [0, 1, 0]


def test_glossary_terms_and_translations(db):
    subject, repo, outline, *_ = _outline(db)
    glossary = GlossaryRepository(db)
    glossary.replace_terms(outline.id, [
        GlossaryTerm(id=uuid4(), outline_id=outline.id, slug="biosphere", source_term="biosfera",
                     definition="All living things", pages=(1, 2)),
        GlossaryTerm(id=uuid4(), outline_id=outline.id, slug="atmosphere", source_term="atmosfera",
                     definition="The air", pages=(3,)),
    ])
    terms = glossary.terms(outline.id)
    assert [t.slug for t in terms] == ["atmosphere", "biosphere"]
    glossary.replace_translations(outline.id, "he", [
        GlossaryTranslation(term_id=terms[0].term_id if hasattr(terms[0], "term_id") else terms[0].id, language="he", term="אטמוספרה"),
        GlossaryTranslation(term_id=terms[1].id, language="he", term="ביוספרה"),
    ])
    translated = glossary.translations(outline.id, "he")
    assert {t.term_id: t.term for t in translated} == {terms[0].id: "אטמוספרה", terms[1].id: "ביוספרה"}
    assert glossary.translations(outline.id, "pt") == []


def test_part_and_section_content(db):
    subject, repo, outline, parts, sections = _outline(db)
    content = ContentRepository(db)
    content.upsert_part(PartContent(part_id=parts[0].id, language="he", title="מבוא", body="{{term:biosphere|הביוספרה}} ...",
                                    key_points=("a", "b"), status=ContentStatus.READY, model="fake-model"))
    content.upsert_sections([
        SectionContent(section_id=sections[0].id, language="he", title="מה", summary="..."),
        SectionContent(section_id=sections[1].id, language="he", title="למה", summary="..."),
    ])
    loaded = content.part(parts[0].id, "he")
    assert loaded is not None and loaded.title == "מבוא" and loaded.key_points == ("a", "b")
    assert content.part(parts[0].id, "en") is None
    assert [s.title for s in content.sections(parts[0].id, "he")] == ["מה", "למה"]
    content.upsert_part(loaded.model_copy(update={"status": ContentStatus.FAILED, "error": "boom"}))
    assert content.part(parts[0].id, "he").error == "boom"
    assert content.languages_ready(outline.id) == {}  # part 2 has no content yet
    content.upsert_part(PartContent(part_id=parts[1].id, language="he", title="x", body="y", key_points=(),
                                    status=ContentStatus.READY, model="m"))
    content.upsert_part(loaded)  # back to READY
    assert content.languages_ready(outline.id) == {"he": 2}


def test_questions_replace_and_query(db):
    subject, repo, outline, parts, sections = _outline(db)
    questions = QuestionRepository(db)
    made = [
        Question(id=uuid4(), section_id=sections[0].id, language="he", kind=QuestionKind.FREE_TEXT, prompt="q1",
                 expected_answer="a1", rubric=("r",), key_terms=("k",), exact_values=("1789",), position=0),
        Question(id=uuid4(), section_id=sections[1].id, language="he", kind=QuestionKind.MULTIPLE_CHOICE, prompt="q2",
                 expected_answer="b", rubric=("r",), key_terms=(), exact_values=(), choices=("a", "b"),
                 correct_choice=1, position=1),
    ]
    questions.replace_for_part(parts[0].id, "he", made)
    loaded = questions.for_part(parts[0].id, "he")
    assert [q.prompt for q in loaded] == ["q1", "q2"]
    assert loaded[1].choices == ("a", "b") and loaded[1].correct_choice == 1
    assert loaded[0].exact_values == ("1789",)
    assert questions.count_by_section(parts[0].id, "he") == {sections[0].id: 1, sections[1].id: 1}
    questions.replace_for_part(parts[0].id, "he", made[:1])
    assert len(questions.for_part(parts[0].id, "he")) == 1
    assert questions.for_part(parts[0].id, "en") == []
```

Note: the glossary test contains a defensive `hasattr` expression; simplify it to `terms[0].id` when writing the file (terms are `GlossaryTerm`, which has `id`).

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/repositories/test_tutorial_repos.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `outlines.py`**

```python
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Outline, Part, Section
from teachme.repositories.errors import NotFound


class OutlineNotFound(NotFound):
    entity = "outline"


class PartNotFound(NotFound):
    entity = "part"


class SectionNotFound(NotFound):
    entity = "section"


def _outline(row: dict) -> Outline:
    return Outline(id=row["id"], subject_id=row["subject_id"], version=row["version"], model=row["model"])


def _part(row: dict) -> Part:
    return Part(id=row["id"], outline_id=row["outline_id"], position=row["position"], title=row["title"],
                page_start=row["page_start"], page_end=row["page_end"])


def _section(row: dict) -> Section:
    return Section(id=row["id"], part_id=row["part_id"], position=row["position"], title=row["title"],
                   page_start=row["page_start"], page_end=row["page_end"])


class OutlineRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, subject_id: UUID, *, model: str) -> Outline:
        row = self._conn.execute(
            "SELECT coalesce(max(version), 0) + 1 AS next FROM outlines WHERE subject_id = %s", (subject_id,)
        ).fetchone()
        outline_id = uuid4()
        self._conn.execute(
            "INSERT INTO outlines (id, subject_id, version, model) VALUES (%s, %s, %s, %s)",
            (outline_id, subject_id, row["next"], model),
        )
        return self.get(outline_id)

    def get(self, outline_id: UUID) -> Outline:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE id = %s", (outline_id,)
        ).fetchone()
        if row is None:
            raise OutlineNotFound(outline_id)
        return _outline(row)

    def latest(self, subject_id: UUID) -> Outline | None:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE subject_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        return _outline(row) if row else None

    def get_version(self, subject_id: UUID, version: int) -> Outline | None:
        row = self._conn.execute(
            "SELECT id, subject_id, version, model FROM outlines WHERE subject_id = %s AND version = %s",
            (subject_id, version),
        ).fetchone()
        return _outline(row) if row else None

    def add_part(self, outline_id: UUID, *, position: int, title: str, page_start: int, page_end: int) -> Part:
        part_id = uuid4()
        self._conn.execute(
            "INSERT INTO parts (id, outline_id, position, title, page_start, page_end) VALUES (%s, %s, %s, %s, %s, %s)",
            (part_id, outline_id, position, title, page_start, page_end),
        )
        return self.get_part(part_id)

    def add_section(self, part_id: UUID, *, position: int, title: str, page_start: int, page_end: int) -> Section:
        section_id = uuid4()
        self._conn.execute(
            "INSERT INTO sections (id, part_id, position, title, page_start, page_end) VALUES (%s, %s, %s, %s, %s, %s)",
            (section_id, part_id, position, title, page_start, page_end),
        )
        return self.get_section(section_id)

    def get_part(self, part_id: UUID) -> Part:
        row = self._conn.execute(
            "SELECT id, outline_id, position, title, page_start, page_end FROM parts WHERE id = %s", (part_id,)
        ).fetchone()
        if row is None:
            raise PartNotFound(part_id)
        return _part(row)

    def get_section(self, section_id: UUID) -> Section:
        row = self._conn.execute(
            "SELECT id, part_id, position, title, page_start, page_end FROM sections WHERE id = %s", (section_id,)
        ).fetchone()
        if row is None:
            raise SectionNotFound(section_id)
        return _section(row)

    def parts(self, outline_id: UUID) -> list[Part]:
        rows = self._conn.execute(
            "SELECT id, outline_id, position, title, page_start, page_end FROM parts WHERE outline_id = %s"
            " ORDER BY position",
            (outline_id,),
        ).fetchall()
        return [_part(row) for row in rows]

    def sections(self, part_id: UUID) -> list[Section]:
        rows = self._conn.execute(
            "SELECT id, part_id, position, title, page_start, page_end FROM sections WHERE part_id = %s"
            " ORDER BY position",
            (part_id,),
        ).fetchall()
        return [_section(row) for row in rows]

    def sections_of_outline(self, outline_id: UUID) -> list[Section]:
        rows = self._conn.execute(
            "SELECT s.id, s.part_id, s.position, s.title, s.page_start, s.page_end FROM sections s"
            " JOIN parts p ON p.id = s.part_id WHERE p.outline_id = %s ORDER BY p.position, s.position",
            (outline_id,),
        ).fetchall()
        return [_section(row) for row in rows]
```

- [ ] **Step 4: Write `glossary.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import GlossaryTerm, GlossaryTranslation


class GlossaryRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_terms(self, outline_id: UUID, terms: Sequence[GlossaryTerm]) -> None:
        self._conn.execute("DELETE FROM glossary_terms WHERE outline_id = %s", (outline_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO glossary_terms (id, outline_id, slug, source_term, definition, pages)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [(t.id, outline_id, t.slug, t.source_term, t.definition, list(t.pages)) for t in terms],
            )

    def terms(self, outline_id: UUID) -> list[GlossaryTerm]:
        rows = self._conn.execute(
            "SELECT id, outline_id, slug, source_term, definition, pages FROM glossary_terms"
            " WHERE outline_id = %s ORDER BY slug",
            (outline_id,),
        ).fetchall()
        return [
            GlossaryTerm(id=r["id"], outline_id=r["outline_id"], slug=r["slug"], source_term=r["source_term"],
                         definition=r["definition"], pages=tuple(r["pages"]))
            for r in rows
        ]

    def replace_translations(self, outline_id: UUID, language: str, translations: Sequence[GlossaryTranslation]) -> None:
        self._conn.execute(
            "DELETE FROM glossary_translations WHERE language = %s AND term_id IN"
            " (SELECT id FROM glossary_terms WHERE outline_id = %s)",
            (language, outline_id),
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO glossary_translations (term_id, language, term) VALUES (%s, %s, %s)",
                [(t.term_id, language, t.term) for t in translations],
            )

    def translations(self, outline_id: UUID, language: str) -> list[GlossaryTranslation]:
        rows = self._conn.execute(
            "SELECT tr.term_id, tr.language, tr.term FROM glossary_translations tr"
            " JOIN glossary_terms t ON t.id = tr.term_id WHERE t.outline_id = %s AND tr.language = %s ORDER BY t.slug",
            (outline_id, language),
        ).fetchall()
        return [GlossaryTranslation(term_id=r["term_id"], language=r["language"], term=r["term"]) for r in rows]
```

- [ ] **Step 5: Write `content.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import ContentStatus, PartContent, SectionContent


class ContentRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_part(self, content: PartContent) -> None:
        self._conn.execute(
            "INSERT INTO part_content (part_id, language, title, body, key_points, status, model, error)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (part_id, language) DO UPDATE SET title = EXCLUDED.title, body = EXCLUDED.body,"
            " key_points = EXCLUDED.key_points, status = EXCLUDED.status, model = EXCLUDED.model,"
            " error = EXCLUDED.error, updated_at = now()",
            (content.part_id, content.language, content.title, content.body, list(content.key_points),
             content.status.value, content.model, content.error),
        )

    def part(self, part_id: UUID, language: str) -> PartContent | None:
        row = self._conn.execute(
            "SELECT part_id, language, title, body, key_points, status, model, error FROM part_content"
            " WHERE part_id = %s AND language = %s",
            (part_id, language),
        ).fetchone()
        if row is None:
            return None
        return PartContent(
            part_id=row["part_id"], language=row["language"], title=row["title"], body=row["body"],
            key_points=tuple(row["key_points"]), status=ContentStatus(row["status"]), model=row["model"],
            error=row["error"],
        )

    def upsert_sections(self, contents: Sequence[SectionContent]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO section_content (section_id, language, title, summary) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (section_id, language) DO UPDATE SET title = EXCLUDED.title, summary = EXCLUDED.summary",
                [(c.section_id, c.language, c.title, c.summary) for c in contents],
            )

    def sections(self, part_id: UUID, language: str) -> list[SectionContent]:
        rows = self._conn.execute(
            "SELECT sc.section_id, sc.language, sc.title, sc.summary FROM section_content sc"
            " JOIN sections s ON s.id = sc.section_id WHERE s.part_id = %s AND sc.language = %s ORDER BY s.position",
            (part_id, language),
        ).fetchall()
        return [SectionContent(section_id=r["section_id"], language=r["language"], title=r["title"],
                               summary=r["summary"]) for r in rows]

    def languages_ready(self, outline_id: UUID) -> dict[str, int]:
        """language -> number of parts with READY content, only for languages where every part is ready."""
        rows = self._conn.execute(
            "SELECT pc.language, count(*) AS ready FROM part_content pc JOIN parts p ON p.id = pc.part_id"
            " WHERE p.outline_id = %s AND pc.status = 'ready' GROUP BY pc.language",
            (outline_id,),
        ).fetchall()
        total = self._conn.execute("SELECT count(*) AS n FROM parts WHERE outline_id = %s", (outline_id,)).fetchone()["n"]
        return {r["language"]: int(r["ready"]) for r in rows if int(r["ready"]) == int(total) and total > 0}
```

- [ ] **Step 6: Write `questions.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Question, QuestionKind

_COLUMNS = (
    "id, section_id, language, kind, prompt, expected_answer, rubric, key_terms, exact_values, choices,"
    " correct_choice, position"
)


def _question(row: dict) -> Question:
    return Question(
        id=row["id"], section_id=row["section_id"], language=row["language"], kind=QuestionKind(row["kind"]),
        prompt=row["prompt"], expected_answer=row["expected_answer"], rubric=tuple(row["rubric"]),
        key_terms=tuple(row["key_terms"]), exact_values=tuple(row["exact_values"]),
        choices=tuple(row["choices"]) if row["choices"] is not None else None,
        correct_choice=row["correct_choice"], position=row["position"],
    )


class QuestionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_for_part(self, part_id: UUID, language: str, questions: Sequence[Question]) -> None:
        self._conn.execute(
            "DELETE FROM questions WHERE language = %s AND section_id IN (SELECT id FROM sections WHERE part_id = %s)",
            (language, part_id),
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO questions ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (q.id, q.section_id, q.language, q.kind.value, q.prompt, q.expected_answer, list(q.rubric),
                     list(q.key_terms), list(q.exact_values), list(q.choices) if q.choices else None,
                     q.correct_choice, q.position)
                    for q in questions
                ],
            )

    def for_part(self, part_id: UUID, language: str) -> list[Question]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM questions WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s) ORDER BY position",
            (language, part_id),
        ).fetchall()
        return [_question(row) for row in rows]

    def count_by_section(self, part_id: UUID, language: str) -> dict[UUID, int]:
        rows = self._conn.execute(
            "SELECT section_id, count(*) AS n FROM questions WHERE language = %s AND section_id IN"
            " (SELECT id FROM sections WHERE part_id = %s) GROUP BY section_id",
            (language, part_id),
        ).fetchall()
        return {row["section_id"]: int(row["n"]) for row in rows}
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest -q api/tests/repositories/test_tutorial_repos.py`
Expected: `4 passed`

- [ ] **Step 8: Commit**

```bash
git add api/teachme/repositories api/tests/repositories/test_tutorial_repos.py
git commit -m "feat: outline, glossary, content and question repositories"
```

---

### Task 3: Cached prompt prefix on the LLM port

**Files:**
- Modify: `api/teachme/ports/llm.py`, `api/teachme/adapters/llm/anthropic.py`
- Test: `api/tests/adapters/test_anthropic_llm.py` (append), `api/tests/adapters/test_fake_llm.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/adapters/test_anthropic_llm.py`:

```python
def test_cached_context_becomes_first_system_block_with_cache_control():
    client = _StubClient(_message())
    request = StructuredRequest(
        purpose="t", model="claude-opus-5", system="instructions", parts=(ContentPart.of_text("x"),),
        cached_context="<corpus>big text</corpus>",
    )
    AnthropicLLM(client=client).generate_structured(request, Answer)
    system = client.calls[0]["system"]
    assert system[0] == {"type": "text", "text": "<corpus>big text</corpus>", "cache_control": {"type": "ephemeral"}}
    assert system[1] == {"type": "text", "text": "instructions"}


def test_without_cached_context_the_single_system_block_is_cached():
    client = _StubClient(_message())
    AnthropicLLM(client=client).generate_structured(_request(), Answer)
    system = client.calls[0]["system"]
    assert len(system) == 1 and system[0]["cache_control"] == {"type": "ephemeral"}
```

Append to `api/tests/adapters/test_fake_llm.py`:

```python
def test_fake_records_cached_context():
    fake = FakeLLM({Out: lambda req: Out(echo=req.cached_context or "")})
    req = StructuredRequest(purpose="t", model="m", system="s", parts=(ContentPart.of_text("x"),), cached_context="C")
    assert fake.generate_structured(req, Out).output.echo == "C"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest -q api/tests/adapters/test_anthropic_llm.py api/tests/adapters/test_fake_llm.py`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'cached_context'`

- [ ] **Step 3: Add the field to `StructuredRequest` in `api/teachme/ports/llm.py`**

```python
@dataclass(frozen=True)
class StructuredRequest:
    purpose: str  # telemetry tag, e.g. "ingest.read_pages"
    model: str
    system: str
    parts: tuple[ContentPart, ...]
    max_tokens: int = 16000
    effort: Effort = "medium"
    cached_context: str | None = None
    """Large, stable text (a subject's whole corpus) placed before `system` and cached across calls.
    Must be byte-identical between calls to hit the cache."""
```

- [ ] **Step 4: Update the system construction in `AnthropicLLM.generate_structured`**

Replace the `system=[...]` argument with `system=_system_blocks(request),` and add:

```python
def _system_blocks(request: StructuredRequest) -> list[dict[str, Any]]:
    """Cache the stable prefix. With a cached_context the instructions follow it uncached, so the
    same corpus is reused by every generation step; without one the instructions are the prefix."""
    if request.cached_context:
        return [
            {"type": "text", "text": request.cached_context, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": request.system},
        ]
    return [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]
```

The fake adapter needs no change: it stores the whole request.

- [ ] **Step 5: Run to verify they pass**

Run: `pytest -q api/tests/adapters/test_anthropic_llm.py api/tests/adapters/test_fake_llm.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add api/teachme/ports/llm.py api/teachme/adapters/llm/anthropic.py api/tests/adapters
git commit -m "feat: cached prompt prefix on structured requests"
```

---

### Task 4: Glossary placeholder renderer (domain)

**Files:**
- Create: `api/teachme/domain/glossary/__init__.py`, `api/teachme/domain/glossary/render.py`
- Test: `api/tests/domain/test_glossary_render.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from teachme.domain.glossary.render import GlossaryView, find_placeholders, render_placeholders

GLOSSARY = GlossaryView(
    source_language="pt",
    source_terms={"biosphere": "biosfera", "atmosphere": "atmosfera"},
)

TEXT = "{{term:biosphere|הביוספרה}} היא חלק. {{term:atmosphere|האטמוספרה}} גם. שוב {{term:biosphere|ביוספרה}}."


def test_find_placeholders_returns_slug_and_words_in_order():
    assert find_placeholders(TEXT) == [
        ("biosphere", "הביוספרה"), ("atmosphere", "האטמוספרה"), ("biosphere", "ביוספרה"),
    ]


def test_first_occurrence_glossed_when_languages_differ():
    out = render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="first")
    assert out == "הביוספרה (biosfera) היא חלק. האטמוספרה (atmosfera) גם. שוב ביוספרה."


def test_every_occurrence():
    out = render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="every")
    assert out.count("(biosfera)") == 2


def test_never_and_same_language_render_words_only():
    assert render_placeholders(TEXT, GLOSSARY, target_language="he", frequency="never") == \
        "הביוספרה היא חלק. האטמוספרה גם. שוב ביוספרה."
    assert "(" not in render_placeholders(TEXT, GLOSSARY, target_language="pt", frequency="first")


def test_unknown_slug_keeps_words_and_is_reported():
    text = "{{term:ghost|רוח}} here"
    assert render_placeholders(text, GLOSSARY, target_language="he", frequency="first") == "רוח here"
    assert find_placeholders(text) == [("ghost", "רוח")]


def test_malformed_placeholder_is_left_untouched():
    text = "{{term:nopipe}} and {{other:x|y}}"
    assert render_placeholders(text, GLOSSARY, target_language="he", frequency="first") == text
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/domain/test_glossary_render.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `domain/glossary/__init__.py`** (empty) **and `render.py`**

```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Frequency = Literal["first", "every", "never"]

PLACEHOLDER = re.compile(r"\{\{term:([a-z0-9][a-z0-9_-]*)\|([^{}|]+?)\}\}")


class GlossaryView(BaseModel):
    """What rendering needs: the source language and each slug's source-language term."""

    model_config = ConfigDict(frozen=True)

    source_language: str | None
    source_terms: dict[str, str]


def find_placeholders(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text)]


def render_placeholders(text: str, glossary: GlossaryView, *, target_language: str, frequency: Frequency) -> str:
    """Replace `{{term:slug|words}}` with the words, followed by the source-language term in
    parentheses when teaching in a different language than the source. Unknown slugs render as
    their words alone; malformed placeholders are left as they are."""
    gloss = frequency != "never" and glossary.source_language is not None and target_language != glossary.source_language
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        slug, words = match.group(1), match.group(2)
        source_term = glossary.source_terms.get(slug)
        if not gloss or source_term is None:
            return words
        if frequency == "first" and slug in seen:
            return words
        seen.add(slug)
        return f"{words} ({source_term})"

    return PLACEHOLDER.sub(replace, text)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/domain/test_glossary_render.py`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/domain/glossary api/tests/domain/test_glossary_render.py
git commit -m "feat: glossary placeholder renderer"
```

---

### Task 5: Generation prompts, corpus builder and validated generation helper

**Files:**
- Create: `api/teachme/generation/__init__.py`, `api/teachme/generation/prompts/__init__.py`, six prompt files, `api/teachme/generation/corpus.py`, `api/teachme/generation/validate.py`, `api/teachme/generation/errors.py`
- Test: `api/tests/generation/test_corpus_validate.py`

- [ ] **Step 1: Write the failing test** (`api/tests/generation/__init__.py` empty)

```python
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Page, Source, SourceStatus
from teachme.generation.corpus import SubjectCorpus, build_corpus
from teachme.generation.errors import GenerationValidationError
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, StructuredRequest


def _source(name, n):
    return Source(id=uuid4(), subject_id=uuid4(), filename=name, media_type="application/pdf", file_key="k",
                  size=1, status=SourceStatus.READY, page_count=n, detected_language="pt")


def test_prompts_exist():
    for name in ("outline", "outline_merge", "glossary", "glossary_translate", "teaching", "questions"):
        assert len(load_prompt(name)) > 100


def test_corpus_renders_sources_in_order_with_global_page_indices():
    a, b = _source("a.pdf", 2), _source("b.pdf", 1)
    pages = {
        a.id: [Page(page_index=0, printed_number="1", text="A0"), Page(page_index=1, printed_number="2", text="A1")],
        b.id: [Page(page_index=0, printed_number=None, text="B0")],
    }
    corpus = build_corpus([a, b], pages)
    assert isinstance(corpus, SubjectCorpus)
    assert corpus.total_pages == 3
    assert corpus.language == "pt"
    text = corpus.render()
    assert text.index('<source name="a.pdf"') < text.index('<source name="b.pdf"')
    assert '<page index="2" printed="">' in text and "B0" in text.split('index="2"')[1]
    assert corpus.page_text(2) == "B0" and corpus.page_text(1) == "A1"
    assert corpus.locate(2) == (b.id, 0)
    assert corpus.render() == corpus.render()  # byte-identical: safe to cache


def test_corpus_language_is_majority_of_sources():
    a, b, c = _source("a", 1), _source("b", 1), _source("c", 1)
    b = b.model_copy(update={"detected_language": "he"})
    c = c.model_copy(update={"detected_language": "he"})
    pages = {s.id: [Page(page_index=0, printed_number=None, text="x")] for s in (a, b, c)}
    assert build_corpus([a, b, c], pages).language == "he"


class Out(BaseModel):
    n: int


def _req(text="go"):
    return StructuredRequest(purpose="gen.test", model="m", system="s", parts=(ContentPart.of_text(text),))


def test_generate_validated_retries_once_with_errors_appended():
    attempts = []

    def responder(req):
        attempts.append(req.parts[-1].text)
        return Out(n=len(attempts))

    llm = FakeLLM({Out: responder})
    result = generate_validated(llm, _req(), Out, validate=lambda out: [] if out.n == 2 else ["n must be 2"])
    assert result.output.n == 2
    assert len(attempts) == 2 and "n must be 2" in attempts[1] and "Previous attempt" in attempts[1]


def test_generate_validated_fails_after_second_invalid_output():
    llm = FakeLLM({Out: lambda req: Out(n=0)})
    with pytest.raises(GenerationValidationError) as info:
        generate_validated(llm, _req(), Out, validate=lambda out: ["still wrong"])
    assert "still wrong" in str(info.value) and len(llm.calls) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_corpus_validate.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/__init__.py`** (empty), **`generation/errors.py`**

```python
from __future__ import annotations


class GenerationError(Exception):
    pass


class GenerationValidationError(GenerationError):
    def __init__(self, purpose: str, errors: list[str]) -> None:
        super().__init__(f"{purpose}: output failed validation twice: {errors}")
        self.errors = errors


class SubjectNotReady(GenerationError):
    pass


class CorpusTooLarge(GenerationError):
    pass
```

- [ ] **Step 4: Write `generation/prompts/__init__.py`**

```python
from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
```

- [ ] **Step 5: Write the six prompt files**

`generation/prompts/outline.md`:

```markdown
You design the structure of a tutorial from textbook material for the subject "{subject}". The whole material is in the cached corpus: every source, every page, wrapped in <source> and <page index="N"> tags. Page indices are global across sources and are the only way to refer to pages.

Produce an ordered list of parts. A part is what a student can absorb in one sitting; a chapter usually yields 3 to 6 parts. Each part has 2 to 6 sections, and a section carries exactly one idea, because sections are the unit that gets re-taught when a student struggles. Every part and every section names the global page range it covers; ranges of consecutive sections may touch or overlap by a page but must stay inside their part's range. Together the parts must cover every page that carries teaching content; skip only front matter, blank pages and pure exercise lists.

Titles are written in the language of the source text. Keep them short and specific.
```

`generation/prompts/outline_merge.md`:

```markdown
You merge several partial outlines, each produced from one source of the subject "{subject}", into one ordered tutorial outline. Keep the parts in the reading order of the sources. Merge parts that clearly cover the same topic across sources; otherwise keep them separate. Preserve every page range exactly; page indices are global and must not be renumbered. Titles stay in the language of the source text.
```

`generation/prompts/glossary.md`:

```markdown
You extract the key terminology of the subject "{subject}" from the cached corpus. A key term is a concept a student must know to understand the material: named phenomena, processes, entities, technical words, and important proper names. Skip ordinary vocabulary.

For each term give: a slug (lowercase ASCII letters, digits and hyphens, stable and descriptive, for example "biosphere" or "treaty-of-tordesillas"), the term exactly as written in the source language in its dictionary form, a one-sentence definition in the source language, and the global page indices where it is introduced or defined. Aim for 15 to 60 terms depending on the size of the material. Slugs must be unique.
```

`generation/prompts/glossary_translate.md`:

```markdown
You translate a glossary of key terms from the source language into the target language "{language}" for a tutorial. For each slug give the standard term a textbook in the target language would use, in dictionary form, not a paraphrase. Where the target language commonly borrows the source term, keep the borrowed form. Return one translation per slug and nothing else.
```

`generation/prompts/teaching.md`:

```markdown
You write the teaching text for one part of a tutorial on the subject "{subject}", in the language "{language}". The cached corpus holds the whole material; the user message names the part, its sections, its page range, and lists the glossary.

Teach, do not summarize: explain the essence so a student who has not read the pages understands it; define each idea when it first appears; move from the concrete to the general; use the figures by telling the student which page to look at and what to notice there. Stay strictly inside the material; do not add facts the pages do not support. Write in Markdown with short paragraphs and headings that follow the sections.

Glossary terms: whenever you use a key term from the glossary, wrap that occurrence as {{term:slug|words}} where "words" is exactly the inflected words you wrote in the sentence, so the sentence reads naturally when the placeholder is replaced by the words. Every glossary term that appears in your text must be wrapped this way, and only glossary slugs may be used.

Also return: a localized title for the part, three to six key points, and for every section of the part a localized title and a one-paragraph summary that a later step can use to re-explain that section alone.
```

`generation/prompts/questions.md`:

```markdown
You write assessment questions for one part of a tutorial on the subject "{subject}", in the language "{language}". The user message gives the part's sections with their page ranges, the teaching text, and the glossary.

Write {count} questions spread across the sections, at least two per section, tagged with the section position. About four out of five are free_text; the rest are multiple_choice with four choices and exactly one correct choice. Free text questions ask for understanding: explain, compare, why, what happens if. Do not ask yes/no questions.

For every question give: the prompt; the expected answer in two or three sentences; a rubric of two or three short points a correct answer must cover; key terms a genuine attempt would likely contain, including synonyms and the source-language form of glossary terms; exact values (dates, numbers, names) for factual questions, otherwise an empty list. Use glossary placeholders {{term:slug|words}} in prompts and expected answers exactly as in the teaching text. Everything must be answerable from the material alone.
```

- [ ] **Step 6: Write `generation/corpus.py`**

```python
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import Page, Source


class CorpusPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    global_index: int
    source_id: UUID
    source_name: str
    page_index: int
    printed_number: str | None
    text: str


class SubjectCorpus(BaseModel):
    """Every page of every ready source, in source order, with global page indices.
    render() is deterministic so the result can be a cached prompt prefix."""

    model_config = ConfigDict(frozen=True)

    pages: tuple[CorpusPage, ...]
    language: str | None

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    def page_text(self, global_index: int) -> str:
        return self.pages[global_index].text

    def locate(self, global_index: int) -> tuple[UUID, int]:
        page = self.pages[global_index]
        return page.source_id, page.page_index

    def render(self, first: int | None = None, last: int | None = None) -> str:
        """Pages [first, last] (inclusive, global) grouped by source. Defaults to everything."""
        first = 0 if first is None else first
        last = self.total_pages - 1 if last is None else last
        out: list[str] = []
        current: UUID | None = None
        for page in self.pages[first : last + 1]:
            if page.source_id != current:
                if current is not None:
                    out.append("</source>")
                out.append(f'<source name="{page.source_name}">')
                current = page.source_id
            out.append(f'<page index="{page.global_index}" printed="{page.printed_number or ""}">\n{page.text}\n</page>')
        if current is not None:
            out.append("</source>")
        return "\n".join(out)


def build_corpus(sources: Sequence[Source], pages_by_source: Mapping[UUID, Sequence[Page]]) -> SubjectCorpus:
    corpus_pages: list[CorpusPage] = []
    for source in sources:
        for page in sorted(pages_by_source[source.id], key=lambda p: p.page_index):
            corpus_pages.append(
                CorpusPage(global_index=len(corpus_pages), source_id=source.id, source_name=source.filename,
                           page_index=page.page_index, printed_number=page.printed_number, text=page.text)
            )
    languages = Counter(s.detected_language for s in sources if s.detected_language)
    language = languages.most_common(1)[0][0] if languages else None
    return SubjectCorpus(pages=tuple(corpus_pages), language=language)
```

- [ ] **Step 7: Write `generation/validate.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from teachme.generation.errors import GenerationValidationError
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest, StructuredResult, T

Validator = Callable[[T], list[str]]


def generate_validated(
    llm: LLMProvider, request: StructuredRequest, schema: type[T], *, validate: Validator
) -> StructuredResult[T]:
    """Call once; if the validator returns errors, call once more with the errors appended to the
    user message; if it still fails, raise. Generated output is never trusted without this."""
    result = llm.generate_structured(request, schema)
    errors = validate(result.output)
    if not errors:
        return result
    feedback = (
        "\n\nPrevious attempt failed validation. Fix every problem below and return the complete output again:\n- "
        + "\n- ".join(errors)
    )
    retry = replace(request, parts=(*request.parts, ContentPart.of_text(feedback)))
    result = llm.generate_structured(retry, schema)
    errors = validate(result.output)
    if errors:
        raise GenerationValidationError(request.purpose, errors)
    return result
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_corpus_validate.py`
Expected: `5 passed`

- [ ] **Step 9: Commit**

```bash
git add api/teachme/generation api/tests/generation
git commit -m "feat: generation prompts, subject corpus and validated generation helper"
```

---

### Task 6: Outline generation

**Files:**
- Create: `api/teachme/generation/outline.py`
- Modify: `api/teachme/generation/corpus.py` (add `source_ranges`)
- Test: `api/tests/generation/test_outline.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Page, Source, SourceStatus
from teachme.generation.corpus import build_corpus
from teachme.generation.errors import GenerationValidationError
from teachme.generation.outline import (
    LARGE_CORPUS_CHARS,
    OutlineOut,
    PartOut,
    SectionOut,
    generate_outline,
    validate_outline,
)


def _corpus(n_pages, sources=1):
    srcs, pages = [], {}
    per = n_pages // sources
    for i in range(sources):
        s = Source(id=uuid4(), subject_id=uuid4(), filename=f"s{i}.pdf", media_type="application/pdf", file_key="k",
                   size=1, status=SourceStatus.READY, page_count=per, detected_language="en")
        srcs.append(s)
        pages[s.id] = [Page(page_index=j, printed_number=None, text=f"text {i}-{j}") for j in range(per)]
    return build_corpus(srcs, pages)


def _good_outline(total):
    half = total // 2
    return OutlineOut(parts=[
        PartOut(title="A", page_start=0, page_end=half - 1,
                sections=[SectionOut(title="a1", page_start=0, page_end=half - 1)]),
        PartOut(title="B", page_start=half, page_end=total - 1,
                sections=[SectionOut(title="b1", page_start=half, page_end=total - 1)]),
    ])


def test_source_ranges():
    corpus = _corpus(6, sources=2)
    ranges = corpus.source_ranges()
    assert [(f, l) for _, f, l in ranges] == [(0, 2), (3, 5)]


def test_validate_outline_catches_range_and_order_errors():
    total = 6
    assert validate_outline(_good_outline(total), total) == []
    bad = OutlineOut(parts=[
        PartOut(title="A", page_start=0, page_end=9, sections=[SectionOut(title="x", page_start=0, page_end=1)]),
        PartOut(title="B", page_start=0, page_end=2, sections=[SectionOut(title="y", page_start=5, page_end=2)]),
    ])
    errors = validate_outline(bad, total)
    assert any("page_end 9" in e for e in errors)
    assert any("before" in e or "order" in e for e in errors)
    assert any("section" in e and "outside" in e for e in errors)


def test_generate_outline_uses_cached_corpus_and_validates():
    corpus = _corpus(6)
    llm = FakeLLM({OutlineOut: lambda req: _good_outline(6)})
    out = generate_outline(llm, "fake-model", "Geo", corpus)
    assert [p.title for p in out.parts] == ["A", "B"]
    call = llm.calls[0]
    assert call.purpose == "gen.outline" and call.cached_context == corpus.render()
    assert "Geo" in call.system and "6 pages" in call.parts[0].text


def test_generate_outline_fails_after_retry():
    corpus = _corpus(6)
    bad = OutlineOut(parts=[PartOut(title="A", page_start=0, page_end=99, sections=[SectionOut(title="x", page_start=0, page_end=1)])])
    llm = FakeLLM({OutlineOut: lambda req: bad})
    with pytest.raises(GenerationValidationError):
        generate_outline(llm, "fake-model", "Geo", corpus)
    assert len(llm.calls) == 2


def test_large_corpus_goes_per_source_then_merge(monkeypatch):
    import teachme.generation.outline as outline_module

    monkeypatch.setattr(outline_module, "LARGE_CORPUS_CHARS", 10)  # force the split path
    corpus = _corpus(6, sources=2)
    calls = []

    def responder(req):
        calls.append(req.purpose)
        if req.purpose == "gen.outline_source":
            first = int(req.parts[0].text.split("pages ")[1].split("-")[0])
            return OutlineOut(parts=[PartOut(title=f"P{first}", page_start=first, page_end=first + 2,
                                             sections=[SectionOut(title="s", page_start=first, page_end=first + 2)])])
        return _good_outline(6)

    llm = FakeLLM({OutlineOut: responder})
    out = generate_outline(llm, "fake-model", "Geo", corpus)
    assert calls == ["gen.outline_source", "gen.outline_source", "gen.outline_merge"]
    assert len(out.parts) == 2
    assert LARGE_CORPUS_CHARS > 10  # module constant untouched outside the monkeypatch
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_outline.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add `source_ranges` to `SubjectCorpus` in `generation/corpus.py`**

```python
    def source_ranges(self) -> list[tuple[UUID, int, int]]:
        """(source_id, first_global_index, last_global_index) per source, in order."""
        ranges: list[tuple[UUID, int, int]] = []
        for page in self.pages:
            if ranges and ranges[-1][0] == page.source_id:
                ranges[-1] = (page.source_id, ranges[-1][1], page.global_index)
            else:
                ranges.append((page.source_id, page.global_index, page.global_index))
        return ranges
```

- [ ] **Step 4: Write `generation/outline.py`**

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

OUTLINE_MAX_TOKENS = 16000
# Above this many rendered characters (roughly 600k tokens) the outline is produced per source and
# merged, so a very large subject still fits one model call at a time.
LARGE_CORPUS_CHARS = 2_500_000


class SectionOut(BaseModel):
    title: str = Field(description="Short title in the source language; one idea")
    page_start: int = Field(ge=0, description="Global page index of the first page")
    page_end: int = Field(ge=0, description="Global page index of the last page")


class PartOut(BaseModel):
    title: str = Field(description="Short title in the source language")
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)
    sections: list[SectionOut] = Field(min_length=1, description="2 to 6 sections, in reading order")


class OutlineOut(BaseModel):
    parts: list[PartOut] = Field(min_length=1, description="Parts in reading order; 3 to 6 for a chapter")


def validate_outline(out: OutlineOut, total_pages: int) -> list[str]:
    errors: list[str] = []
    last_end = -1
    for i, part in enumerate(out.parts):
        if part.page_end < part.page_start:
            errors.append(f"part {i} '{part.title}': page_end {part.page_end} before page_start {part.page_start}")
        if part.page_end >= total_pages:
            errors.append(f"part {i} '{part.title}': page_end {part.page_end} exceeds last page index {total_pages - 1}")
        if part.page_start < last_end:
            errors.append(f"part {i} '{part.title}': starts at {part.page_start}, out of order with the previous part ending {last_end}")
        last_end = max(last_end, part.page_end)
        for j, section in enumerate(part.sections):
            if section.page_end < section.page_start:
                errors.append(f"part {i} section {j}: page_end before page_start")
            if section.page_start < part.page_start or section.page_end > part.page_end:
                errors.append(
                    f"part {i} section {j} '{section.title}': pages {section.page_start}-{section.page_end}"
                    f" outside the part's range {part.page_start}-{part.page_end}"
                )
    return errors


def generate_outline(llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus) -> OutlineOut:
    rendered = corpus.render()
    if len(rendered) <= LARGE_CORPUS_CHARS:
        request = StructuredRequest(
            purpose="gen.outline", model=model, system=load_prompt("outline").format(subject=subject_name),
            parts=(ContentPart.of_text(f"Design the outline for all {corpus.total_pages} pages of the corpus."),),
            cached_context=rendered, max_tokens=OUTLINE_MAX_TOKENS, effort="high",
        )
        return generate_validated(
            llm, request, OutlineOut, validate=lambda out: validate_outline(out, corpus.total_pages)
        ).output
    return _outline_per_source_then_merge(llm, model, subject_name, corpus)


def _outline_per_source_then_merge(
    llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus
) -> OutlineOut:
    partials: list[OutlineOut] = []
    system = load_prompt("outline").format(subject=subject_name)
    for _, first, last in corpus.source_ranges():
        request = StructuredRequest(
            purpose="gen.outline_source", model=model, system=system,
            parts=(ContentPart.of_text(
                f"Design the outline for pages {first}-{last} only. Use these global page indices.\n\n"
                + corpus.render(first, last)
            ),),
            max_tokens=OUTLINE_MAX_TOKENS, effort="high",
        )
        partial = generate_validated(
            llm, request, OutlineOut, validate=lambda out: _validate_within(out, first, last)
        ).output
        partials.append(partial)
    merge_request = StructuredRequest(
        purpose="gen.outline_merge", model=model, system=load_prompt("outline_merge").format(subject=subject_name),
        parts=(ContentPart.of_text(
            "Partial outlines in source order:\n\n" + "\n\n".join(p.model_dump_json(indent=2) for p in partials)
        ),),
        max_tokens=OUTLINE_MAX_TOKENS, effort="high",
    )
    return generate_validated(
        llm, merge_request, OutlineOut, validate=lambda out: validate_outline(out, corpus.total_pages)
    ).output


def _validate_within(out: OutlineOut, first: int, last: int) -> list[str]:
    errors = validate_outline(out, last + 1)
    for i, part in enumerate(out.parts):
        if part.page_start < first:
            errors.append(f"part {i} starts before page {first}")
    return errors
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_outline.py`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add api/teachme/generation/outline.py api/teachme/generation/corpus.py api/tests/generation/test_outline.py
git commit -m "feat: outline generation with validation and per-source merge path"
```

---

### Task 7: Glossary extraction and translation

**Files:**
- Create: `api/teachme/generation/glossary.py`
- Test: `api/tests/generation/test_glossary.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm
from teachme.generation.glossary import (
    GlossaryOut,
    GlossaryTranslationOut,
    TermOut,
    TranslationOut,
    generate_glossary,
    translate_glossary,
    validate_glossary,
    validate_translations,
)
from tests.generation.test_outline import _corpus


def test_validate_glossary_slugs_unique_and_pages_in_range():
    good = GlossaryOut(terms=[TermOut(slug="biosphere", term="biosfera", definition="d", pages=[0, 1])])
    assert validate_glossary(good, total_pages=3) == []
    bad = GlossaryOut(terms=[
        TermOut(slug="a", term="x", definition="d", pages=[7]),
        TermOut(slug="a", term="y", definition="d", pages=[]),
        TermOut(slug="c", term="", definition="d", pages=[0]),
    ])
    errors = validate_glossary(bad, total_pages=3)
    assert any("duplicate slug" in e for e in errors)
    assert any("page 7" in e for e in errors)
    assert any("empty term" in e for e in errors)


def test_generate_glossary_uses_cached_corpus():
    corpus = _corpus(4)
    llm = FakeLLM({GlossaryOut: lambda req: GlossaryOut(terms=[TermOut(slug="t", term="T", definition="d", pages=[0])])})
    out = generate_glossary(llm, "fake-model", "Geo", corpus)
    assert out.terms[0].slug == "t"
    assert llm.calls[0].purpose == "gen.glossary" and llm.calls[0].cached_context == corpus.render()


def test_translate_glossary_validates_full_coverage():
    terms = [
        GlossaryTerm(id=uuid4(), outline_id=uuid4(), slug="biosphere", source_term="biosfera", definition="d", pages=(0,)),
        GlossaryTerm(id=uuid4(), outline_id=uuid4(), slug="atmosphere", source_term="atmosfera", definition="d", pages=(1,)),
    ]
    complete = GlossaryTranslationOut(translations=[
        TranslationOut(slug="biosphere", term="ביוספרה"), TranslationOut(slug="atmosphere", term="אטמוספרה"),
    ])
    assert validate_translations(complete, {"biosphere", "atmosphere"}) == []
    partial = GlossaryTranslationOut(translations=[TranslationOut(slug="biosphere", term="ביוספרה"),
                                                    TranslationOut(slug="ghost", term="x")])
    errors = validate_translations(partial, {"biosphere", "atmosphere"})
    assert any("missing" in e and "atmosphere" in e for e in errors)
    assert any("unknown slug" in e and "ghost" in e for e in errors)

    llm = FakeLLM({GlossaryTranslationOut: lambda req: complete})
    out = translate_glossary(llm, "fake-model", "he", terms)
    assert {t.slug: t.term for t in out.translations}["atmosphere"] == "אטמוספרה"
    call = llm.calls[0]
    assert call.purpose == "gen.glossary_translate" and call.cached_context is None
    assert "TERM: biosphere | biosfera | d" in call.parts[0].text and "he" in call.system
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_glossary.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/glossary.py`**

```python
from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import GlossaryTerm
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

GLOSSARY_MAX_TOKENS = 16000
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class TermOut(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN, description="lowercase ascii, digits and hyphens; unique")
    term: str = Field(description="The term as written in the source language, dictionary form")
    definition: str = Field(description="One sentence in the source language")
    pages: list[int] = Field(description="Global page indices where the term is introduced")


class GlossaryOut(BaseModel):
    terms: list[TermOut]


class TranslationOut(BaseModel):
    slug: str
    term: str = Field(description="The standard target-language term, dictionary form")


class GlossaryTranslationOut(BaseModel):
    translations: list[TranslationOut]


def validate_glossary(out: GlossaryOut, total_pages: int) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for term in out.terms:
        if term.slug in seen:
            errors.append(f"duplicate slug {term.slug!r}")
        seen.add(term.slug)
        if not term.term.strip():
            errors.append(f"slug {term.slug!r}: empty term")
        for page in term.pages:
            if page < 0 or page >= total_pages:
                errors.append(f"slug {term.slug!r}: page {page} outside 0-{total_pages - 1}")
    return errors


def validate_translations(out: GlossaryTranslationOut, slugs: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for tr in out.translations:
        if tr.slug not in slugs:
            errors.append(f"unknown slug {tr.slug!r}")
        elif tr.slug in seen:
            errors.append(f"duplicate translation for {tr.slug!r}")
        if not tr.term.strip():
            errors.append(f"slug {tr.slug!r}: empty translation")
        seen.add(tr.slug)
    for slug in sorted(slugs - seen):
        errors.append(f"missing translation for {slug!r}")
    return errors


def generate_glossary(llm: LLMProvider, model: str, subject_name: str, corpus: SubjectCorpus) -> GlossaryOut:
    request = StructuredRequest(
        purpose="gen.glossary", model=model, system=load_prompt("glossary").format(subject=subject_name),
        parts=(ContentPart.of_text(f"Extract the key terminology from all {corpus.total_pages} pages."),),
        cached_context=corpus.render(), max_tokens=GLOSSARY_MAX_TOKENS, effort="medium",
    )
    return generate_validated(
        llm, request, GlossaryOut, validate=lambda out: validate_glossary(out, corpus.total_pages)
    ).output


def render_terms(terms: Sequence[GlossaryTerm]) -> str:
    return "\n".join(f"TERM: {t.slug} | {t.source_term} | {t.definition}" for t in terms)


def translate_glossary(
    llm: LLMProvider, model: str, language: str, terms: Sequence[GlossaryTerm]
) -> GlossaryTranslationOut:
    request = StructuredRequest(
        purpose="gen.glossary_translate", model=model,
        system=load_prompt("glossary_translate").format(language=language),
        parts=(ContentPart.of_text(render_terms(terms)),), max_tokens=8000, effort="low",
    )
    slugs = {t.slug for t in terms}
    return generate_validated(
        llm, request, GlossaryTranslationOut, validate=lambda out: validate_translations(out, slugs)
    ).output
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_glossary.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/generation/glossary.py api/tests/generation/test_glossary.py
git commit -m "feat: glossary extraction and translation"
```

---

### Task 8: Teaching text generation

**Files:**
- Create: `api/teachme/generation/teaching.py`
- Test: `api/tests/generation/test_teaching.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm, Part, Section
from teachme.generation.teaching import (
    SectionContentOut,
    TeachingOut,
    generate_teaching,
    render_brief,
    validate_teaching,
)
from tests.generation.test_outline import _corpus


def _structure():
    outline_id, part_id = uuid4(), uuid4()
    part = Part(id=part_id, outline_id=outline_id, position=0, title="Intro", page_start=0, page_end=3)
    sections = [
        Section(id=uuid4(), part_id=part_id, position=0, title="What", page_start=0, page_end=1),
        Section(id=uuid4(), part_id=part_id, position=1, title="Why", page_start=2, page_end=3),
    ]
    terms = [GlossaryTerm(id=uuid4(), outline_id=outline_id, slug="biosphere", source_term="biosfera",
                          definition="d", pages=(0,))]
    return part, sections, terms


def _good(body="x" * 300):
    return TeachingOut(title="מבוא", body_markdown=body, key_points=["a", "b", "c"],
                       sections=[SectionContentOut(position=0, title="מה", summary="s"),
                                 SectionContentOut(position=1, title="למה", summary="s")])


def test_validate_teaching():
    part, sections, terms = _structure()
    slugs = {t.slug for t in terms}
    assert validate_teaching(_good("{{term:biosphere|הביוספרה}} " + "x" * 300), sections, slugs) == []
    short = _good("tiny")
    assert any("too short" in e for e in validate_teaching(short, sections, slugs))
    missing_section = _good().model_copy(update={"sections": [SectionContentOut(position=0, title="t", summary="s")]})
    assert any("sections" in e for e in validate_teaching(missing_section, sections, slugs))
    unknown = _good("{{term:ghost|x}} " + "x" * 300)
    assert any("unknown glossary slug" in e and "ghost" in e for e in validate_teaching(unknown, sections, slugs))


def test_render_brief_lists_sections_and_glossary_and_pages():
    part, sections, terms = _structure()
    brief = render_brief(part, sections, terms, {"biosphere": "ביוספרה"}, _corpus(4), "he")
    assert "PART: Intro" in brief and "PAGES: 0-3" in brief
    assert "SECTION 0: What (pages 0-1)" in brief and "SECTION 1: Why (pages 2-3)" in brief
    assert "TERM: biosphere | biosfera | ביוספרה" in brief
    assert '<page index="3"' in brief and '<page index="4"' not in brief


def test_generate_teaching_uses_cached_corpus_and_language():
    part, sections, terms = _structure()
    corpus = _corpus(4)
    llm = FakeLLM({TeachingOut: lambda req: _good("{{term:biosphere|הביוספרה}} " + "y" * 300)})
    out = generate_teaching(llm, "fake-model", "Geo", "he", corpus, part, sections, terms, {"biosphere": "ביוספרה"})
    assert out.title == "מבוא"
    call = llm.calls[0]
    assert call.purpose == "gen.teaching" and call.cached_context == corpus.render()
    assert '"he"' in call.system and "Geo" in call.system
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_teaching.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/teaching.py`**

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from teachme.domain.glossary.render import find_placeholders
from teachme.domain.models import GlossaryTerm, Part, Section
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

TEACHING_MAX_TOKENS = 24000
MIN_BODY_CHARS = 200


class SectionContentOut(BaseModel):
    position: int = Field(ge=0, description="The section position given in the brief")
    title: str = Field(description="Localized section title")
    summary: str = Field(description="One paragraph a later step can use to re-explain this section alone")


class TeachingOut(BaseModel):
    title: str = Field(description="Localized part title")
    body_markdown: str = Field(description="Teaching text with {{term:slug|words}} placeholders")
    key_points: list[str] = Field(min_length=3, max_length=6)
    sections: list[SectionContentOut]


def validate_teaching(out: TeachingOut, sections: Sequence[Section], slugs: set[str]) -> list[str]:
    errors: list[str] = []
    if len(out.body_markdown.strip()) < MIN_BODY_CHARS:
        errors.append(f"body_markdown too short ({len(out.body_markdown.strip())} chars)")
    expected = sorted(s.position for s in sections)
    got = sorted(s.position for s in out.sections)
    if got != expected:
        errors.append(f"sections must cover positions {expected} exactly once, got {got}")
    for slug, _ in find_placeholders(out.body_markdown):
        if slug not in slugs:
            errors.append(f"unknown glossary slug {slug!r} in body_markdown")
    return errors


def render_brief(
    part: Part,
    sections: Sequence[Section],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    corpus: SubjectCorpus,
    language: str,
) -> str:
    """The user message: what to teach, where it is, and which terms to wrap. Machine-readable
    line prefixes (PART, PAGES, SECTION n, TERM) are relied on by the fake responders."""
    lines = [f"PART: {part.title}", f"PAGES: {part.page_start}-{part.page_end}", f"LANGUAGE: {language}"]
    lines += [f"SECTION {s.position}: {s.title} (pages {s.page_start}-{s.page_end})" for s in sections]
    lines += [f"TERM: {t.slug} | {t.source_term} | {translations.get(t.slug, t.source_term)}" for t in terms]
    lines.append("")
    lines.append("The part's pages, for focus (the full corpus is available for context):")
    lines.append(corpus.render(part.page_start, part.page_end))
    return "\n".join(lines)


def generate_teaching(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    language: str,
    corpus: SubjectCorpus,
    part: Part,
    sections: Sequence[Section],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
) -> TeachingOut:
    request = StructuredRequest(
        purpose="gen.teaching", model=model,
        system=load_prompt("teaching").format(subject=subject_name, language=f'"{language}"'),
        parts=(ContentPart.of_text(render_brief(part, sections, terms, translations, corpus, language)),),
        cached_context=corpus.render(), max_tokens=TEACHING_MAX_TOKENS, effort="high",
    )
    slugs = {t.slug for t in terms}
    return generate_validated(
        llm, request, TeachingOut, validate=lambda out: validate_teaching(out, sections, slugs)
    ).output
```

Note: the prompt file `teaching.md` contains `"{language}"` in quotes; `.format(language=f'"{language}"')` would double the quotes. Edit `teaching.md` to use `{language}` without surrounding quotes in the first sentence: `in the language {language}.` Do the same in `questions.md` (`in the language {language}.`) and keep the `.format(language=f'"{language}"')` call so the rendered system prompt reads `in the language "he".`, which the test asserts.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_teaching.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/generation/teaching.py api/teachme/generation/prompts/teaching.md api/teachme/generation/prompts/questions.md api/tests/generation/test_teaching.py
git commit -m "feat: teaching text generation with placeholder validation"
```

---

### Task 9: Question bank generation

**Files:**
- Create: `api/teachme/generation/question_bank.py`
- Test: `api/tests/generation/test_question_bank.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import QuestionKind
from teachme.generation.question_bank import (
    QuestionBankOut,
    QuestionOut,
    augment_key_terms,
    generate_question_bank,
    to_questions,
    validate_bank,
)
from tests.generation.test_outline import _corpus
from tests.generation.test_teaching import _good, _structure


def _bank(n_per_section=2, mc=True):
    qs = []
    for pos in (0, 1):
        for i in range(n_per_section):
            qs.append(QuestionOut(section_position=pos, kind=QuestionKind.FREE_TEXT, prompt=f"q{pos}{i} {{{{term:biosphere|biosfera}}}}",
                                  expected_answer="a", rubric=["r1", "r2"], key_terms=["k"], exact_values=[]))
    if mc:
        qs.append(QuestionOut(section_position=0, kind=QuestionKind.MULTIPLE_CHOICE, prompt="mc", expected_answer="b",
                              rubric=["r"], key_terms=[], exact_values=[], choices=["a", "b", "c", "d"], correct_choice=1))
    return QuestionBankOut(questions=qs)


def test_validate_bank():
    part, sections, terms = _structure()
    slugs = {t.slug for t in terms}
    assert validate_bank(_bank(), sections, slugs, min_per_section=2) == []
    errors = validate_bank(_bank(n_per_section=1, mc=False), sections, slugs, min_per_section=2)
    assert any("section 0" in e and "at least 2" in e for e in errors)
    assert any("multiple_choice" in e for e in errors)
    bad_pos = QuestionBankOut(questions=[QuestionOut(section_position=9, kind=QuestionKind.FREE_TEXT, prompt="p",
                                                     expected_answer="a", rubric=["r"], key_terms=[], exact_values=[])])
    assert any("unknown section position 9" in e for e in validate_bank(bad_pos, sections, slugs, min_per_section=0))
    bad_mc = QuestionBankOut(questions=[QuestionOut(section_position=0, kind=QuestionKind.MULTIPLE_CHOICE, prompt="p",
                                                    expected_answer="a", rubric=["r"], key_terms=[], exact_values=[],
                                                    choices=["a", "b"], correct_choice=5)])
    assert any("correct_choice" in e for e in validate_bank(bad_mc, sections, slugs, min_per_section=0))


def test_augment_key_terms_adds_glossary_forms():
    q = QuestionOut(section_position=0, kind=QuestionKind.FREE_TEXT, prompt="{{term:biosphere|הביוספרה}}?",
                    expected_answer="{{term:atmosphere|האטמוספרה}}", rubric=["r"], key_terms=["k"], exact_values=[])
    terms = augment_key_terms(q, {"biosphere": "biosfera", "atmosphere": "atmosfera"}, {"biosphere": "ביוספרה"})
    assert terms == ("k", "biosfera", "ביוספרה", "atmosfera")


def test_to_questions_maps_positions_to_section_ids_and_strips_placeholders_only_from_choices():
    part, sections, terms = _structure()
    questions = to_questions(_bank(), sections, "he", {"biosphere": "biosfera"}, {"biosphere": "ביוספרה"})
    assert len(questions) == 5
    assert {q.section_id for q in questions} == {s.id for s in sections}
    assert [q.position for q in questions] == [0, 1, 2, 3, 4]
    assert "{{term:biosphere|biosfera}}" in questions[0].prompt  # placeholders stay; rendered at serve time
    mc = [q for q in questions if q.kind == QuestionKind.MULTIPLE_CHOICE][0]
    assert mc.choices == ("a", "b", "c", "d") and mc.correct_choice == 1


def test_generate_question_bank_request_shape():
    part, sections, terms = _structure()
    corpus = _corpus(4)
    llm = FakeLLM({QuestionBankOut: lambda req: _bank()})
    out = generate_question_bank(llm, "fake-model", "Geo", "he", corpus, part, sections, _good(), terms,
                                 {"biosphere": "ביוספרה"}, count=5)
    assert len(out.questions) == 5
    call = llm.calls[0]
    assert call.purpose == "gen.questions" and call.cached_context == corpus.render()
    assert "COUNT: 5" in call.parts[0].text and "TEACHING:" in call.parts[0].text and "SECTION 1:" in call.parts[0].text
    assert "{count}" not in call.system and "5 questions" in call.system
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_question_bank.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/question_bank.py`**

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

from teachme.domain.glossary.render import find_placeholders
from teachme.domain.models import GlossaryTerm, Part, Question, QuestionKind, Section
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.generation.teaching import TeachingOut
from teachme.generation.validate import generate_validated
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

QUESTIONS_MAX_TOKENS = 24000
MC_CHOICES = 4


class QuestionOut(BaseModel):
    section_position: int = Field(ge=0, description="Position of the section this question tests")
    kind: QuestionKind
    prompt: str = Field(description="The question, with glossary placeholders")
    expected_answer: str = Field(description="Two or three sentences")
    rubric: list[str] = Field(min_length=1, max_length=4, description="Points a correct answer must cover")
    key_terms: list[str] = Field(description="Terms a genuine attempt would contain, with synonyms")
    exact_values: list[str] = Field(default_factory=list, description="Dates, numbers, names for factual questions")
    choices: list[str] | None = Field(default=None, description="Exactly four for multiple_choice, else null")
    correct_choice: int | None = Field(default=None, description="Index into choices for multiple_choice")


class QuestionBankOut(BaseModel):
    questions: list[QuestionOut]


def validate_bank(out: QuestionBankOut, sections: Sequence[Section], slugs: set[str], *, min_per_section: int) -> list[str]:
    errors: list[str] = []
    positions = {s.position for s in sections}
    per_section = {p: 0 for p in positions}
    has_mc = False
    for i, q in enumerate(out.questions):
        if q.section_position not in positions:
            errors.append(f"question {i}: unknown section position {q.section_position}")
        else:
            per_section[q.section_position] += 1
        if q.kind == QuestionKind.MULTIPLE_CHOICE:
            has_mc = True
            if not q.choices or len(q.choices) != MC_CHOICES:
                errors.append(f"question {i}: multiple_choice needs exactly {MC_CHOICES} choices")
            if q.correct_choice is None or not q.choices or not 0 <= q.correct_choice < len(q.choices):
                errors.append(f"question {i}: correct_choice must index into choices")
        elif q.choices is not None:
            errors.append(f"question {i}: free_text must not have choices")
        for text in (q.prompt, q.expected_answer):
            for slug, _ in find_placeholders(text):
                if slug not in slugs:
                    errors.append(f"question {i}: unknown glossary slug {slug!r}")
    for position, count in sorted(per_section.items()):
        if count < min_per_section:
            errors.append(f"section {position}: has {count} questions, needs at least {min_per_section}")
    if len(out.questions) >= 5 and not has_mc:
        errors.append("include at least one multiple_choice question")
    return errors


def augment_key_terms(q: QuestionOut, source_terms: Mapping[str, str], target_terms: Mapping[str, str]) -> tuple[str, ...]:
    """Key terms plus the source- and target-language forms of every glossary term the question uses,
    so a student writing either form scores as on-topic."""
    terms = list(q.key_terms)
    for slug, _ in find_placeholders(q.prompt + " " + q.expected_answer):
        for candidate in (source_terms.get(slug), target_terms.get(slug)):
            if candidate and candidate not in terms:
                terms.append(candidate)
    return tuple(terms)


def to_questions(
    out: QuestionBankOut,
    sections: Sequence[Section],
    language: str,
    source_terms: Mapping[str, str],
    target_terms: Mapping[str, str],
) -> list[Question]:
    by_position = {s.position: s.id for s in sections}
    return [
        Question(
            id=uuid4(), section_id=by_position[q.section_position], language=language, kind=q.kind,
            prompt=q.prompt, expected_answer=q.expected_answer, rubric=tuple(q.rubric),
            key_terms=augment_key_terms(q, source_terms, target_terms), exact_values=tuple(q.exact_values),
            choices=tuple(q.choices) if q.choices else None, correct_choice=q.correct_choice, position=i,
        )
        for i, q in enumerate(out.questions)
    ]


def render_brief(
    part: Part,
    sections: Sequence[Section],
    teaching: TeachingOut,
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    count: int,
) -> str:
    lines = [f"PART: {part.title}", f"PAGES: {part.page_start}-{part.page_end}", f"COUNT: {count}"]
    lines += [f"SECTION {s.position}: {s.title} (pages {s.page_start}-{s.page_end})" for s in sections]
    lines += [f"TERM: {t.slug} | {t.source_term} | {translations.get(t.slug, t.source_term)}" for t in terms]
    lines += ["", "TEACHING:", teaching.body_markdown]
    return "\n".join(lines)


def generate_question_bank(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    language: str,
    corpus: SubjectCorpus,
    part: Part,
    sections: Sequence[Section],
    teaching: TeachingOut,
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    *,
    count: int,
    min_per_section: int = 2,
) -> QuestionBankOut:
    request = StructuredRequest(
        purpose="gen.questions", model=model,
        system=load_prompt("questions").format(subject=subject_name, language=f'"{language}"', count=count),
        parts=(ContentPart.of_text(render_brief(part, sections, teaching, terms, translations, count)),),
        cached_context=corpus.render(), max_tokens=QUESTIONS_MAX_TOKENS, effort="high",
    )
    slugs = {t.slug for t in terms}
    return generate_validated(
        llm, request, QuestionBankOut,
        validate=lambda out: validate_bank(out, sections, slugs, min_per_section=min_per_section),
    ).output
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_question_bank.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/generation/question_bank.py api/tests/generation/test_question_bank.py
git commit -m "feat: question bank generation with validation and key-term augmentation"
```

---

### Task 10: Fake responders for the generation schemas

**Files:**
- Create: `api/teachme/generation/fake_responders.py`
- Modify: `api/teachme/container.py` (fake LLM gets both responder sets)
- Test: `api/tests/generation/test_fake_responders.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import GlossaryTerm
from teachme.generation.fake_responders import default_responders
from teachme.generation.glossary import generate_glossary, translate_glossary
from teachme.generation.outline import generate_outline
from teachme.generation.question_bank import generate_question_bank, validate_bank
from teachme.generation.teaching import generate_teaching
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
from tests.generation.test_outline import _corpus
from tests.generation.test_teaching import _structure


def test_generation_responders_drive_every_schema_and_validate():
    llm = FakeLLM({**ingestion_responders(), **default_responders()})
    corpus = _corpus(6)
    outline = generate_outline(llm, "fake-model", "Geo", corpus)
    assert outline.parts and all(p.sections for p in outline.parts)
    assert outline.parts[-1].page_end == 5

    glossary = generate_glossary(llm, "fake-model", "Geo", corpus)
    assert len(glossary.terms) >= 2

    terms = [GlossaryTerm(id=uuid4(), outline_id=uuid4(), slug=t.slug, source_term=t.term, definition=t.definition,
                          pages=tuple(t.pages)) for t in glossary.terms]
    translated = translate_glossary(llm, "fake-model", "he", terms)
    assert {t.slug for t in translated.translations} == {t.slug for t in terms}

    part, sections, _ = _structure()
    teaching = generate_teaching(llm, "fake-model", "Geo", "he", corpus, part, sections, terms,
                                 {t.slug: f"he-{t.slug}" for t in terms})
    assert "{{term:" in teaching.body_markdown and len(teaching.sections) == 2

    bank = generate_question_bank(llm, "fake-model", "Geo", "he", corpus, part, sections, teaching, terms,
                                  {t.slug: f"he-{t.slug}" for t in terms}, count=5)
    assert validate_bank(bank, sections, {t.slug for t in terms}, min_per_section=2) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_fake_responders.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/fake_responders.py`**

```python
from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder
from teachme.domain.models import QuestionKind
from teachme.generation.glossary import GlossaryOut, GlossaryTranslationOut, TermOut, TranslationOut
from teachme.generation.outline import OutlineOut, PartOut, SectionOut
from teachme.generation.question_bank import QuestionBankOut, QuestionOut
from teachme.generation.teaching import SectionContentOut, TeachingOut
from teachme.ports.llm import StructuredRequest

_ALL_PAGES = re.compile(r"all (\d+) pages")
_PAGE_RANGE = re.compile(r"pages (\d+)-(\d+)")
_SECTION = re.compile(r"^SECTION (\d+): (.+?) \(pages (\d+)-(\d+)\)$", re.MULTILINE)
_TERM = re.compile(r"^TERM: ([a-z0-9-]+) \| ([^|]+?) \| (.+)$", re.MULTILINE)
_COUNT = re.compile(r"^COUNT: (\d+)$", re.MULTILINE)


def _user_text(request: StructuredRequest) -> str:
    return "\n".join(p.text or "" for p in request.parts if p.kind == "text")


def _outline(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    if match := _ALL_PAGES.search(text):
        first, last = 0, int(match.group(1)) - 1
    else:
        rng = _PAGE_RANGE.search(text)
        first, last = int(rng.group(1)), int(rng.group(2))
    parts = []
    start = first
    while start <= last:
        end = min(start + 2, last)
        mid = (start + end) // 2
        sections = [SectionOut(title=f"Section {start}", page_start=start, page_end=mid)]
        if mid < end:
            sections.append(SectionOut(title=f"Section {mid + 1}", page_start=mid + 1, page_end=end))
        parts.append(PartOut(title=f"Part {start}-{end}", page_start=start, page_end=end, sections=sections))
        start = end + 1
    return OutlineOut(parts=parts)


def _glossary(request: StructuredRequest) -> BaseModel:
    total = int(_ALL_PAGES.search(_user_text(request)).group(1))
    return GlossaryOut(terms=[
        TermOut(slug="biosphere", term="biosfera", definition="Fake definition one.", pages=[0]),
        TermOut(slug="atmosphere", term="atmosfera", definition="Fake definition two.", pages=[min(1, total - 1)]),
    ])


def _translate(request: StructuredRequest) -> BaseModel:
    slugs = [m.group(1) for m in _TERM.finditer(_user_text(request))]
    return GlossaryTranslationOut(translations=[TranslationOut(slug=s, term=f"tr-{s}") for s in slugs])


def _teaching(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    sections = [(int(m.group(1)), m.group(2)) for m in _SECTION.finditer(text)]
    slugs = [m.group(1) for m in _TERM.finditer(text)]
    placeholder = f"{{{{term:{slugs[0]}|fake-words}}}}" if slugs else ""
    body = f"# Fake teaching\n\n{placeholder} " + "Fake teaching sentence. " * 30
    return TeachingOut(
        title="Fake part title", body_markdown=body, key_points=["point 1", "point 2", "point 3"],
        sections=[SectionContentOut(position=pos, title=f"Fake {title}", summary="Fake summary.") for pos, title in sections],
    )


def _questions(request: StructuredRequest) -> BaseModel:
    text = _user_text(request)
    positions = [int(m.group(1)) for m in _SECTION.finditer(text)]
    count = int(_COUNT.search(text).group(1))
    slugs = [m.group(1) for m in _TERM.finditer(text)]
    placeholder = f" {{{{term:{slugs[0]}|fake-words}}}}" if slugs else ""
    questions: list[QuestionOut] = []
    while len(questions) < max(count, 2 * len(positions)):
        for pos in positions:
            questions.append(QuestionOut(
                section_position=pos, kind=QuestionKind.FREE_TEXT, prompt=f"Fake question {len(questions)}{placeholder}?",
                expected_answer="Fake expected answer.", rubric=["fake point"], key_terms=["fake"], exact_values=[],
            ))
    questions[-1] = QuestionOut(
        section_position=positions[0], kind=QuestionKind.MULTIPLE_CHOICE, prompt="Fake choice question?",
        expected_answer="B", rubric=["fake"], key_terms=[], exact_values=[], choices=["A", "B", "C", "D"], correct_choice=1,
    )
    return QuestionBankOut(questions=questions)


def default_responders() -> dict[type[BaseModel], Responder]:
    return {
        OutlineOut: _outline, GlossaryOut: _glossary, GlossaryTranslationOut: _translate,
        TeachingOut: _teaching, QuestionBankOut: _questions,
    }
```

- [ ] **Step 4: Update `build_llm` in `api/teachme/container.py`** so the fake stack covers both stages:

```python
from teachme.generation.fake_responders import default_responders as generation_responders
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
...
def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM()
    return FakeLLM({**ingestion_responders(), **generation_responders()})
```

(Remove the old single import of `default_responders`.)

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_fake_responders.py api/tests/test_container.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add api/teachme/generation/fake_responders.py api/teachme/container.py api/tests/generation/test_fake_responders.py
git commit -m "feat: fake responders for generation schemas"
```

---

### Task 11: Subject bundle writer

**Files:**
- Create: `api/teachme/generation/bundle.py`
- Test: `api/tests/generation/test_subject_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json
from uuid import uuid4

from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.domain.models import (
    GlossaryTerm,
    Outline,
    Part,
    PartContent,
    ContentStatus,
    Question,
    QuestionKind,
    Section,
)
from teachme.generation.bundle import OutlineDoc, SubjectBundleWriter


def test_writer_lays_out_subject_level_files():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678")
    outline = Outline(id=uuid4(), subject_id=uuid4(), version=2, model="fake-model")
    part = Part(id=uuid4(), outline_id=outline.id, position=0, title="Intro", page_start=0, page_end=3)
    sections = [Section(id=uuid4(), part_id=part.id, position=0, title="What", page_start=0, page_end=3)]
    terms = [GlossaryTerm(id=uuid4(), outline_id=outline.id, slug="biosphere", source_term="biosfera",
                          definition="d", pages=(0,))]

    writer.write_outline(outline, [(part, sections)])
    writer.write_glossary(terms)
    writer.write_translations("he", {"biosphere": "ביוספרה"})
    writer.write_part_content(part, PartContent(part_id=part.id, language="he", title="מבוא", body="{{term:biosphere|x}} body",
                                                key_points=("a",), status=ContentStatus.READY, model="fake-model"))
    writer.write_questions("he", [
        Question(id=uuid4(), section_id=sections[0].id, language="he", kind=QuestionKind.FREE_TEXT, prompt="q",
                 expected_answer="a", rubric=("r",), key_terms=("k",), exact_values=(), position=0)
    ], {sections[0].id: (part.position, sections[0].position)})

    keys = store.list_keys("geo-12345678/")
    assert keys == [
        "geo-12345678/glossary.he.json", "geo-12345678/glossary.json", "geo-12345678/outline.json",
        "geo-12345678/parts/01.he.md", "geo-12345678/questions.he.jsonl",
    ]
    doc = OutlineDoc.model_validate_json(store.get("geo-12345678/outline.json"))
    assert doc.version == 2 and doc.parts[0].sections[0].title == "What"
    md = store.get("geo-12345678/parts/01.he.md").decode()
    assert md.startswith("# מבוא\n") and "{{term:biosphere|x}} body" in md and "- a" in md
    row = json.loads(store.get("geo-12345678/questions.he.jsonl").decode().splitlines()[0])
    assert row["part_position"] == 0 and row["section_position"] == 0 and row["prompt"] == "q"
    assert json.loads(store.get("geo-12345678/glossary.he.json")) == {"biosphere": "ביוספרה"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/generation/test_subject_bundle.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `generation/bundle.py`**

```python
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel

from teachme.domain.models import GlossaryTerm, Outline, Part, PartContent, Question, Section
from teachme.ports.file_store import FileStore


class SectionDoc(BaseModel):
    position: int
    title: str
    page_start: int
    page_end: int


class PartDoc(BaseModel):
    position: int
    title: str
    page_start: int
    page_end: int
    sections: list[SectionDoc]


class OutlineDoc(BaseModel):
    version: int
    model: str
    parts: list[PartDoc]


class QuestionRow(BaseModel):
    part_position: int
    section_position: int
    position: int
    kind: str
    prompt: str
    expected_answer: str
    rubric: list[str]
    key_terms: list[str]
    exact_values: list[str]
    choices: list[str] | None
    correct_choice: int | None


class SubjectBundleWriter:
    """Subject-level digest files next to the per-source bundles: outline.json, glossary.json,
    glossary.<lang>.json, parts/NN.<lang>.md, questions.<lang>.jsonl."""

    def __init__(self, stores: Sequence[FileStore], subject_slug: str) -> None:
        self._stores = list(stores)
        self._slug = subject_slug

    def write_outline(self, outline: Outline, parts: Sequence[tuple[Part, Sequence[Section]]]) -> None:
        doc = OutlineDoc(
            version=outline.version, model=outline.model,
            parts=[
                PartDoc(position=p.position, title=p.title, page_start=p.page_start, page_end=p.page_end,
                        sections=[SectionDoc(position=s.position, title=s.title, page_start=s.page_start,
                                             page_end=s.page_end) for s in sections])
                for p, sections in parts
            ],
        )
        self._write("outline.json", doc.model_dump_json(indent=2).encode(), "application/json")

    def write_glossary(self, terms: Sequence[GlossaryTerm]) -> None:
        payload = json.dumps([t.model_dump(mode="json") for t in terms], ensure_ascii=False, indent=2)
        self._write("glossary.json", payload.encode(), "application/json")

    def write_translations(self, language: str, translations: Mapping[str, str]) -> None:
        payload = json.dumps(dict(sorted(translations.items())), ensure_ascii=False, indent=2)
        self._write(f"glossary.{language}.json", payload.encode(), "application/json")

    def write_part_content(self, part: Part, content: PartContent) -> None:
        points = "\n".join(f"- {p}" for p in content.key_points)
        body = f"# {content.title}\n\n{content.body.strip()}\n\n## Key points\n\n{points}\n"
        self._write(f"parts/{part.position + 1:02d}.{content.language}.md", body.encode(), "text/markdown")

    def write_questions(
        self, language: str, questions: Sequence[Question], positions: Mapping[UUID, tuple[int, int]]
    ) -> None:
        rows = [
            QuestionRow(
                part_position=positions[q.section_id][0], section_position=positions[q.section_id][1],
                position=q.position, kind=q.kind.value, prompt=q.prompt, expected_answer=q.expected_answer,
                rubric=list(q.rubric), key_terms=list(q.key_terms), exact_values=list(q.exact_values),
                choices=list(q.choices) if q.choices else None, correct_choice=q.correct_choice,
            )
            for q in questions
        ]
        data = "".join(r.model_dump_json() + "\n" for r in rows).encode()
        self._write(f"questions.{language}.jsonl", data, "application/x-ndjson")

    def _write(self, relative: str, data: bytes, content_type: str) -> None:
        for store in self._stores:
            store.put(f"{self._slug}/{relative}", data, content_type)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/generation/test_subject_bundle.py`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/generation/bundle.py api/tests/generation/test_subject_bundle.py
git commit -m "feat: subject-level digest bundle writer"
```

---

### Task 12: Tutorial service (generate, status, publish, render)

**Files:**
- Modify: `api/teachme/domain/models.py` (Subject settings fields), `api/teachme/repositories/subjects.py`
- Create: `api/teachme/services/tutorial.py`
- Test: `api/tests/services/test_tutorial_service.py`, `api/tests/repositories/test_subjects_sources.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/repositories/test_subjects_sources.py`:

```python
def test_subject_settings_and_published_version(db):
    repo = SubjectRepository(db)
    subject = repo.create("Bio", ["he"])
    assert subject.pass_threshold == 50 and subject.max_rounds == 3 and subject.questions_per_round == 5
    assert subject.bank_size_per_part == 25 and subject.gloss_frequency == "first"
    assert subject.current_outline_version is None
    repo.set_current_outline_version(subject.id, 3)
    assert repo.get(subject.id).current_outline_version == 3
```

Create `api/tests/services/test_tutorial_service.py`:

```python
from __future__ import annotations

import pytest

from teachme.container import Container
from teachme.domain.models import ContentStatus, SubjectState
from teachme.generation.errors import SubjectNotReady
from teachme.ingestion.bundle import bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from tests.helpers import make_pdf


@pytest.fixture
def container(db, migrated_database, tmp_path):
    settings = Settings(
        _env_file=None, database_url=migrated_database, llm_provider="fake", embeddings_provider="fake",
        reranker_provider="noop", file_store="local", local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest", pages_per_read_batch=3, pages_per_chunk_batch=3,
    )
    c = Container(settings)
    yield c
    c.close()


def _ingested_subject(c, name="Geo", languages=("he", "en"), pages=6):
    subject = c.subject_service.get_or_create(name, list(languages))
    source = c.source_service.register(subject, "ch1.pdf", make_pdf(pages))
    c.pipeline.ingest_source(source.id)
    return c.subjects.get(subject.id)


def test_generate_requires_ready_sources(container):
    subject = container.subject_service.get_or_create("Empty", ["he"])
    with pytest.raises(SubjectNotReady):
        container.tutorial_service.generate(subject)


def test_generate_creates_outline_glossary_content_and_questions_for_every_language(container):
    subject = _ingested_subject(container)
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 1 and report.new_outline
    assert report.failures == []
    languages = {r.language for r in report.results}
    assert languages == {"he", "en"}
    outline = container.outlines.latest(subject.id)
    parts = container.outlines.parts(outline.id)
    assert len(parts) >= 2
    for part in parts:
        for language in ("he", "en"):
            content = container.content.part(part.id, language)
            assert content is not None and content.status == ContentStatus.READY
            assert len(container.questions.for_part(part.id, language)) >= 5
    assert {t.slug for t in container.glossary.terms(outline.id)} == {"biosphere", "atmosphere"}
    assert len(container.glossary.translations(outline.id, "he")) == 2

    slug = bundle_slug(subject.name, subject.id)
    keys = container.bundle_stores[0].list_keys(f"{slug}/")
    assert f"{slug}/outline.json" in keys and f"{slug}/glossary.he.json" in keys
    assert f"{slug}/parts/01.he.md" in keys and f"{slug}/questions.en.jsonl" in keys

    purposes = {row["purpose"] for row in UsageRepository(container.conn).summarize(subject_id=subject.id)}
    assert {"gen.outline", "gen.glossary", "gen.glossary_translate", "gen.teaching", "gen.questions"} <= purposes


def test_status_publish_and_unpublish(container):
    subject = _ingested_subject(container)
    status = container.tutorial_service.status(subject)
    assert status.outline_version is None and not status.publishable
    with pytest.raises(SubjectNotReady):
        container.tutorial_service.publish(subject)

    container.tutorial_service.generate(subject)
    status = container.tutorial_service.status(subject)
    assert status.publishable and all(lang.complete for lang in status.languages)

    published = container.tutorial_service.publish(subject)
    assert published.state == SubjectState.PUBLISHED and published.current_outline_version == 1
    with pytest.raises(SubjectLocked):
        container.tutorial_service.generate(published)

    draft = container.tutorial_service.unpublish(published)
    assert draft.state == SubjectState.DRAFT and draft.current_outline_version == 1


def test_regenerate_creates_new_version_and_content_only_reuses_it(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    report = container.tutorial_service.generate(subject, languages=["he"], content_only=True)
    assert report.outline_version == 1 and not report.new_outline
    assert {r.language for r in report.results} == {"he"}
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 2 and report.new_outline


def test_publish_notifies_version_listeners_only_on_change(container):
    subject = _ingested_subject(container)
    seen = []
    container.tutorial_service.on_version_published(lambda subj, version: seen.append(version))
    container.tutorial_service.generate(subject)
    container.tutorial_service.publish(subject)
    container.tutorial_service.unpublish(container.subjects.get(subject.id))
    container.tutorial_service.publish(container.subjects.get(subject.id))
    assert seen == [1]


def test_rendered_part_resolves_placeholders_with_source_gloss(container):
    subject = _ingested_subject(container)  # fake detects language "en"; teaching in "he" is cross-language
    container.tutorial_service.generate(subject)
    rendered = container.tutorial_service.rendered_part(subject, "he", part_position=0)
    assert "{{term:" not in rendered.body
    assert "fake-words (biosfera)" in rendered.body or "fake-words (atmosfera)" in rendered.body
    assert rendered.title == "Fake part title" and rendered.sections
    same_language = container.tutorial_service.rendered_part(subject, "en", part_position=0)
    assert "(biosfera)" not in same_language.body
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest -q api/tests/services/test_tutorial_service.py api/tests/repositories/test_subjects_sources.py`
Expected: FAIL (`AttributeError` for `tutorial_service`, and the subject settings assertions).

- [ ] **Step 3: Extend `Subject` in `api/teachme/domain/models.py`**

```python
class Subject(Frozen):
    id: UUID
    name: str
    state: SubjectState
    languages: tuple[str, ...]
    created_by: str | None = None
    pass_threshold: int = 50
    max_rounds: int = 3
    questions_per_round: int = 5
    bank_size_per_part: int = 25
    gloss_frequency: str = "first"
    current_outline_version: int | None = None
```

- [ ] **Step 4: Extend `api/teachme/repositories/subjects.py`**

```python
_COLUMNS = (
    "id, name, state, languages, created_by, pass_threshold, max_rounds, questions_per_round,"
    " bank_size_per_part, gloss_frequency, current_outline_version"
)


def _row_to_subject(row: dict) -> Subject:
    return Subject(
        id=row["id"], name=row["name"], state=SubjectState(row["state"]), languages=tuple(row["languages"]),
        created_by=row["created_by"], pass_threshold=row["pass_threshold"], max_rounds=row["max_rounds"],
        questions_per_round=row["questions_per_round"], bank_size_per_part=row["bank_size_per_part"],
        gloss_frequency=row["gloss_frequency"], current_outline_version=row["current_outline_version"],
    )
```

and add the method:

```python
    def set_current_outline_version(self, subject_id: UUID, version: int) -> None:
        self._conn.execute("UPDATE subjects SET current_outline_version = %s WHERE id = %s", (version, subject_id))
```

- [ ] **Step 5: Write `services/tutorial.py`**

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID

import psycopg
from pydantic import BaseModel

from teachme.domain.glossary.render import GlossaryView, render_placeholders
from teachme.domain.models import (
    ContentStatus,
    GlossaryTerm,
    GlossaryTranslation,
    Outline,
    Part,
    PartContent,
    Section,
    SectionContent,
    SourceStatus,
    Subject,
    SubjectState,
)
from teachme.generation.bundle import SubjectBundleWriter
from teachme.generation.corpus import SubjectCorpus, build_corpus
from teachme.generation.errors import GenerationError, SubjectNotReady
from teachme.generation.glossary import generate_glossary, translate_glossary
from teachme.generation.outline import generate_outline
from teachme.generation.question_bank import generate_question_bank, to_questions
from teachme.generation.teaching import TeachingOut, generate_teaching
from teachme.ingestion.bundle import bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMError, LLMProvider
from teachme.repositories.content import ContentRepository
from teachme.repositories.glossary import GlossaryRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings
from teachme.telemetry.usage import usage_context

MIN_QUESTIONS_PER_SECTION = 2
VersionListener = Callable[[Subject, int], None]


class PartLanguageResult(BaseModel):
    part_position: int
    language: str
    content_status: ContentStatus
    questions: int
    error: str | None = None


class GenerationReport(BaseModel):
    subject: str
    outline_version: int
    new_outline: bool
    results: list[PartLanguageResult]

    @property
    def failures(self) -> list[PartLanguageResult]:
        return [r for r in self.results if r.content_status != ContentStatus.READY]


class LanguageStatus(BaseModel):
    language: str
    parts_ready: int
    parts_total: int
    questions: int
    complete: bool


class TutorialStatus(BaseModel):
    subject: str
    state: SubjectState
    outline_version: int | None
    published_version: int | None
    parts: int
    languages: list[LanguageStatus]
    publishable: bool


class GlossaryEntry(BaseModel):
    slug: str
    term: str
    source_term: str
    definition: str


class RenderedPart(BaseModel):
    position: int
    title: str
    body: str
    key_points: tuple[str, ...]
    sections: list[SectionContent]
    glossary: list[GlossaryEntry]


class TutorialService:
    """Generates, versions, publishes and renders a subject's tutorial. The model is called only
    through the generation modules; this class owns ordering, persistence, bundle writes and commits."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        llm: LLMProvider,
        subjects: SubjectRepository,
        sources: SourceRepository,
        pages: PageRepository,
        outlines: OutlineRepository,
        glossary: GlossaryRepository,
        content: ContentRepository,
        questions: QuestionRepository,
        bundle_stores: Sequence[FileStore],
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._llm = llm
        self._subjects = subjects
        self._sources = sources
        self._pages = pages
        self._outlines = outlines
        self._glossary = glossary
        self._content = content
        self._questions = questions
        self._bundle_stores = bundle_stores
        self._listeners: list[VersionListener] = []

    # generation -----------------------------------------------------------------------------
    def corpus(self, subject: Subject) -> SubjectCorpus:
        sources = self._sources.list_by_subject(subject.id)
        if not sources:
            raise SubjectNotReady(f"subject {subject.name!r} has no sources")
        not_ready = [s.filename for s in sources if s.status != SourceStatus.READY]
        if not_ready:
            raise SubjectNotReady(f"sources not ready: {not_ready}")
        return build_corpus(sources, {s.id: self._pages.list(s.id) for s in sources})

    def generate(
        self,
        subject: Subject,
        *,
        languages: Sequence[str] | None = None,
        parts: Sequence[int] | None = None,
        content_only: bool = False,
    ) -> GenerationReport:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before generating")
        chosen_languages = list(languages or subject.languages)
        unknown = [code for code in chosen_languages if code not in subject.languages]
        if unknown:
            raise GenerationError(f"languages not enabled for this subject: {unknown}")
        corpus = self.corpus(subject)
        writer = SubjectBundleWriter(self._bundle_stores, bundle_slug(subject.name, subject.id))
        model = self._settings.model_generation

        with usage_context(subject_id=subject.id):
            outline = self._outlines.latest(subject.id)
            new_outline = not content_only or outline is None
            if new_outline:
                outline = self._create_outline(subject, corpus, model, writer)
            assert outline is not None
            all_parts = self._outlines.parts(outline.id)
            terms = self._glossary.terms(outline.id)
            wanted = [p for p in all_parts if parts is None or p.position in parts]

            results: list[PartLanguageResult] = []
            for language in chosen_languages:
                translations = self._ensure_translations(outline, corpus, language, terms, model, writer)
                for part in wanted:
                    results.append(self._generate_part(subject, corpus, outline, part, language, terms, translations, model, writer))
        return GenerationReport(subject=subject.name, outline_version=outline.version, new_outline=new_outline, results=results)

    def _create_outline(self, subject: Subject, corpus: SubjectCorpus, model: str, writer: SubjectBundleWriter) -> Outline:
        outline_out = generate_outline(self._llm, model, subject.name, corpus)
        outline = self._outlines.create(subject.id, model=model)
        structure: list[tuple[Part, list[Section]]] = []
        for position, part_out in enumerate(outline_out.parts):
            part = self._outlines.add_part(outline.id, position=position, title=part_out.title,
                                           page_start=part_out.page_start, page_end=part_out.page_end)
            sections = [
                self._outlines.add_section(part.id, position=i, title=s.title, page_start=s.page_start, page_end=s.page_end)
                for i, s in enumerate(part_out.sections)
            ]
            structure.append((part, sections))
        glossary_out = generate_glossary(self._llm, model, subject.name, corpus)
        from uuid import uuid4  # local import keeps the module header focused on collaborators

        terms = [
            GlossaryTerm(id=uuid4(), outline_id=outline.id, slug=t.slug, source_term=t.term, definition=t.definition,
                         pages=tuple(t.pages))
            for t in glossary_out.terms
        ]
        self._glossary.replace_terms(outline.id, terms)
        writer.write_outline(outline, structure)
        writer.write_glossary(terms)
        self._conn.commit()
        return outline

    def _ensure_translations(
        self, outline: Outline, corpus: SubjectCorpus, language: str, terms: Sequence[GlossaryTerm], model: str,
        writer: SubjectBundleWriter,
    ) -> dict[str, str]:
        existing = {t.term_id: t.term for t in self._glossary.translations(outline.id, language)}
        if len(existing) == len(terms) and terms:
            return {t.slug: existing[t.id] for t in terms}
        if not terms:
            return {}
        if corpus.language == language:
            mapping = {t.slug: t.source_term for t in terms}
        else:
            out = translate_glossary(self._llm, model, language, terms)
            mapping = {tr.slug: tr.term for tr in out.translations}
        by_slug = {t.slug: t.id for t in terms}
        self._glossary.replace_translations(
            outline.id, language,
            [GlossaryTranslation(term_id=by_slug[slug], language=language, term=term) for slug, term in mapping.items()],
        )
        writer.write_translations(language, mapping)
        self._conn.commit()
        return mapping

    def _generate_part(
        self, subject: Subject, corpus: SubjectCorpus, outline: Outline, part: Part, language: str,
        terms: Sequence[GlossaryTerm], translations: dict[str, str], model: str, writer: SubjectBundleWriter,
    ) -> PartLanguageResult:
        sections = self._outlines.sections(part.id)
        try:
            teaching = generate_teaching(self._llm, model, subject.name, language, corpus, part, sections, terms, translations)
            content = PartContent(part_id=part.id, language=language, title=teaching.title, body=teaching.body_markdown,
                                  key_points=tuple(teaching.key_points), status=ContentStatus.READY, model=model)
            self._content.upsert_part(content)
            by_position = {s.position: s.id for s in sections}
            self._content.upsert_sections([
                SectionContent(section_id=by_position[sc.position], language=language, title=sc.title, summary=sc.summary)
                for sc in teaching.sections
            ])
            writer.write_part_content(part, content)
            questions = self._generate_questions(subject, corpus, outline, part, sections, language, teaching, terms, translations, model, writer)
            self._conn.commit()
            return PartLanguageResult(part_position=part.position, language=language, content_status=ContentStatus.READY,
                                      questions=len(questions))
        except (GenerationError, LLMError) as exc:
            self._content.upsert_part(PartContent(part_id=part.id, language=language, title=part.title, body="",
                                                  key_points=(), status=ContentStatus.FAILED, model=model, error=str(exc)))
            self._conn.commit()
            return PartLanguageResult(part_position=part.position, language=language, content_status=ContentStatus.FAILED,
                                      questions=0, error=str(exc))

    def _generate_questions(
        self, subject: Subject, corpus: SubjectCorpus, outline: Outline, part: Part, sections: Sequence[Section],
        language: str, teaching: TeachingOut, terms: Sequence[GlossaryTerm], translations: dict[str, str], model: str,
        writer: SubjectBundleWriter,
    ):
        bank = generate_question_bank(
            self._llm, model, subject.name, language, corpus, part, sections, teaching, terms, translations,
            count=subject.bank_size_per_part, min_per_section=MIN_QUESTIONS_PER_SECTION,
        )
        source_terms = {t.slug: t.source_term for t in terms}
        questions = to_questions(bank, sections, language, source_terms, translations)
        self._questions.replace_for_part(part.id, language, questions)
        positions = {s.id: (part.position, s.position) for s in sections}
        all_for_language = []
        for other in self._outlines.parts(outline.id):
            other_sections = self._outlines.sections(other.id)
            positions.update({s.id: (other.position, s.position) for s in other_sections})
            all_for_language.extend(self._questions.for_part(other.id, language))
        writer.write_questions(language, all_for_language, positions)
        return questions

    # status and publishing ------------------------------------------------------------------
    def status(self, subject: Subject) -> TutorialStatus:
        outline = self._outlines.latest(subject.id)
        if outline is None:
            return TutorialStatus(subject=subject.name, state=subject.state, outline_version=None,
                                  published_version=subject.current_outline_version, parts=0, languages=[], publishable=False)
        parts = self._outlines.parts(outline.id)
        ready = self._content.languages_ready(outline.id)
        languages: list[LanguageStatus] = []
        for language in subject.languages:
            counts = [self._questions.count_by_section(p.id, language) for p in parts]
            total_questions = sum(sum(c.values()) for c in counts)
            enough = all(
                all(c.get(s.id, 0) >= MIN_QUESTIONS_PER_SECTION for s in self._outlines.sections(p.id))
                for p, c in zip(parts, counts, strict=True)
            )
            parts_ready = ready.get(language, 0)
            languages.append(LanguageStatus(language=language, parts_ready=parts_ready, parts_total=len(parts),
                                            questions=total_questions, complete=parts_ready == len(parts) and enough))
        return TutorialStatus(
            subject=subject.name, state=subject.state, outline_version=outline.version,
            published_version=subject.current_outline_version, parts=len(parts), languages=languages,
            publishable=bool(parts) and all(lang.complete for lang in languages),
        )

    def on_version_published(self, listener: VersionListener) -> None:
        """Stage 3 registers the progress reset here; called only when the published version changes."""
        self._listeners.append(listener)

    def publish(self, subject: Subject) -> Subject:
        status = self.status(subject)
        if not status.publishable:
            incomplete = [lang.language for lang in status.languages if not lang.complete] or ["no outline"]
            raise SubjectNotReady(f"cannot publish {subject.name!r}: incomplete for {incomplete}")
        assert status.outline_version is not None
        changed = subject.current_outline_version != status.outline_version
        self._subjects.set_current_outline_version(subject.id, status.outline_version)
        self._subjects.set_state(subject.id, SubjectState.PUBLISHED)
        self._conn.commit()
        published = self._subjects.get(subject.id)
        if changed:
            for listener in self._listeners:
                listener(published, status.outline_version)
        return published

    def unpublish(self, subject: Subject) -> Subject:
        self._subjects.set_state(subject.id, SubjectState.DRAFT)
        self._conn.commit()
        return self._subjects.get(subject.id)

    # rendering ------------------------------------------------------------------------------
    def rendered_part(self, subject: Subject, language: str, part_position: int) -> RenderedPart:
        version = subject.current_outline_version
        outline = self._outlines.get_version(subject.id, version) if version else self._outlines.latest(subject.id)
        if outline is None:
            raise SubjectNotReady(f"subject {subject.name!r} has no outline")
        part = next((p for p in self._outlines.parts(outline.id) if p.position == part_position), None)
        if part is None:
            raise SubjectNotReady(f"no part {part_position} in outline version {outline.version}")
        content = self._content.part(part.id, language)
        if content is None or content.status != ContentStatus.READY:
            raise SubjectNotReady(f"part {part_position} has no ready content in {language!r}")
        terms = self._glossary.terms(outline.id)
        translations = {t.term_id: t.term for t in self._glossary.translations(outline.id, language)}
        corpus_language = self._corpus_language(subject)
        view = GlossaryView(source_language=corpus_language, source_terms={t.slug: t.source_term for t in terms})
        body = render_placeholders(content.body, view, target_language=language, frequency=subject.gloss_frequency)  # type: ignore[arg-type]
        return RenderedPart(
            position=part.position, title=content.title, body=body, key_points=content.key_points,
            sections=self._content.sections(part.id, language),
            glossary=[GlossaryEntry(slug=t.slug, term=translations.get(t.id, t.source_term), source_term=t.source_term,
                                    definition=t.definition) for t in terms],
        )

    def _corpus_language(self, subject: Subject) -> str | None:
        from collections import Counter

        languages = Counter(s.detected_language for s in self._sources.list_by_subject(subject.id) if s.detected_language)
        return languages.most_common(1)[0][0] if languages else None
```

Add to `Settings` in `api/teachme/settings.py`:

```python
    model_generation: str = "claude-opus-5"
```

and to `.env.example` under the models block: `MODEL_GENERATION=claude-opus-5`.

- [ ] **Step 6: Wire the container.** In `api/teachme/container.py` add cached properties `outlines`, `glossary`, `content`, `questions` (one per repository, same pattern as `subjects`) and:

```python
    @cached_property
    def tutorial_service(self) -> TutorialService:
        return TutorialService(
            self.conn, self.settings, self.llm, self.subjects, self.sources, self.pages, self.outlines,
            self.glossary, self.content, self.questions, self.bundle_stores,
        )
```

with the imports `from teachme.repositories.outlines import OutlineRepository`, `...glossary import GlossaryRepository`, `...content import ContentRepository`, `...questions import QuestionRepository`, `from teachme.services.tutorial import TutorialService`.

- [ ] **Step 7: Run to verify they pass**

Run: `pytest -q api/tests/services/test_tutorial_service.py api/tests/repositories/test_subjects_sources.py api/tests/test_container.py`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add api/teachme/domain/models.py api/teachme/repositories/subjects.py api/teachme/services/tutorial.py api/teachme/settings.py .env.example api/teachme/container.py api/tests/services/test_tutorial_service.py api/tests/repositories/test_subjects_sources.py
git commit -m "feat: tutorial service with versioned generation, publishing and rendering"
```

---

### Task 13: CLI commands for generation and publishing

**Files:**
- Modify: `api/teachme/cli/main.py`
- Test: `api/tests/cli/test_cli.py` (append)

- [ ] **Step 1: Write the failing test** (append to `api/tests/cli/test_cli.py`)

```python
def test_generate_publish_show_flow(cli):
    app, pdf, tmp_path = cli
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)]).exit_code == 0
    result = runner.invoke(app, ["generate", "--subject", "Geo"])
    assert result.exit_code == 0, result.output
    assert "outline v1" in result.output and "he" in result.output and "ready" in result.output

    result = runner.invoke(app, ["tutorial", "status", "--subject", "Geo"])
    assert result.exit_code == 0 and "publishable: yes" in result.output

    result = runner.invoke(app, ["publish", "--subject", "Geo"])
    assert result.exit_code == 0 and "published" in result.output

    result = runner.invoke(app, ["tutorial", "show", "--subject", "Geo", "--language", "he", "--part", "0"])
    assert result.exit_code == 0 and "Fake part title" in result.output and "{{term:" not in result.output

    result = runner.invoke(app, ["generate", "--subject", "Geo"])
    assert result.exit_code == 1 and "published" in result.output

    result = runner.invoke(app, ["unpublish", "--subject", "Geo"])
    assert result.exit_code == 0 and "draft" in result.output
    result = runner.invoke(app, ["generate", "--subject", "Geo", "--language", "he", "--part", "0", "--content-only"])
    assert result.exit_code == 0 and "outline v1" in result.output
```

The `cli` fixture creates the subject with the default languages `he,en,pt`. Generation for three languages with the fake LLM is fast.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/cli/test_cli.py -k generate`
Expected: FAIL with `exit_code == 2` (unknown command)

- [ ] **Step 3: Add the commands to `api/teachme/cli/main.py`**

Add `tutorial_app = typer.Typer(no_args_is_help=True, help="Inspect the generated tutorial")` and `app.add_typer(tutorial_app, name="tutorial")` next to the other sub-apps, then:

```python
from teachme.generation.errors import GenerationError
from teachme.ingestion.errors import SubjectLocked


@app.command()
def generate(
    subject: str = typer.Option(..., "--subject", "-s"),
    language: list[str] = typer.Option(None, "--language", "-l", help="Repeatable; default: all enabled"),
    part: list[int] = typer.Option(None, "--part", "-p", help="Repeatable part positions; default: all"),
    content_only: bool = typer.Option(False, "--content-only", help="Keep the current outline and glossary"),
) -> None:
    """Generate outline, glossary, teaching text and question bank for a subject."""
    c = build_container()
    c.check_ready()
    subj = c.subject_service.require(subject)
    try:
        report = c.tutorial_service.generate(
            subj, languages=language or None, parts=part or None, content_only=content_only
        )
    except (GenerationError, SubjectLocked) as exc:
        typer.echo(f"generate failed: {exc}", err=True)
        c.close()
        raise typer.Exit(code=1) from None
    typer.echo(f"{subj.name}: outline v{report.outline_version}{' (new)' if report.new_outline else ''}")
    for r in report.results:
        line = f"  part {r.part_position} [{r.language}]: {r.content_status.value}, {r.questions} questions"
        typer.echo(line + (f"  error: {r.error}" if r.error else ""))
    c.close()
    if report.failures:
        raise typer.Exit(code=1)


@app.command()
def publish(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    """Lock sources and make the subject visible to students. Requires complete content in every language."""
    c = build_container()
    subj = c.subject_service.require(subject)
    try:
        published = c.tutorial_service.publish(subj)
    except GenerationError as exc:
        typer.echo(f"publish failed: {exc}", err=True)
        c.close()
        raise typer.Exit(code=1) from None
    typer.echo(f"{published.name}: published outline v{published.current_outline_version}")
    c.close()


@app.command()
def unpublish(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    c = build_container()
    draft = c.tutorial_service.unpublish(c.subject_service.require(subject))
    typer.echo(f"{draft.name}: {draft.state.value}")
    c.close()


@tutorial_app.command("status")
def tutorial_status(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    c = build_container()
    status = c.tutorial_service.status(c.subject_service.require(subject))
    typer.echo(f"{status.subject}: {status.state.value}, outline v{status.outline_version}, published v{status.published_version}, {status.parts} parts")
    for lang in status.languages:
        typer.echo(f"  {lang.language}: {lang.parts_ready}/{lang.parts_total} parts ready, {lang.questions} questions, complete: {'yes' if lang.complete else 'no'}")
    typer.echo(f"publishable: {'yes' if status.publishable else 'no'}")
    c.close()


@tutorial_app.command("show")
def tutorial_show(
    subject: str = typer.Option(..., "--subject", "-s"),
    language: str = typer.Option(..., "--language", "-l"),
    part: int = typer.Option(0, "--part", "-p"),
) -> None:
    """Print a part's rendered teaching text as a student would receive it."""
    c = build_container()
    try:
        rendered = c.tutorial_service.rendered_part(c.subject_service.require(subject), language, part)
    except GenerationError as exc:
        typer.echo(str(exc), err=True)
        c.close()
        raise typer.Exit(code=1) from None
    typer.echo(f"# {rendered.title}\n")
    typer.echo(rendered.body)
    typer.echo("\n## Key points")
    for point in rendered.key_points:
        typer.echo(f"- {point}")
    c.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/cli/test_cli.py`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add api/teachme/cli/main.py api/tests/cli/test_cli.py
git commit -m "feat: generate, publish, unpublish and tutorial commands"
```

---

### Task 14: Documentation, full verification, merge

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Document the operator flow.** Append to the README quick start block:

```bash
teachme generate --subject "History ch. 3"            # outline, glossary, teaching text, questions, all languages
teachme tutorial status --subject "History ch. 3"
teachme tutorial show --subject "History ch. 3" --language he --part 0
teachme publish --subject "History ch. 3"             # locks sources, students can see it
```

And in `CLAUDE.md` replace the stage line with: `- Stages 1 and 2 (ingestion, tutorial generation) are complete. Run \`teachme --help\`.`

- [ ] **Step 2: Lint and run everything**

Run: `ruff check api && ruff format --check api && TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5433/teachme_test pytest -q`
Expected: no ruff errors; all tests pass, only live and Vercel Blob cases skipped.

- [ ] **Step 3: Commit and merge**

```bash
git add README.md CLAUDE.md
git commit -m "docs: stage 2 operator commands"
git checkout main && git merge --ff-only stage-2-generation && git push origin main
```

---

## Self-review against the spec

- Section 6 steps: outline (Task 6, with the per-source merge path), glossary and per-language translation with same-language shortcut (Tasks 7, 12), teaching text with placeholders, key points and section summaries (Task 8), question bank with rubric, key terms incl. source forms, exact values, 4:1 ratio enforced softly and at least one multiple choice (Task 9), validation with one retry (Task 5), versions and publish switching (Task 12), review surface in the bundle (Task 11) and `tutorial show` (Task 13).
- Section 4 tables for tutorial structure and content: Task 1.
- Cached prompt prefix so all languages in one run share the corpus: Task 3.
- Placeholder rendering rules and gloss frequency setting: Task 4, wired in Task 12 through `subject.gloss_frequency`.
- Deferred to stage 3 by design: `reexplain` prompt and module, the progress reset listener (hook provided in Task 12), retrieval tool for the grader.
