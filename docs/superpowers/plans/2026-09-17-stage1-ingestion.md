# Stage 1: Ingestion Library and CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend foundation and the ingestion pipeline of teach-me so an operator can run `teachme ingest --subject NAME file.pdf` and end up with pages, figures, contextualized chunks, embeddings and a portable digest bundle in a hosted Postgres and a file store, with every LLM call costed.

**Architecture:** Ports-and-adapters Python package `teachme` under `api/`. Routes -> services -> domain + ports; adapters implement ports; one composition root (`container.py`) wires adapters from typed settings. Domain modules do no I/O. Every vendor SDK is imported only inside `adapters/`. The pipeline is a resumable state machine over the `sources.status` column and writes a Markdown/JSON digest bundle before touching the database.

**Tech Stack:** Python 3.12, uv, FastAPI (health only in this stage), Anthropic SDK 1.x (`messages.stream` + `output_format`), Voyage AI (`voyage-4`, `rerank-2.5`), Postgres 17 + pgvector via psycopg 3, pypdf, typer, tenacity, boto3 + moto, `vercel` Python package for Blob, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-17-teach-me-design.md` sections 3, 4, 5 and 9. Read section 3.2 (module layout) before starting.

---

## Conventions for every task

- Work in `/home/frtlx/liorkoren77/teach-me`. Activate the venv: `source .venv/bin/activate` (created in Task 1).
- Run tests with `pytest -q`. Database tests need `TEST_DATABASE_URL`; they skip cleanly when it is unset. `docker compose up -d` (Task 1) provides it at `postgresql://teachme:teachme@localhost:5432/teachme_test`.
- Commit after each task with the message given. Always commit as the repo-local identity (already configured: LiorKoren77). Never use the company GitHub account.
- Every Python file starts with `from __future__ import annotations`.
- No vendor SDK import outside `api/teachme/adapters/`. `ruff` enforces line length 110.
- **Pydantic rule.** Anything validated at a boundary or serialized is a pydantic `BaseModel`: settings, LLM output schemas, domain models, digest bundle files, CLI/API payloads. Plain `dataclass` only for internal transport objects that never leave the process (port request/result types, search hits). Pydantic models are constructed with keyword arguments only.

## File structure

```
pyproject.toml                       project metadata, deps, pytest + ruff config
requirements.txt                     compiled pins for Vercel (uv pip compile)
docker-compose.yml                   local Postgres 17 + pgvector
.env.example                         every setting with a comment
api/index.py                         FastAPI app with /api/health (Vercel entry)
api/teachme/__init__.py
api/teachme/settings.py              Settings (pydantic-settings)
api/teachme/container.py             Container: builds adapters, repos, services
api/teachme/ports/{__init__,llm,embeddings,reranker,file_store,job_runner,chunk_search}.py
api/teachme/domain/{__init__,models,languages}.py
api/teachme/domain/text/{__init__,normalize}.py
api/teachme/domain/retrieval/{__init__,fusion}.py
api/teachme/adapters/llm/{__init__,anthropic,fake}.py
api/teachme/adapters/embeddings/{__init__,voyage,fake}.py
api/teachme/adapters/reranker/{__init__,voyage,noop}.py
api/teachme/adapters/file_store/{__init__,local,memory,s3,vercel_blob}.py
api/teachme/adapters/job_runner/{__init__,inprocess,sqs}.py
api/teachme/adapters/chunk_search/{__init__,memory,pgvector}.py
api/teachme/adapters/db/{__init__,engine,migrate}.py
api/teachme/adapters/db/migrations/0001_initial.sql
api/teachme/telemetry/{__init__,prices,usage,recording}.py
api/teachme/repositories/{__init__,subjects,sources,pages,figures,jobs,usage}.py
api/teachme/retrieval/{__init__,hybrid}.py
api/teachme/ingestion/{__init__,prompts,bundle,pdf_pages,read_pages,extract,detect_language,contextualize,index,estimate,pipeline}.py
api/teachme/ingestion/prompts/{read_pages,detect_language,contextualize}.md
api/teachme/services/{__init__,subjects,sources,usage,export_import}.py
api/teachme/cli/{__init__,main}.py
api/tests/conftest.py
api/tests/helpers.py                 make_pdf(n_pages) and shared builders
api/tests/... one test file per module (named in each task)
```

---

## Phase A: Foundation

### Task 1: Python project, venv, Docker Postgres

**Files:**
- Create: `pyproject.toml`, `docker-compose.yml`, `.env.example`, `api/teachme/__init__.py`, `api/tests/__init__.py`, `api/tests/helpers.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "teach-me"
version = "0.1.0"
description = "Textbook-to-tutorial tutor backend"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "anthropic>=1.5",
  "voyageai>=0.3",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "psycopg[binary]>=3.2",
  "pgvector>=0.3",
  "pypdf>=5.0",
  "typer>=0.12",
  "tenacity>=9.0",
  "boto3>=1.35",
  "vercel>=0.11",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "moto[s3,sqs]>=5",
  "ruff>=0.6",
  "uvicorn>=0.30",
]

[project.scripts]
teachme = "teachme.cli.main:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "api"}

[tool.setuptools.packages.find]
where = ["api"]
include = ["teachme*"]

[tool.pytest.ini_options]
testpaths = ["api/tests"]
pythonpath = ["api"]
addopts = "-ra"

[tool.ruff]
line-length = 110
target-version = "py312"
src = ["api"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: teachme
      POSTGRES_PASSWORD: teachme
      POSTGRES_DB: teachme
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/initdb:/docker-entrypoint-initdb.d:ro
volumes:
  pgdata:
```

Create `docker/initdb/01-test-db.sql`:

```sql
CREATE DATABASE teachme_test;
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Database (local docker default). Vercel injects the hosted URL as DATABASE_URL.
DATABASE_URL=postgresql://teachme:teachme@localhost:5432/teachme
TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5432/teachme_test

# Adapters. Values: anthropic|fake, voyage|fake, voyage|noop, local|vercel_blob|s3, inprocess|sqs
LLM_PROVIDER=anthropic
EMBEDDINGS_PROVIDER=voyage
RERANKER_PROVIDER=voyage
FILE_STORE=local
JOB_RUNNER=inprocess

# Provider credentials (never commit real values)
ANTHROPIC_API_KEY=
VOYAGE_API_KEY=
BLOB_READ_WRITE_TOKEN=
AWS_REGION=eu-central-1
S3_BUCKET=
SQS_QUEUE_URL=

# Models per call site
MODEL_READ_PAGES=claude-opus-5
MODEL_DETECT_LANGUAGE=claude-opus-5
MODEL_CONTEXTUALIZE=claude-opus-5
EMBEDDING_MODEL=voyage-4
RERANK_MODEL=rerank-2.5

# Paths for the local file store and local digest bundles
LOCAL_FILES_DIR=data/files
DIGEST_DIR=digest
WRITE_LOCAL_BUNDLE=true

# Limits. Lists are JSON.
ENABLED_LANGUAGES=["he","en","pt"]
MAX_PAGES_PER_SOURCE=400
PAGES_PER_READ_BATCH=6
PAGES_PER_CHUNK_BATCH=6
# Optional narrowing of accepted upload types, JSON list, e.g. ["application/pdf"]
# ALLOWED_UPLOAD_TYPES=
```

- [ ] **Step 4: Create package and test helpers**

`api/teachme/__init__.py`:

```python
"""teach-me backend package."""
```

`api/tests/__init__.py`: empty file.

`api/tests/helpers.py`:

```python
from __future__ import annotations

import io

from pypdf import PdfWriter


def make_pdf(n_pages: int) -> bytes:
    """A PDF with n blank A4 pages. Enough for page counting and batch splitting;
    the fake LLM does not read page content."""
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
```

- [ ] **Step 5: Create the venv, install, start Postgres**

Run:
```bash
cd /home/frtlx/liorkoren77/teach-me
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv pip compile pyproject.toml -o requirements.txt
docker compose up -d
sleep 5 && docker compose exec postgres psql -U teachme -d teachme_test -c "select 1"
```
Expected: install succeeds, `requirements.txt` written with pinned versions, psql prints `1`.

- [ ] **Step 6: Smoke test the helper**

Create `api/tests/test_helpers.py`:

```python
from __future__ import annotations

from pypdf import PdfReader
import io

from tests.helpers import make_pdf


def test_make_pdf_has_requested_pages():
    reader = PdfReader(io.BytesIO(make_pdf(3)))
    assert len(reader.pages) == 3
```

Run: `pytest -q api/tests/test_helpers.py`
Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.txt docker-compose.yml docker/ .env.example api/
git commit -m "chore: python project skeleton, docker postgres, test helpers"
```

---

### Task 2: Settings

**Files:**
- Create: `api/teachme/settings.py`
- Test: `api/tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from teachme.settings import Settings


def test_defaults_are_local_and_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "anthropic"
    assert settings.file_store == "local"
    assert settings.enabled_languages == ["he", "en", "pt"]
    assert settings.model_read_pages == "claude-opus-5"


def test_reads_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ENABLED_LANGUAGES", '["he"]')
    monkeypatch.setenv("MAX_PAGES_PER_SOURCE", "12")
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "fake"
    assert settings.enabled_languages == ["he"]
    assert settings.max_pages_per_source == 12


def test_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_rejects_unknown_language(monkeypatch):
    monkeypatch.setenv("ENABLED_LANGUAGES", '["he","xx"]')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/test_settings.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'teachme.settings'`

- [ ] **Step 3: Write `api/teachme/settings.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_LANGUAGES = ("he", "en", "pt")


class Settings(BaseSettings):
    """Every configurable value in one place. Nothing else reads os.environ."""

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    database_url: str = "postgresql://teachme:teachme@localhost:5432/teachme"

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    embeddings_provider: Literal["voyage", "fake"] = "voyage"
    reranker_provider: Literal["voyage", "noop"] = "voyage"
    file_store: Literal["local", "vercel_blob", "s3"] = "local"
    job_runner: Literal["inprocess", "sqs"] = "inprocess"

    local_files_dir: Path = Path("data/files")
    digest_dir: Path = Path("digest")
    write_local_bundle: bool = True
    blob_prefix: str = "teach-me"
    aws_region: str = "eu-central-1"
    s3_bucket: str | None = None
    sqs_queue_url: str | None = None

    model_read_pages: str = "claude-opus-5"
    model_detect_language: str = "claude-opus-5"
    model_contextualize: str = "claude-opus-5"
    embedding_model: str = "voyage-4"
    rerank_model: str = "rerank-2.5"

    enabled_languages: list[str] = ["he", "en", "pt"]
    allowed_upload_types: list[str] | None = None
    max_pages_per_source: int = 400
    pages_per_read_batch: int = 6
    pages_per_chunk_batch: int = 6

    @field_validator("enabled_languages")
    @classmethod
    def _known_languages(cls, value: list[str]) -> list[str]:
        unknown = [code for code in value if code not in SUPPORTED_LANGUAGES]
        if unknown:
            raise ValueError(f"unsupported languages: {unknown}; supported: {list(SUPPORTED_LANGUAGES)}")
        return value
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/test_settings.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/settings.py api/tests/test_settings.py
git commit -m "feat: typed settings module"
```

---

### Task 3: Domain models

**Files:**
- Create: `api/teachme/domain/__init__.py`, `api/teachme/domain/models.py`
- Test: `api/tests/domain/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/domain/__init__.py` (empty) and `api/tests/domain/test_models.py`:

```python
from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import Chunk, ChunkRecord, SourceStatus


def test_chunk_content_prepends_context():
    chunk = Chunk(context="From chapter 3 on climate.", text="The biosphere is...", page_start=2, page_end=2)
    assert chunk.content == "From chapter 3 on climate.\n\nThe biosphere is..."


def test_source_status_values_are_stable_strings():
    assert SourceStatus.READY == "ready"
    assert [s.value for s in SourceStatus] == [
        "uploaded", "extracting", "chunking", "indexing", "ready", "failed",
    ]


def test_chunk_record_is_hashable_and_carries_model():
    record = ChunkRecord(
        id=uuid4(), source_id=uuid4(), subject_id=uuid4(),
        chunk=Chunk(context="c", text="t", page_start=0, page_end=0),
        embedding=(0.1, 0.2), embedding_model="voyage-4", tokens=("t",),
    )
    assert record.embedding_model == "voyage-4"
    assert hash(record)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/domain/test_models.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `api/teachme/domain/__init__.py`** (empty) **and `api/teachme/domain/models.py`**

```python
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubjectState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class SourceStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class Frozen(BaseModel):
    """Immutable, hashable value object. All domain records except Source derive from it."""

    model_config = ConfigDict(frozen=True)


class Subject(Frozen):
    id: UUID
    name: str
    state: SubjectState
    languages: tuple[str, ...]
    created_by: str | None = None


class Source(BaseModel):
    """Mutable: status changes as the pipeline advances."""

    id: UUID
    subject_id: UUID
    filename: str
    media_type: str
    file_key: str
    size: int
    status: SourceStatus
    page_count: int | None = None
    vision_pages: int | None = None
    detected_language: str | None = None
    error: str | None = None
    resume_status: SourceStatus | None = None


class Page(Frozen):
    page_index: int = Field(ge=0, description="0-based position in the source")
    printed_number: str | None = Field(default=None, description="the number printed on the page, if any")
    text: str = Field(description="Markdown, figure blocks included")


class Figure(Frozen):
    page_index: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    kind: str
    caption: str
    description: str


class Chunk(Frozen):
    context: str
    text: str
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)

    @property
    def content(self) -> str:
        """What gets embedded and indexed: the situating context first."""
        return f"{self.context}\n\n{self.text}"


class ChunkRecord(Frozen):
    id: UUID
    source_id: UUID
    subject_id: UUID
    chunk: Chunk
    embedding: tuple[float, ...]
    embedding_model: str
    tokens: tuple[str, ...]


class ChunkHit(Frozen):
    chunk_id: UUID
    source_id: UUID
    content: str
    page_start: int
    page_end: int
    score: float
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/domain/test_models.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/domain api/tests/domain
git commit -m "feat: domain models"
```

---

### Task 4: Language registry

**Files:**
- Create: `api/teachme/domain/languages.py`
- Test: `api/tests/domain/test_languages.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.domain.languages import LANGUAGES, get_language


def test_three_languages_registered():
    assert set(LANGUAGES) == {"he", "en", "pt"}


def test_hebrew_is_rtl_with_prefixes():
    he = get_language("he")
    assert he.direction == "rtl"
    assert "ו" in he.prefixes and "ה" in he.prefixes
    assert "של" in he.stopwords


def test_english_and_portuguese_are_ltr():
    assert get_language("en").direction == "ltr"
    assert get_language("pt").direction == "ltr"
    assert "the" in get_language("en").stopwords
    assert "de" in get_language("pt").stopwords


def test_unknown_code_raises():
    with pytest.raises(KeyError):
        get_language("xx")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/domain/test_languages.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `api/teachme/domain/languages.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["ltr", "rtl"]


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    direction: Direction
    stopwords: frozenset[str]
    # Single-letter clitics that attach to the front of Hebrew words (and, the, in, to, from, that, as).
    prefixes: tuple[str, ...] = ()


_HE_STOPWORDS = frozenset(
    "של את על עם הוא היא הם הן זה זאת אני אתה את אנחנו לא כן גם כי אם או אבל יש אין כל מה מי איך למה "
    "כאשר אשר היה היו יהיה להיות בין עד אל מן אחרי לפני כמו יותר פחות רק עוד כבר אז שם פה כאן".split()
)
_EN_STOPWORDS = frozenset(
    "a an the and or but if then of to in on at by for with from as is are was were be been being it its "
    "this that these those there here he she they them his her their we you i not no yes do does did have "
    "has had will would can could should may might which who whom what when where why how than so such".split()
)
_PT_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre e ou mas se "
    "que quem qual quais como quando onde porque não sim é são foi foram ser está estão ele ela eles elas "
    "eu tu nós vós seu sua seus suas meu minha este esta isto esse essa isso aquele aquela aquilo há mais menos já".split()
)

LANGUAGES: dict[str, Language] = {
    "he": Language(
        code="he", name="Hebrew", direction="rtl", stopwords=_HE_STOPWORDS,
        prefixes=("ו", "ה", "ב", "ל", "מ", "ש", "כ"),
    ),
    "en": Language(code="en", name="English", direction="ltr", stopwords=_EN_STOPWORDS),
    "pt": Language(code="pt", name="Portuguese", direction="ltr", stopwords=_PT_STOPWORDS),
}


def get_language(code: str) -> Language:
    """KeyError for unsupported codes; callers validate at the boundary."""
    return LANGUAGES[code]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/domain/test_languages.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/domain/languages.py api/tests/domain/test_languages.py
git commit -m "feat: language registry for he/en/pt"
```

---

### Task 5: Text normalization and tokenization

**Files:**
- Create: `api/teachme/domain/text/__init__.py`, `api/teachme/domain/text/normalize.py`
- Test: `api/tests/domain/test_normalize.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from teachme.domain.text.normalize import normalize, tokenize


def test_normalize_lowercases_and_strips_hebrew_points():
    assert normalize("Ａtmosphere") == "atmosphere"
    assert normalize("בְּרֵאשִׁית") == "בראשית"


def test_tokenize_english_removes_stopwords():
    assert tokenize("The biosphere and the atmosphere", "en") == ["biosphere", "atmosphere"]


def test_tokenize_keeps_numbers_and_short_words():
    assert tokenize("In 1789 the map", "en") == ["1789", "map"]


def test_tokenize_hebrew_strips_one_prefix_from_long_words():
    # והביוספרה -> strip ו -> הביוספרה (one prefix only, deterministic)
    assert tokenize("והביוספרה", "he") == ["הביוספרה"]
    # short words are left alone so real words like "הר" are not mangled
    assert tokenize("הר", "he") == ["הר"]


def test_tokenize_portuguese_keeps_accents():
    assert tokenize("A atmosfera é composta", "pt") == ["atmosfera", "composta"]


def test_tokenize_unknown_language_falls_back_to_no_stopwords():
    assert tokenize("the map", "xx") == ["the", "map"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/domain/test_normalize.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `api/teachme/domain/text/__init__.py`** (empty) **and `normalize.py`**

```python
from __future__ import annotations

import re
import unicodedata

from teachme.domain.languages import LANGUAGES

_HEBREW_POINTS = re.compile(r"[֑-ׇ]")  # niqqud and cantillation marks
_WORD = re.compile(r"\w+", re.UNICODE)
_MIN_LEN_FOR_PREFIX_STRIP = 4


def normalize(text: str) -> str:
    """NFKC fold, lowercase, drop Hebrew vowel points. Keeps letters of every script and digits."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return _HEBREW_POINTS.sub("", folded)


def tokenize(text: str, language_code: str) -> list[str]:
    """Content words for lexical indexing and relevance scoring.

    Shared by the pgvector lexical column and the answer-relevance scorer so both sides
    agree on what a token is. Unknown language codes tokenize without stopword removal.
    """
    language = LANGUAGES.get(language_code)
    stopwords = language.stopwords if language else frozenset()
    prefixes = language.prefixes if language else ()
    tokens: list[str] = []
    for raw in _WORD.findall(normalize(text)):
        if raw in stopwords:
            continue
        token = _strip_prefix(raw, prefixes)
        if token in stopwords:
            continue
        tokens.append(token)
    return tokens


def _strip_prefix(token: str, prefixes: tuple[str, ...]) -> str:
    if len(token) >= _MIN_LEN_FOR_PREFIX_STRIP and token[0] in prefixes:
        return token[1:]
    return token
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/domain/test_normalize.py`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/domain/text api/tests/domain/test_normalize.py
git commit -m "feat: unicode-aware normalizer and tokenizer"
```

---

## Phase B: Ports

### Task 6: LLM, embeddings and reranker ports

**Files:**
- Create: `api/teachme/ports/__init__.py`, `api/teachme/ports/llm.py`, `api/teachme/ports/embeddings.py`, `api/teachme/ports/reranker.py`
- Test: `api/tests/ports/test_llm_types.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/ports/__init__.py` (empty) and `api/tests/ports/test_llm_types.py`:

```python
from __future__ import annotations

from teachme.ports.llm import ContentPart, LLMUsage, StructuredRequest


def test_content_part_constructors():
    text = ContentPart.of_text("hello")
    doc = ContentPart.of_document(b"%PDF", "application/pdf")
    img = ContentPart.of_image(b"\x89PNG", "image/png")
    assert text.kind == "text" and text.text == "hello"
    assert doc.kind == "document" and doc.media_type == "application/pdf" and doc.text is None
    assert img.kind == "image" and img.data == b"\x89PNG"


def test_request_defaults():
    req = StructuredRequest(purpose="test", model="claude-opus-5", system="s", parts=(ContentPart.of_text("x"),))
    assert req.max_tokens == 16000
    assert req.effort == "medium"


def test_usage_totals():
    usage = LLMUsage(input_tokens=10, output_tokens=5, cache_read_tokens=3, cache_write_tokens=2)
    assert usage.total_input == 15
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ports/test_llm_types.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the ports**

`api/teachme/ports/__init__.py`: empty.

`api/teachme/ports/llm.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high"]


class LLMError(Exception):
    """Base for failures the adapter could not resolve."""


class LLMRefused(LLMError):
    """The model declined the request (stop_reason refusal)."""


class LLMOutputTruncated(LLMError):
    """Output hit max_tokens; the caller should split the input or raise the limit."""


class LLMParseError(LLMError):
    """The response did not parse into the requested schema."""


@dataclass(frozen=True)
class LLMCapabilities:
    media_types: frozenset[str]


@dataclass(frozen=True)
class ContentPart:
    kind: Literal["text", "document", "image"]
    text: str | None = None
    data: bytes | None = None
    media_type: str | None = None

    @staticmethod
    def of_text(value: str) -> ContentPart:
        return ContentPart(kind="text", text=value)

    @staticmethod
    def of_document(data: bytes, media_type: str) -> ContentPart:
        return ContentPart(kind="document", data=data, media_type=media_type)

    @staticmethod
    def of_image(data: bytes, media_type: str) -> ContentPart:
        return ContentPart(kind="image", data=data, media_type=media_type)


@dataclass(frozen=True)
class StructuredRequest:
    purpose: str  # telemetry tag, e.g. "ingest.read_pages"
    model: str
    system: str
    parts: tuple[ContentPart, ...]
    max_tokens: int = 16000
    effort: Effort = "medium"


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    output: T
    usage: LLMUsage
    model: str


class LLMProvider(Protocol):
    name: str

    def capabilities(self) -> LLMCapabilities: ...

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]: ...
```

The constructors are named `of_text`, `of_document`, `of_image` because a dataclass field and a staticmethod must not share a name (the method would become the field's default value).

`api/teachme/ports/embeddings.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    tokens: int


class Embedder(Protocol):
    name: str
    model: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult: ...

    def embed_query(self, text: str) -> EmbeddingResult: ...
```

`api/teachme/ports/reranker.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        """Indices into `documents`, best first, at most top_k."""
        ...
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/ports/test_llm_types.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/ports api/tests/ports
git commit -m "feat: llm, embeddings and reranker ports"
```

---

### Task 7: File store, job runner and chunk search ports

**Files:**
- Create: `api/teachme/ports/file_store.py`, `api/teachme/ports/job_runner.py`, `api/teachme/ports/chunk_search.py`

- [ ] **Step 1: Write the ports** (pure Protocols; they are exercised by the contract tests of their adapters in Phase D)

`api/teachme/ports/file_store.py`:

```python
from __future__ import annotations

from typing import Protocol


class FileNotFound(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"no file at key {key!r}")
        self.key = key


class FileStore(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes:
        """Raises FileNotFound."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """Every key starting with prefix, sorted."""
        ...
```

`api/teachme/ports/job_runner.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

JobPayload = dict[str, Any]
JobHandler = Callable[[JobPayload], None]


class UnknownJobKind(Exception):
    pass


class JobRunner(Protocol):
    name: str

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        """Record the job and hand it to the executor. Returns the job id.

        The in-process runner executes synchronously and re-raises handler errors;
        queue-backed runners return after the message is accepted.
        """
        ...
```

`api/teachme/ports/chunk_search.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from teachme.domain.models import ChunkHit, ChunkRecord


class ChunkSearch(Protocol):
    name: str

    def dimension(self) -> int:
        """Vector width the store accepts. The container checks it against the embedder."""
        ...

    def upsert(self, records: Sequence[ChunkRecord]) -> None: ...

    def delete_by_source(self, source_id: UUID) -> None: ...

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]: ...

    def count(self, subject_id: UUID) -> int: ...

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]: ...

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]: ...
```

- [ ] **Step 2: Import check**

Run: `python -c "import teachme.ports.file_store, teachme.ports.job_runner, teachme.ports.chunk_search; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add api/teachme/ports
git commit -m "feat: file store, job runner and chunk search ports"
```

---

### Task 8: Reciprocal rank fusion (domain)

**Files:**
- Create: `api/teachme/domain/retrieval/__init__.py`, `api/teachme/domain/retrieval/fusion.py`
- Test: `api/tests/domain/test_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import ChunkHit
from teachme.domain.retrieval.fusion import reciprocal_rank_fusion


def hit(chunk_id, score=1.0):
    return ChunkHit(chunk_id=chunk_id, source_id=uuid4(), content=str(chunk_id), page_start=0, page_end=0, score=score)


def test_item_in_both_lists_ranks_first():
    a, b, c = uuid4(), uuid4(), uuid4()
    dense = [hit(a), hit(b)]
    lexical = [hit(c), hit(a)]
    fused = reciprocal_rank_fusion([dense, lexical])
    assert [h.chunk_id for h in fused] == [a, c, b] or [h.chunk_id for h in fused][0] == a
    assert fused[0].chunk_id == a


def test_dedupes_and_keeps_first_seen_hit_object():
    a = uuid4()
    first = hit(a, score=0.9)
    fused = reciprocal_rank_fusion([[first], [hit(a, score=0.1)]])
    assert len(fused) == 1 and fused[0] is first


def test_empty_rankings():
    assert reciprocal_rank_fusion([[], []]) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/domain/test_fusion.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `fusion.py`** (and empty `__init__.py`)

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from teachme.domain.models import ChunkHit


def reciprocal_rank_fusion(rankings: Sequence[Sequence[ChunkHit]], k: int = 60) -> list[ChunkHit]:
    """Fuse ranked lists by summing 1/(k+rank). Needs no score calibration, which matters
    because a cosine similarity and a text-search rank are not on comparable scales."""
    scores: dict[UUID, float] = {}
    first_seen: dict[UUID, ChunkHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            first_seen.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [first_seen[chunk_id] for chunk_id in order]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/domain/test_fusion.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/domain/retrieval api/tests/domain/test_fusion.py
git commit -m "feat: reciprocal rank fusion"
```

---

## Phase C: Database and repositories

### Task 9: Connection, migration runner and initial schema

**Files:**
- Create: `api/teachme/adapters/__init__.py`, `api/teachme/adapters/db/__init__.py`, `api/teachme/adapters/db/engine.py`, `api/teachme/adapters/db/migrate.py`, `api/teachme/adapters/db/migrations/0001_initial.sql`
- Create: `api/tests/conftest.py`
- Test: `api/tests/adapters/test_migrate.py`

- [ ] **Step 1: Write `api/tests/conftest.py`** (database fixture shared by every DB test)

```python
from __future__ import annotations

import os

import pytest

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import apply_migrations

TABLES = ["llm_usage", "jobs", "chunks", "source_figures", "source_pages", "sources", "subjects"]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; start docker compose and export it")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    conn = connect(test_database_url)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return test_database_url


@pytest.fixture
def db(migrated_database: str):
    conn = connect(migrated_database)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        conn.commit()
        conn.close()
```

- [ ] **Step 2: Write the failing test** `api/tests/adapters/__init__.py` (empty) and `api/tests/adapters/test_migrate.py`

```python
from __future__ import annotations

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import applied_versions, available_versions, pending_versions


def test_migrations_apply_once_and_are_idempotent(migrated_database):
    conn = connect(migrated_database)
    try:
        assert applied_versions(conn) == available_versions()
        assert pending_versions(conn) == []
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        assert {"subjects", "sources", "source_pages", "source_figures", "chunks", "jobs", "llm_usage"} <= tables
    finally:
        conn.close()


def test_available_versions_are_sorted_filenames():
    versions = available_versions()
    assert versions == sorted(versions)
    assert versions[0] == "0001_initial"
```

- [ ] **Step 3: Run to verify it fails**

Run: `export TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5432/teachme_test && pytest -q api/tests/adapters/test_migrate.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'teachme.adapters'`

- [ ] **Step 4: Write `engine.py`** (plus empty `adapters/__init__.py` and `adapters/db/__init__.py`)

```python
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def connect(database_url: str) -> psycopg.Connection:
    """One connection, dict rows, explicit commits. Vectors travel as text literals
    ('[0.1,0.2]'::vector) so no type registration is needed."""
    return psycopg.connect(database_url, row_factory=dict_row)
```

- [ ] **Step 5: Write `migrate.py`**

```python
from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaOutOfDate(Exception):
    def __init__(self, pending: list[str]) -> None:
        super().__init__(f"database schema is behind; run `teachme migrate` to apply: {pending}")
        self.pending = pending


def available_versions() -> list[str]:
    return sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    conn.commit()
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


def pending_versions(conn: psycopg.Connection) -> list[str]:
    applied = set(applied_versions(conn))
    return [version for version in available_versions() if version not in applied]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every pending migration in filename order, one transaction each."""
    applied_now: list[str] = []
    for version in pending_versions(conn):
        sql = (MIGRATIONS_DIR / f"{version}.sql").read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()
        applied_now.append(version)
    return applied_now


def ensure_schema_current(conn: psycopg.Connection) -> None:
    pending = pending_versions(conn)
    if pending:
        raise SchemaOutOfDate(pending)
```

- [ ] **Step 6: Write `migrations/0001_initial.sql`**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE subjects (
  id                      uuid PRIMARY KEY,
  name                    text NOT NULL UNIQUE,
  state                   text NOT NULL DEFAULT 'draft',
  languages               text[] NOT NULL,
  pass_threshold          int  NOT NULL DEFAULT 50,
  max_rounds              int  NOT NULL DEFAULT 3,
  questions_per_round     int  NOT NULL DEFAULT 5,
  bank_size_per_part      int  NOT NULL DEFAULT 25,
  gloss_frequency         text NOT NULL DEFAULT 'first',
  current_outline_version int,
  created_by              text,
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id                uuid PRIMARY KEY,
  subject_id        uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  filename          text NOT NULL,
  media_type        text NOT NULL,
  file_key          text NOT NULL,
  size              bigint NOT NULL,
  status            text NOT NULL,
  resume_status     text,
  error             text,
  page_count        int,
  vision_pages      int,
  detected_language text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sources_subject_idx ON sources(subject_id);

CREATE TABLE source_pages (
  source_id      uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page_index     int  NOT NULL,
  printed_number text,
  text           text NOT NULL,
  PRIMARY KEY (source_id, page_index)
);

CREATE TABLE source_figures (
  source_id   uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page_index  int  NOT NULL,
  ordinal     int  NOT NULL,
  kind        text NOT NULL,
  caption     text NOT NULL,
  description text NOT NULL,
  PRIMARY KEY (source_id, page_index, ordinal)
);

CREATE TABLE chunks (
  id              uuid PRIMARY KEY,
  source_id       uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  subject_id      uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  context         text NOT NULL,
  text            text NOT NULL,
  page_start      int  NOT NULL,
  page_end        int  NOT NULL,
  embedding       vector(1024) NOT NULL,
  embedding_model text NOT NULL,
  tokens          tsvector NOT NULL
);
CREATE INDEX chunks_subject_idx   ON chunks(subject_id);
CREATE INDEX chunks_source_idx    ON chunks(source_id);
CREATE INDEX chunks_tokens_idx    ON chunks USING gin(tokens);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE jobs (
  id         uuid PRIMARY KEY,
  kind       text NOT NULL,
  payload    jsonb NOT NULL,
  status     text NOT NULL,
  attempts   int  NOT NULL DEFAULT 0,
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
  id                 uuid PRIMARY KEY,
  created_at         timestamptz NOT NULL DEFAULT now(),
  purpose            text NOT NULL,
  provider           text NOT NULL,
  model              text NOT NULL,
  input_tokens       int  NOT NULL,
  output_tokens      int  NOT NULL,
  cache_read_tokens  int  NOT NULL DEFAULT 0,
  cache_write_tokens int  NOT NULL DEFAULT 0,
  cost_usd           numeric(12, 6) NOT NULL,
  latency_ms         int  NOT NULL,
  user_id            text,
  subject_id         uuid,
  source_id          uuid,
  attempt_id         uuid
);
CREATE INDEX llm_usage_subject_idx ON llm_usage(subject_id);
CREATE INDEX llm_usage_source_idx  ON llm_usage(source_id);
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_migrate.py`
Expected: `2 passed`

- [ ] **Step 8: Commit**

```bash
git add api/teachme/adapters api/tests/conftest.py api/tests/adapters
git commit -m "feat: postgres connection, migration runner, initial schema"
```

---

### Task 10: Subject and source repositories

**Files:**
- Create: `api/teachme/repositories/__init__.py`, `api/teachme/repositories/errors.py`, `api/teachme/repositories/subjects.py`, `api/teachme/repositories/sources.py`
- Test: `api/tests/repositories/test_subjects_sources.py`

- [ ] **Step 1: Write the failing test** (`api/tests/repositories/__init__.py` empty)

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.domain.models import SourceStatus, SubjectState
from teachme.repositories.errors import SourceNotFound, SubjectNotFound
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository


def test_subject_create_get_list(db):
    repo = SubjectRepository(db)
    subject = repo.create("History ch. 3", ["he", "en"], created_by="user_1")
    assert subject.state == SubjectState.DRAFT
    assert subject.languages == ("he", "en")
    assert repo.get(subject.id) == subject
    assert repo.get_by_name("History ch. 3") == subject
    assert repo.get_by_name("nope") is None
    assert [s.name for s in repo.list()] == ["History ch. 3"]


def test_subject_set_state_and_missing(db):
    repo = SubjectRepository(db)
    subject = repo.create("Geo", ["pt"])
    repo.set_state(subject.id, SubjectState.PUBLISHED)
    assert repo.get(subject.id).state == SubjectState.PUBLISHED
    with pytest.raises(SubjectNotFound):
        repo.get(uuid4())


def test_source_lifecycle(db):
    subject = SubjectRepository(db).create("Physics", ["en"])
    repo = SourceRepository(db)
    source = repo.create(subject.id, "ch1.pdf", "application/pdf", "sources/x/ch1.pdf", 1234)
    assert source.status == SourceStatus.UPLOADED
    repo.set_status(source.id, SourceStatus.EXTRACTING)
    repo.set_extraction_result(source.id, page_count=12, vision_pages=12, detected_language="pt")
    repo.set_status(source.id, SourceStatus.FAILED, error="boom", resume_status=SourceStatus.CHUNKING)
    loaded = repo.get(source.id)
    assert loaded.page_count == 12 and loaded.detected_language == "pt"
    assert loaded.status == SourceStatus.FAILED and loaded.resume_status == SourceStatus.CHUNKING
    assert loaded.error == "boom"
    repo.set_status(source.id, SourceStatus.READY)
    assert repo.get(source.id).error is None and repo.get(source.id).resume_status is None
    assert [s.id for s in repo.list_by_subject(subject.id)] == [source.id]
    repo.delete(source.id)
    with pytest.raises(SourceNotFound):
        repo.get(source.id)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/repositories/test_subjects_sources.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `repositories/__init__.py`** (empty) **and `errors.py`**

```python
from __future__ import annotations

from uuid import UUID


class NotFound(Exception):
    entity = "entity"

    def __init__(self, identifier: UUID | str) -> None:
        super().__init__(f"{self.entity} {identifier} not found")
        self.identifier = identifier


class SubjectNotFound(NotFound):
    entity = "subject"


class SourceNotFound(NotFound):
    entity = "source"


class JobNotFound(NotFound):
    entity = "job"
```

- [ ] **Step 4: Write `subjects.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Subject, SubjectState
from teachme.repositories.errors import SubjectNotFound

_COLUMNS = "id, name, state, languages, created_by"


def _row_to_subject(row: dict) -> Subject:
    return Subject(
        id=row["id"], name=row["name"], state=SubjectState(row["state"]),
        languages=tuple(row["languages"]), created_by=row["created_by"],
    )


class SubjectRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, name: str, languages: Sequence[str], created_by: str | None = None) -> Subject:
        subject_id = uuid4()
        self._conn.execute(
            "INSERT INTO subjects (id, name, languages, created_by) VALUES (%s, %s, %s, %s)",
            (subject_id, name, list(languages), created_by),
        )
        return self.get(subject_id)

    def get(self, subject_id: UUID) -> Subject:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects WHERE id = %s", (subject_id,)).fetchone()
        if row is None:
            raise SubjectNotFound(subject_id)
        return _row_to_subject(row)

    def get_by_name(self, name: str) -> Subject | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects WHERE name = %s", (name,)).fetchone()
        return _row_to_subject(row) if row else None

    def list(self) -> list[Subject]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM subjects ORDER BY name").fetchall()
        return [_row_to_subject(row) for row in rows]

    def set_state(self, subject_id: UUID, state: SubjectState) -> None:
        self._conn.execute("UPDATE subjects SET state = %s WHERE id = %s", (state.value, subject_id))
```

- [ ] **Step 5: Write `sources.py`**

```python
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Source, SourceStatus
from teachme.repositories.errors import SourceNotFound

_COLUMNS = (
    "id, subject_id, filename, media_type, file_key, size, status, resume_status, error, "
    "page_count, vision_pages, detected_language"
)


def _row_to_source(row: dict) -> Source:
    return Source(
        id=row["id"], subject_id=row["subject_id"], filename=row["filename"], media_type=row["media_type"],
        file_key=row["file_key"], size=row["size"], status=SourceStatus(row["status"]),
        resume_status=SourceStatus(row["resume_status"]) if row["resume_status"] else None,
        error=row["error"], page_count=row["page_count"], vision_pages=row["vision_pages"],
        detected_language=row["detected_language"],
    )


class SourceRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, subject_id: UUID, filename: str, media_type: str, file_key: str, size: int) -> Source:
        source_id = uuid4()
        self._conn.execute(
            "INSERT INTO sources (id, subject_id, filename, media_type, file_key, size, status)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (source_id, subject_id, filename, media_type, file_key, size, SourceStatus.UPLOADED.value),
        )
        return self.get(source_id)

    def get(self, source_id: UUID) -> Source:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM sources WHERE id = %s", (source_id,)).fetchone()
        if row is None:
            raise SourceNotFound(source_id)
        return _row_to_source(row)

    def list_by_subject(self, subject_id: UUID) -> list[Source]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM sources WHERE subject_id = %s ORDER BY created_at, filename", (subject_id,)
        ).fetchall()
        return [_row_to_source(row) for row in rows]

    def set_status(
        self,
        source_id: UUID,
        status: SourceStatus,
        *,
        error: str | None = None,
        resume_status: SourceStatus | None = None,
    ) -> None:
        """A non-failed status clears error and resume_status; FAILED records both."""
        self._conn.execute(
            "UPDATE sources SET status = %s, error = %s, resume_status = %s, updated_at = now() WHERE id = %s",
            (status.value, error, resume_status.value if resume_status else None, source_id),
        )

    def set_extraction_result(
        self, source_id: UUID, *, page_count: int, vision_pages: int, detected_language: str | None
    ) -> None:
        self._conn.execute(
            "UPDATE sources SET page_count = %s, vision_pages = %s, detected_language = %s, updated_at = now()"
            " WHERE id = %s",
            (page_count, vision_pages, detected_language, source_id),
        )

    def delete(self, source_id: UUID) -> None:
        self._conn.execute("DELETE FROM sources WHERE id = %s", (source_id,))
```

- [ ] **Step 6: Run to verify it passes**

Run: `pytest -q api/tests/repositories/test_subjects_sources.py`
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add api/teachme/repositories api/tests/repositories
git commit -m "feat: subject and source repositories"
```

---

### Task 11: Page, figure, job and usage repositories

**Files:**
- Create: `api/teachme/repositories/pages.py`, `api/teachme/repositories/figures.py`, `api/teachme/repositories/jobs.py`, `api/teachme/repositories/usage.py`
- Test: `api/tests/repositories/test_pages_figures_jobs_usage.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.domain.models import Figure, Page
from teachme.repositories.figures import FigureRepository
from teachme.repositories.jobs import JobRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository, UsageRow


def _source(db):
    subject = SubjectRepository(db).create(f"S-{uuid4()}", ["en"])
    return subject, SourceRepository(db).create(subject.id, "a.pdf", "application/pdf", "k", 1)


def test_pages_replace_and_list_in_order(db):
    _, source = _source(db)
    repo = PageRepository(db)
    repo.replace(source.id, [
        Page(page_index=1, printed_number="2", text="second"),
        Page(page_index=0, printed_number="1", text="first"),
    ])
    assert [p.text for p in repo.list(source.id)] == ["first", "second"]
    repo.replace(source.id, [Page(page_index=0, printed_number=None, text="only")])
    assert [p.text for p in repo.list(source.id)] == ["only"]


def test_figures_replace_and_list(db):
    _, source = _source(db)
    repo = FigureRepository(db)
    repo.replace(source.id, [
        Figure(page_index=3, ordinal=0, kind="map", caption="Earth 1850", description="A world map"),
        Figure(page_index=1, ordinal=0, kind="photo", caption="", description="A port"),
    ])
    figures = repo.list(source.id)
    assert [(f.page_index, f.kind) for f in figures] == [(1, "photo"), (3, "map")]


def test_jobs_create_status_attempts(db):
    repo = JobRepository(db)
    job_id = repo.create("ingest_source", {"source_id": "abc"})
    job = repo.get(job_id)
    assert job["kind"] == "ingest_source" and job["payload"] == {"source_id": "abc"} and job["status"] == "queued"
    repo.set_status(job_id, "running")
    repo.increment_attempts(job_id)
    repo.set_status(job_id, "failed", error="nope")
    job = repo.get(job_id)
    assert job["status"] == "failed" and job["attempts"] == 1 and job["error"] == "nope"


def test_usage_insert_and_summarize(db):
    subject, source = _source(db)
    repo = UsageRepository(db)
    for tokens in (100, 300):
        repo.insert(UsageRow(
            purpose="ingest.read_pages", provider="anthropic", model="claude-opus-5",
            input_tokens=tokens, output_tokens=10, cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=0.001, latency_ms=5, subject_id=subject.id, source_id=source.id,
        ))
    repo.insert(UsageRow(
        purpose="ingest.embed", provider="voyage", model="voyage-4", input_tokens=50, output_tokens=0,
        cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.0001, latency_ms=1, subject_id=subject.id,
    ))
    summary = repo.summarize(subject_id=subject.id)
    by_purpose = {row["purpose"]: row for row in summary}
    assert by_purpose["ingest.read_pages"]["calls"] == 2
    assert by_purpose["ingest.read_pages"]["input_tokens"] == 400
    assert float(by_purpose["ingest.read_pages"]["cost_usd"]) == 0.002
    assert by_purpose["ingest.embed"]["model"] == "voyage-4"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/repositories/test_pages_figures_jobs_usage.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `pages.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Page


class PageRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace(self, source_id: UUID, pages: Sequence[Page]) -> None:
        self._conn.execute("DELETE FROM source_pages WHERE source_id = %s", (source_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO source_pages (source_id, page_index, printed_number, text) VALUES (%s, %s, %s, %s)",
                [(source_id, p.page_index, p.printed_number, p.text) for p in pages],
            )

    def list(self, source_id: UUID) -> list[Page]:
        rows = self._conn.execute(
            "SELECT page_index, printed_number, text FROM source_pages WHERE source_id = %s ORDER BY page_index",
            (source_id,),
        ).fetchall()
        return [
            Page(page_index=row["page_index"], printed_number=row["printed_number"], text=row["text"]) for row in rows
        ]
```

- [ ] **Step 4: Write `figures.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Figure


class FigureRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace(self, source_id: UUID, figures: Sequence[Figure]) -> None:
        self._conn.execute("DELETE FROM source_figures WHERE source_id = %s", (source_id,))
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO source_figures (source_id, page_index, ordinal, kind, caption, description)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [(source_id, f.page_index, f.ordinal, f.kind, f.caption, f.description) for f in figures],
            )

    def list(self, source_id: UUID) -> list[Figure]:
        rows = self._conn.execute(
            "SELECT page_index, ordinal, kind, caption, description FROM source_figures"
            " WHERE source_id = %s ORDER BY page_index, ordinal",
            (source_id,),
        ).fetchall()
        return [
            Figure(
                page_index=row["page_index"], ordinal=row["ordinal"], kind=row["kind"],
                caption=row["caption"], description=row["description"],
            )
            for row in rows
        ]
```

- [ ] **Step 5: Write `jobs.py`**

```python
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from teachme.repositories.errors import JobNotFound


class JobRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, kind: str, payload: dict[str, Any]) -> UUID:
        job_id = uuid4()
        self._conn.execute(
            "INSERT INTO jobs (id, kind, payload, status) VALUES (%s, %s, %s, 'queued')",
            (job_id, kind, Jsonb(payload)),
        )
        return job_id

    def get(self, job_id: UUID) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT id, kind, payload, status, attempts, error FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return dict(row)

    def set_status(self, job_id: UUID, status: str, *, error: str | None = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = %s, error = %s, updated_at = now() WHERE id = %s", (status, error, job_id)
        )

    def increment_attempts(self, job_id: UUID) -> None:
        self._conn.execute("UPDATE jobs SET attempts = attempts + 1, updated_at = now() WHERE id = %s", (job_id,))
```

- [ ] **Step 6: Write `usage.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True)
class UsageRow:
    purpose: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int
    user_id: str | None = None
    subject_id: UUID | None = None
    source_id: UUID | None = None
    attempt_id: UUID | None = None


class UsageRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def insert(self, row: UsageRow) -> None:
        self._conn.execute(
            "INSERT INTO llm_usage (id, purpose, provider, model, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, cost_usd, latency_ms, user_id, subject_id, source_id, attempt_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(), row.purpose, row.provider, row.model, row.input_tokens, row.output_tokens,
                row.cache_read_tokens, row.cache_write_tokens, row.cost_usd, row.latency_ms,
                row.user_id, row.subject_id, row.source_id, row.attempt_id,
            ),
        )

    def summarize(self, *, subject_id: UUID | None = None) -> list[dict[str, Any]]:
        """Calls, tokens and cost grouped by purpose and model, optionally for one subject."""
        where = "WHERE subject_id = %s" if subject_id else ""
        params = (subject_id,) if subject_id else ()
        rows = self._conn.execute(
            "SELECT purpose, model, count(*) AS calls,"
            " sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,"
            " sum(cache_read_tokens) AS cache_read_tokens, sum(cache_write_tokens) AS cache_write_tokens,"
            " sum(cost_usd) AS cost_usd, avg(latency_ms)::int AS avg_latency_ms"
            f" FROM llm_usage {where} GROUP BY purpose, model ORDER BY purpose, model",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest -q api/tests/repositories/test_pages_figures_jobs_usage.py`
Expected: `4 passed`

- [ ] **Step 8: Commit**

```bash
git add api/teachme/repositories api/tests/repositories
git commit -m "feat: page, figure, job and usage repositories"
```

---

## Phase D: Adapters

### Task 12: Anthropic LLM adapter

**Files:**
- Create: `api/teachme/adapters/llm/__init__.py`, `api/teachme/adapters/llm/anthropic.py`
- Test: `api/tests/adapters/test_anthropic_llm.py`

- [ ] **Step 1: Write the failing test** (uses a stub client, no network)

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.ports.llm import ContentPart, LLMOutputTruncated, LLMRefused, StructuredRequest


class Answer(BaseModel):
    value: int


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _StubClient:
    """Records the kwargs of messages.stream and returns a canned final message."""

    def __init__(self, message):
        self.calls = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._message = message

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self._message)


def _message(stop_reason="end_turn", parsed=Answer(value=7)):
    usage = SimpleNamespace(input_tokens=120, output_tokens=8, cache_read_input_tokens=100, cache_creation_input_tokens=None)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage, model="claude-opus-5")


def _request():
    return StructuredRequest(
        purpose="test", model="claude-opus-5", system="sys",
        parts=(ContentPart.of_document(b"%PDF-1.4", "application/pdf"), ContentPart.of_text("Read it")),
        max_tokens=4000, effort="low",
    )


def test_builds_request_and_returns_parsed_output():
    client = _StubClient(_message())
    llm = AnthropicLLM(client=client)
    result = llm.generate_structured(_request(), Answer)
    assert result.output == Answer(value=7)
    assert result.usage.input_tokens == 120 and result.usage.cache_read_tokens == 100
    assert result.usage.cache_write_tokens == 0 and result.model == "claude-opus-5"
    kwargs = client.calls[0]
    assert kwargs["model"] == "claude-opus-5" and kwargs["max_tokens"] == 4000
    assert kwargs["thinking"] == {"type": "adaptive"} and kwargs["output_config"] == {"effort": "low"}
    assert kwargs["output_format"] is Answer
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert content[0]["source"]["data"] == "JVBERi0xLjQ="
    assert content[1] == {"type": "text", "text": "Read it"}


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMRefused):
        AnthropicLLM(client=_StubClient(_message(stop_reason="refusal"))).generate_structured(_request(), Answer)
    with pytest.raises(LLMOutputTruncated):
        AnthropicLLM(client=_StubClient(_message(stop_reason="max_tokens"))).generate_structured(_request(), Answer)


def test_capabilities_include_pdf_and_images():
    caps = AnthropicLLM(client=_StubClient(_message())).capabilities()
    assert {"application/pdf", "image/png", "image/jpeg", "text/plain", "text/markdown"} <= caps.media_types
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_anthropic_llm.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `adapters/llm/__init__.py`** (empty) **and `anthropic.py`**

```python
from __future__ import annotations

import base64
from typing import Any

from anthropic import Anthropic

from teachme.ports.llm import (
    ContentPart,
    LLMCapabilities,
    LLMOutputTruncated,
    LLMParseError,
    LLMRefused,
    LLMUsage,
    StructuredRequest,
    StructuredResult,
    T,
)

MEDIA_TYPES = frozenset({
    "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain", "text/markdown",
})


class AnthropicLLM:
    """Claude through the official SDK. Always streams so large outputs never hit HTTP timeouts,
    and always requests structured output so callers get a validated pydantic object."""

    name = "anthropic"

    def __init__(self, client: Anthropic | None = None) -> None:
        self._client = client or Anthropic(max_retries=5, timeout=600.0)

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(media_types=MEDIA_TYPES)

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        with self._client.messages.stream(
            model=request.model,
            max_tokens=request.max_tokens,
            system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": request.effort},
            messages=[{"role": "user", "content": [_to_block(part) for part in request.parts]}],
            output_format=schema,
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise LLMRefused(f"{request.purpose}: model refused the request")
        if message.stop_reason == "max_tokens":
            raise LLMOutputTruncated(f"{request.purpose}: output exceeded max_tokens={request.max_tokens}")
        output = message.parsed_output
        if output is None:
            raise LLMParseError(f"{request.purpose}: no parseable {schema.__name__} in response")

        usage = LLMUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
        )
        return StructuredResult(output=output, usage=usage, model=message.model)


def _to_block(part: ContentPart) -> dict[str, Any]:
    if part.kind == "text":
        return {"type": "text", "text": part.text or ""}
    assert part.data is not None and part.media_type is not None
    encoded = base64.standard_b64encode(part.data).decode("ascii")
    source = {"type": "base64", "media_type": part.media_type, "data": encoded}
    return {"type": "document" if part.kind == "document" else "image", "source": source}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_anthropic_llm.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/adapters/llm api/tests/adapters/test_anthropic_llm.py
git commit -m "feat: anthropic llm adapter with structured streaming output"
```

---

### Task 13: Fake LLM adapter (keyless runs and tests)

**Files:**
- Create: `api/teachme/adapters/llm/fake.py`
- Test: `api/tests/adapters/test_fake_llm.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.fake import FakeLLM
from teachme.ports.llm import ContentPart, LLMParseError, StructuredRequest


class Out(BaseModel):
    echo: str


def _req(text):
    return StructuredRequest(purpose="t", model="m", system="s", parts=(ContentPart.of_text(text),))


def test_responder_is_called_with_request_and_calls_are_recorded():
    fake = FakeLLM({Out: lambda req: Out(echo=req.parts[0].text.upper())})
    result = fake.generate_structured(_req("hi"), Out)
    assert result.output.echo == "HI" and result.model == "fake-model"
    assert fake.calls[0].purpose == "t"


def test_missing_responder_is_a_parse_error():
    with pytest.raises(LLMParseError):
        FakeLLM({}).generate_structured(_req("x"), Out)


def test_capabilities_default_to_pdf_and_text():
    assert "application/pdf" in FakeLLM({}).capabilities().media_types
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_fake_llm.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `fake.py`**

```python
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from teachme.ports.llm import (
    LLMCapabilities,
    LLMParseError,
    LLMUsage,
    StructuredRequest,
    StructuredResult,
    T,
)

Responder = Callable[[StructuredRequest], BaseModel]

DEFAULT_MEDIA_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "text/plain", "text/markdown"})


class FakeLLM:
    """Deterministic stand-in: one responder per output schema. Records every request.

    `teachme.ingestion.fake_responders.default_responders()` provides responders for the
    ingestion schemas so the whole pipeline runs without an API key."""

    name = "fake"

    def __init__(
        self,
        responders: dict[type[BaseModel], Responder] | None = None,
        media_types: frozenset[str] = DEFAULT_MEDIA_TYPES,
    ) -> None:
        self._responders = dict(responders or {})
        self._media_types = media_types
        self.calls: list[StructuredRequest] = []

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(media_types=self._media_types)

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        self.calls.append(request)
        responder = self._responders.get(schema)
        if responder is None:
            raise LLMParseError(f"FakeLLM has no responder for {schema.__name__}")
        output = responder(request)
        if not isinstance(output, schema):
            raise LLMParseError(f"responder for {schema.__name__} returned {type(output).__name__}")
        usage = LLMUsage(input_tokens=1000, output_tokens=200)
        return StructuredResult(output=output, usage=usage, model="fake-model")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_fake_llm.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/adapters/llm/fake.py api/tests/adapters/test_fake_llm.py
git commit -m "feat: fake llm adapter"
```

---

### Task 14: Voyage and fake embedders, Voyage and noop rerankers

**Files:**
- Create: `api/teachme/adapters/embeddings/__init__.py`, `api/teachme/adapters/embeddings/voyage.py`, `api/teachme/adapters/embeddings/fake.py`
- Create: `api/teachme/adapters/reranker/__init__.py`, `api/teachme/adapters/reranker/voyage.py`, `api/teachme/adapters/reranker/noop.py`
- Test: `api/tests/adapters/test_embeddings_reranker.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import math
from types import SimpleNamespace

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.embeddings.voyage import VoyageEmbedder
from teachme.adapters.reranker.noop import NoopReranker
from teachme.adapters.reranker.voyage import VoyageReranker


class _VoyageStub:
    def __init__(self):
        self.embed_calls = []

    def embed(self, texts, model, input_type):
        self.embed_calls.append((list(texts), model, input_type))
        return SimpleNamespace(embeddings=[[0.0] * 4 for _ in texts], total_tokens=7 * len(texts))

    def rerank(self, query, documents, model, top_k):
        order = sorted(range(len(documents)), key=lambda i: len(documents[i]), reverse=True)[:top_k]
        return SimpleNamespace(results=[SimpleNamespace(index=i, relevance_score=1.0) for i in order])


def test_fake_embedder_is_deterministic_unit_length():
    emb = FakeEmbedder(dimension=16)
    a = emb.embed_documents(["hello"]).vectors[0]
    b = emb.embed_documents(["hello"]).vectors[0]
    assert a == b and len(a) == 16
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)
    assert emb.embed_query("hello").vectors[0] == a
    assert emb.embed_documents(["x", "y"]).tokens > 0


def test_voyage_embedder_batches_and_sums_tokens():
    stub = _VoyageStub()
    emb = VoyageEmbedder(model="voyage-4", dimension=4, client=stub, batch_size=2)
    result = emb.embed_documents(["a", "b", "c"])
    assert len(result.vectors) == 3 and result.tokens == 21
    assert [len(call[0]) for call in stub.embed_calls] == [2, 1]
    assert stub.embed_calls[0][2] == "document"
    emb.embed_query("q")
    assert stub.embed_calls[-1][2] == "query"


def test_voyage_reranker_returns_indices():
    reranker = VoyageReranker(model="rerank-2.5", client=_VoyageStub())
    assert reranker.rerank("q", ["aa", "a", "aaa"], top_k=2) == [2, 0]


def test_noop_reranker_keeps_order():
    assert NoopReranker().rerank("q", ["a", "b", "c"], top_k=2) == [0, 1]
    assert NoopReranker().rerank("q", [], top_k=2) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_embeddings_reranker.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `embeddings/__init__.py`** (empty), **`embeddings/voyage.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voyageai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from teachme.ports.embeddings import EmbeddingResult

# Names verified against the installed voyageai package; adjust here if a release renames them.
_TRANSIENT = (
    voyageai.error.RateLimitError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
)


class VoyageEmbedder:
    name = "voyage"

    def __init__(self, model: str, dimension: int = 1024, client: Any | None = None, batch_size: int = 128) -> None:
        self.model = model
        self.dimension = dimension
        self._client = client or voyageai.Client()
        self._batch_size = batch_size

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), self._batch_size):
            batch = self._embed(list(texts[start : start + self._batch_size]), "document")
            vectors.extend(batch.vectors)
            tokens += batch.tokens
        return EmbeddingResult(vectors=vectors, tokens=tokens)

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed([text], "query")

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        wait=wait_exponential(multiplier=1, min=5, max=120),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _embed(self, texts: list[str], input_type: str) -> EmbeddingResult:
        response = self._client.embed(texts, model=self.model, input_type=input_type)
        return EmbeddingResult(vectors=[list(v) for v in response.embeddings], tokens=int(response.total_tokens))
```

**`embeddings/fake.py`**

```python
from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from teachme.ports.embeddings import EmbeddingResult


class FakeEmbedder:
    """Deterministic unit vectors derived from a hash of the text. Same text, same vector."""

    name = "fake"

    def __init__(self, dimension: int = 1024, model: str = "fake-embed") -> None:
        self.dimension = dimension
        self.model = model

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[self._vector(t) for t in texts], tokens=sum(max(1, len(t) // 4) for t in texts))

    def embed_query(self, text: str) -> EmbeddingResult:
        return self.embed_documents([text])

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend((b / 127.5) - 1.0 for b in digest)
            counter += 1
        values = values[: self.dimension]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
```

- [ ] **Step 4: Write `reranker/__init__.py`** (empty), **`reranker/voyage.py`**, **`reranker/noop.py`**

```python
# reranker/voyage.py
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voyageai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_TRANSIENT = (
    voyageai.error.RateLimitError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
)


class VoyageReranker:
    name = "voyage"

    def __init__(self, model: str, client: Any | None = None) -> None:
        self.model = model
        self._client = client or voyageai.Client()

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        wait=wait_exponential(multiplier=1, min=5, max=120),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        if not documents:
            return []
        response = self._client.rerank(query=query, documents=list(documents), model=self.model, top_k=top_k)
        return [item.index for item in response.results]
```

```python
# reranker/noop.py
from __future__ import annotations

from collections.abc import Sequence


class NoopReranker:
    """Keeps the fused order. For local runs without a Voyage key."""

    name = "noop"

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        return list(range(min(top_k, len(documents))))
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_embeddings_reranker.py`
Expected: `4 passed`. If the import of `voyageai.error.*` names fails, run `python -c "import voyageai.error as e; print([n for n in dir(e) if n.endswith('Error') or n=='Timeout'])"` and use the printed names.

- [ ] **Step 6: Commit**

```bash
git add api/teachme/adapters/embeddings api/teachme/adapters/reranker api/tests/adapters/test_embeddings_reranker.py
git commit -m "feat: voyage and fake embedders, voyage and noop rerankers"
```

---

### Task 15: File store adapters with a shared contract test

**Files:**
- Create: `api/teachme/adapters/file_store/__init__.py`, `local.py`, `memory.py`, `s3.py`, `vercel_blob.py`
- Test: `api/tests/adapters/test_file_store_contract.py`

- [ ] **Step 1: Write the failing contract test**

```python
from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.s3 import S3FileStore
from teachme.adapters.file_store.vercel_blob import VercelBlobFileStore
from teachme.ports.file_store import FileNotFound


@pytest.fixture(params=["memory", "local", "s3", "vercel_blob"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryFileStore()
    elif request.param == "local":
        yield LocalFileStore(tmp_path / "files")
    elif request.param == "s3":
        with mock_aws():
            client = boto3.client("s3", region_name="eu-central-1")
            client.create_bucket(
                Bucket="teachme-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
            )
            yield S3FileStore(bucket="teachme-test", region="eu-central-1", client=client)
    else:
        if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
            pytest.skip("BLOB_READ_WRITE_TOKEN not set")
        blob = VercelBlobFileStore(prefix=f"teach-me-test/{os.getpid()}")
        yield blob
        for key in blob.list_keys(""):
            blob.delete(key)


def test_put_get_exists(store):
    store.put("a/b.txt", b"hi", "text/plain")
    assert store.get("a/b.txt") == b"hi"
    assert store.exists("a/b.txt")
    assert not store.exists("a/missing.txt")


def test_get_missing_raises(store):
    with pytest.raises(FileNotFound):
        store.get("nope/none.bin")


def test_overwrite_replaces_content(store):
    store.put("k.txt", b"one", "text/plain")
    store.put("k.txt", b"two", "text/plain")
    assert store.get("k.txt") == b"two"


def test_delete_is_idempotent(store):
    store.put("d.txt", b"x", "text/plain")
    store.delete("d.txt")
    store.delete("d.txt")
    assert not store.exists("d.txt")


def test_list_keys_by_prefix_sorted(store):
    store.put("p/2.md", b"2", "text/markdown")
    store.put("p/1.md", b"1", "text/markdown")
    store.put("q/1.md", b"1", "text/markdown")
    assert store.list_keys("p/") == ["p/1.md", "p/2.md"]
    assert store.list_keys("zzz/") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_file_store_contract.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `file_store/__init__.py`** (empty) **and `memory.py`**

```python
from __future__ import annotations

from teachme.ports.file_store import FileNotFound


class InMemoryFileStore:
    name = "memory"

    def __init__(self) -> None:
        self._files: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._files[key] = (bytes(data), content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._files[key][0]
        except KeyError as exc:
            raise FileNotFound(key) from exc

    def exists(self, key: str) -> bool:
        return key in self._files

    def delete(self, key: str) -> None:
        self._files.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._files if k.startswith(prefix))
```

- [ ] **Step 4: Write `local.py`**

```python
from __future__ import annotations

from pathlib import Path

from teachme.ports.file_store import FileNotFound


class LocalFileStore:
    """Keys map to paths under root. Used for development and for the local digest bundle."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root.resolve() not in path.parents and path != self._root.resolve():
            raise ValueError(f"key escapes the store root: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFound(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def list_keys(self, prefix: str) -> list[str]:
        root = self._root.resolve()
        if not root.exists():
            return []
        keys = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
        return sorted(k for k in keys if k.startswith(prefix))
```

- [ ] **Step 5: Write `s3.py`**

```python
from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from teachme.ports.file_store import FileNotFound


class S3FileStore:
    name = "s3"

    def __init__(self, bucket: str, region: str, client: Any | None = None) -> None:
        self._bucket = bucket
        self._client = client or boto3.client("s3", region_name=region)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFound(key) from exc
            raise

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)
```

- [ ] **Step 6: Write `vercel_blob.py`**

```python
from __future__ import annotations

from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError

from teachme.ports.file_store import FileNotFound


class VercelBlobFileStore:
    """Private blobs under a fixed prefix. Token from BLOB_READ_WRITE_TOKEN unless given."""

    name = "vercel_blob"

    def __init__(self, prefix: str, token: str | None = None, client: BlobClient | None = None) -> None:
        self._prefix = prefix.strip("/")
        self._client = client or BlobClient(token=token)

    def _path(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put(self._path(key), data, access="private", content_type=content_type, overwrite=True)

    def get(self, key: str) -> bytes:
        try:
            result = self._client.get(self._path(key), access="private")
        except BlobNotFoundError as exc:
            raise FileNotFound(key) from exc
        if result is None or result.status_code != 200:
            raise FileNotFound(key)
        return bytes(result.content)

    def exists(self, key: str) -> bool:
        try:
            self._client.head(self._path(key))
            return True
        except BlobNotFoundError:
            return False

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._path(key))
        except BlobNotFoundError:
            return

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        cursor = None
        full_prefix = self._path(prefix)
        while True:
            page = self._client.list_objects(prefix=full_prefix, cursor=cursor, limit=1000)
            keys.extend(item.pathname[len(self._prefix) + 1 :] for item in page.blobs)
            if not page.has_more:
                break
            cursor = page.cursor
        return sorted(keys)
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_file_store_contract.py`
Expected: `15 passed, 5 skipped` (the Vercel Blob cases skip without a token). If `vercel.blob.errors` does not export `BlobNotFoundError`, run `python -c "import vercel.blob.errors as e; print(dir(e))"` and use the listed name.

- [ ] **Step 8: Commit**

```bash
git add api/teachme/adapters/file_store api/tests/adapters/test_file_store_contract.py
git commit -m "feat: local, in-memory, s3 and vercel blob file stores with contract test"
```

---

### Task 16: Job runner adapters

**Files:**
- Create: `api/teachme/adapters/job_runner/__init__.py`, `inprocess.py`, `sqs.py`
- Test: `api/tests/adapters/test_job_runners.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from teachme.adapters.job_runner.inprocess import InProcessJobRunner
from teachme.adapters.job_runner.sqs import SqsJobRunner
from teachme.ports.job_runner import UnknownJobKind
from teachme.repositories.jobs import JobRepository


def test_inprocess_runs_handler_synchronously_without_repository():
    seen = []
    runner = InProcessJobRunner({"echo": lambda payload: seen.append(payload)}, jobs=None)
    job_id = runner.enqueue("echo", {"x": 1})
    assert seen == [{"x": 1}] and job_id


def test_inprocess_unknown_kind():
    with pytest.raises(UnknownJobKind):
        InProcessJobRunner({}, jobs=None).enqueue("nope", {})


def test_inprocess_records_status_and_reraises(db):
    jobs = JobRepository(db)

    def boom(payload):
        raise RuntimeError("bad")

    runner = InProcessJobRunner({"ok": lambda p: None, "boom": boom}, jobs=jobs)
    ok_id = runner.enqueue("ok", {})
    assert jobs.get(ok_id)["status"] == "done" and jobs.get(ok_id)["attempts"] == 1
    with pytest.raises(RuntimeError):
        runner.enqueue("boom", {})
    failed = [r for r in db.execute("SELECT status, error FROM jobs WHERE kind = 'boom'").fetchall()]
    assert failed[0]["status"] == "failed" and failed[0]["error"] == "bad"


def test_sqs_sends_message_with_job_id():
    with mock_aws():
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="teachme-test")["QueueUrl"]
        runner = SqsJobRunner(queue_url=queue_url, region="eu-central-1", jobs=None, client=sqs)
        job_id = runner.enqueue("ingest_source", {"source_id": "abc"})
        body = json.loads(sqs.receive_message(QueueUrl=queue_url)["Messages"][0]["Body"])
        assert body == {"job_id": str(job_id), "kind": "ingest_source", "payload": {"source_id": "abc"}}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_job_runners.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `job_runner/__init__.py`** (empty), **`inprocess.py`**

```python
from __future__ import annotations

from uuid import UUID, uuid4

from teachme.ports.job_runner import JobHandler, JobPayload, UnknownJobKind
from teachme.repositories.jobs import JobRepository


class InProcessJobRunner:
    """Runs the handler in the calling thread. Used by the CLI and by tests.
    With a JobRepository it records queued -> running -> done|failed; without one it just runs."""

    name = "inprocess"

    def __init__(self, handlers: dict[str, JobHandler], jobs: JobRepository | None) -> None:
        self._handlers = handlers
        self._jobs = jobs

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        handler = self._handlers.get(kind)
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        if handler is None:
            if self._jobs:
                self._jobs.set_status(job_id, "failed", error=f"unknown job kind {kind!r}")
            raise UnknownJobKind(kind)
        if self._jobs:
            self._jobs.set_status(job_id, "running")
            self._jobs.increment_attempts(job_id)
        try:
            handler(payload)
        except Exception as exc:
            if self._jobs:
                self._jobs.set_status(job_id, "failed", error=str(exc))
            raise
        if self._jobs:
            self._jobs.set_status(job_id, "done")
        return job_id
```

- [ ] **Step 4: Write `sqs.py`**

```python
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import boto3

from teachme.ports.job_runner import JobPayload
from teachme.repositories.jobs import JobRepository


class SqsJobRunner:
    """Enqueue only. A worker that receives messages and calls the handlers is part of the AWS
    move (spec section 9), not of this stage."""

    name = "sqs"

    def __init__(self, queue_url: str, region: str, jobs: JobRepository | None, client: Any | None = None) -> None:
        self._queue_url = queue_url
        self._jobs = jobs
        self._client = client or boto3.client("sqs", region_name=region)

    def enqueue(self, kind: str, payload: JobPayload) -> UUID:
        job_id = self._jobs.create(kind, payload) if self._jobs else uuid4()
        body = json.dumps({"job_id": str(job_id), "kind": kind, "payload": payload})
        self._client.send_message(QueueUrl=self._queue_url, MessageBody=body)
        return job_id
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_job_runners.py`
Expected: `4 passed` (3 if the database is not running; the DB test skips)

- [ ] **Step 6: Commit**

```bash
git add api/teachme/adapters/job_runner api/tests/adapters/test_job_runners.py
git commit -m "feat: in-process and sqs job runners"
```

---

### Task 17: Chunk search adapters (in-memory and pgvector) with a shared contract test

**Files:**
- Create: `api/teachme/adapters/chunk_search/__init__.py`, `memory.py`, `pgvector.py`
- Test: `api/tests/adapters/test_chunk_search_contract.py`

- [ ] **Step 1: Write the failing contract test**

```python
from __future__ import annotations

import math
from uuid import uuid4

import pytest

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.domain.models import Chunk, ChunkRecord
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository

DIM = 1024


def _unit(index: int) -> tuple[float, ...]:
    vec = [0.0] * DIM
    vec[index] = 1.0
    return tuple(vec)


def _mix(a: int, b: int) -> tuple[float, ...]:
    vec = [0.0] * DIM
    vec[a] = vec[b] = 1 / math.sqrt(2)
    return tuple(vec)


@pytest.fixture(params=["memory", "pgvector"])
def search_env(request):
    if request.param == "memory":
        subject_id, source_id, other_source = uuid4(), uuid4(), uuid4()
        yield InMemoryChunkSearch(dimension=DIM), subject_id, source_id, other_source
    else:
        db = request.getfixturevalue("db")
        subject = SubjectRepository(db).create(f"S-{uuid4()}", ["en"])
        sources = SourceRepository(db)
        a = sources.create(subject.id, "a.pdf", "application/pdf", "k1", 1)
        b = sources.create(subject.id, "b.pdf", "application/pdf", "k2", 1)
        yield PgVectorChunkSearch(db), subject.id, a.id, b.id


def _record(subject_id, source_id, text, tokens, embedding):
    return ChunkRecord(
        id=uuid4(), source_id=source_id, subject_id=subject_id,
        chunk=Chunk(context="ctx", text=text, page_start=0, page_end=1),
        embedding=embedding, embedding_model="fake-embed", tokens=tuple(tokens),
    )


def test_dimension(search_env):
    search, *_ = search_env
    assert search.dimension() == DIM


def test_upsert_dense_lexical_delete(search_env):
    search, subject_id, source_id, other_source = search_env
    r1 = _record(subject_id, source_id, "the biosphere", ["biosphere"], _unit(0))
    r2 = _record(subject_id, source_id, "the atmosphere", ["atmosphere"], _unit(1))
    r3 = _record(subject_id, other_source, "biosphere and atmosphere", ["biosphere", "atmosphere"], _mix(0, 1))
    search.upsert([r1, r2, r3])
    assert search.count(subject_id) == 3

    dense = search.dense(subject_id, _unit(0), k=2)
    assert [h.chunk_id for h in dense] == [r1.id, r3.id]
    assert dense[0].score > dense[1].score
    assert dense[0].content == "ctx\n\nthe biosphere"

    lexical = search.lexical(subject_id, ["atmosphere"], k=5)
    assert {h.chunk_id for h in lexical} == {r2.id, r3.id}
    assert search.lexical(subject_id, [], k=5) == []

    listed = search.list_by_source(source_id)
    assert {r.id for r in listed} == {r1.id, r2.id}
    assert listed[0].embedding_model == "fake-embed" and len(listed[0].embedding) == DIM

    search.delete_by_source(source_id)
    assert search.count(subject_id) == 1


def test_upsert_is_idempotent_on_id(search_env):
    search, subject_id, source_id, _ = search_env
    record = _record(subject_id, source_id, "v1", ["v1"], _unit(2))
    search.upsert([record])
    updated = ChunkRecord(
        id=record.id, source_id=source_id, subject_id=subject_id,
        chunk=Chunk(context="ctx", text="v2", page_start=0, page_end=0),
        embedding=_unit(3), embedding_model="fake-embed", tokens=("v2",),
    )
    search.upsert([updated])
    assert search.count(subject_id) == 1
    assert search.list_by_source(source_id)[0].chunk.text == "v2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/adapters/test_chunk_search_contract.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `chunk_search/__init__.py`** (empty) **and `memory.py`**

```python
from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from teachme.domain.models import ChunkHit, ChunkRecord


class InMemoryChunkSearch:
    name = "memory"

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension
        self._records: dict[UUID, ChunkRecord] = {}

    def dimension(self) -> int:
        return self._dimension

    def upsert(self, records: Sequence[ChunkRecord]) -> None:
        for record in records:
            if len(record.embedding) != self._dimension:
                raise ValueError(f"embedding has {len(record.embedding)} dims, store expects {self._dimension}")
            self._records[record.id] = record

    def delete_by_source(self, source_id: UUID) -> None:
        self._records = {k: v for k, v in self._records.items() if v.source_id != source_id}

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]:
        return [r for r in self._records.values() if r.source_id == source_id]

    def count(self, subject_id: UUID) -> int:
        return sum(1 for r in self._records.values() if r.subject_id == subject_id)

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]:
        scored = [
            (_cosine(vector, r.embedding), r) for r in self._records.values() if r.subject_id == subject_id
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [_hit(r, score) for score, r in scored[:k]]

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]:
        wanted = set(tokens)
        if not wanted:
            return []
        scored = []
        for r in self._records.values():
            if r.subject_id != subject_id:
                continue
            overlap = len(wanted & set(r.tokens))
            if overlap:
                scored.append((overlap / len(wanted), r))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [_hit(r, score) for score, r in scored[:k]]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _hit(record: ChunkRecord, score: float) -> ChunkHit:
    return ChunkHit(
        chunk_id=record.id, source_id=record.source_id, content=record.chunk.content,
        page_start=record.chunk.page_start, page_end=record.chunk.page_end, score=score,
    )
```

- [ ] **Step 4: Write `pgvector.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import psycopg

from teachme.domain.models import Chunk, ChunkHit, ChunkRecord

_HIT_COLUMNS = "id, source_id, context, text, page_start, page_end"


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def parse_vector(text: str) -> tuple[float, ...]:
    return tuple(float(v) for v in text.strip("[]").split(",") if v)


class PgVectorChunkSearch:
    """Chunks table: vector(1024) for dense search, tsvector('simple') for lexical search.
    Tokens are produced by teachme.domain.text.normalize so they match the relevance scorer."""

    name = "pgvector"

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def dimension(self) -> int:
        row = self._conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
        return int(row["atttypmod"])

    def upsert(self, records: Sequence[ChunkRecord]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (id, source_id, subject_id, context, text, page_start, page_end,"
                " embedding, embedding_model, tokens)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, to_tsvector('simple', %s))"
                " ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, subject_id = EXCLUDED.subject_id,"
                " context = EXCLUDED.context, text = EXCLUDED.text, page_start = EXCLUDED.page_start,"
                " page_end = EXCLUDED.page_end, embedding = EXCLUDED.embedding,"
                " embedding_model = EXCLUDED.embedding_model, tokens = EXCLUDED.tokens",
                [
                    (
                        r.id, r.source_id, r.subject_id, r.chunk.context, r.chunk.text, r.chunk.page_start,
                        r.chunk.page_end, vector_literal(r.embedding), r.embedding_model, " ".join(r.tokens),
                    )
                    for r in records
                ],
            )

    def delete_by_source(self, source_id: UUID) -> None:
        self._conn.execute("DELETE FROM chunks WHERE source_id = %s", (source_id,))

    def list_by_source(self, source_id: UUID) -> list[ChunkRecord]:
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, subject_id, embedding::text AS embedding, embedding_model,"
            " array_to_string(tsvector_to_array(tokens), ' ') AS tokens"
            " FROM chunks WHERE source_id = %s ORDER BY page_start, page_end",
            (source_id,),
        ).fetchall()
        return [
            ChunkRecord(
                id=row["id"], source_id=row["source_id"], subject_id=row["subject_id"],
                chunk=Chunk(
                    context=row["context"], text=row["text"], page_start=row["page_start"], page_end=row["page_end"]
                ),
                embedding=parse_vector(row["embedding"]), embedding_model=row["embedding_model"],
                tokens=tuple(row["tokens"].split()) if row["tokens"] else (),
            )
            for row in rows
        ]

    def count(self, subject_id: UUID) -> int:
        row = self._conn.execute("SELECT count(*) AS n FROM chunks WHERE subject_id = %s", (subject_id,)).fetchone()
        return int(row["n"])

    def dense(self, subject_id: UUID, vector: Sequence[float], k: int) -> list[ChunkHit]:
        literal = vector_literal(vector)
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, 1 - (embedding <=> %(v)s::vector) AS score"
            " FROM chunks WHERE subject_id = %(sid)s ORDER BY embedding <=> %(v)s::vector LIMIT %(k)s",
            {"v": literal, "sid": subject_id, "k": k},
        ).fetchall()
        return [_row_to_hit(row) for row in rows]

    def lexical(self, subject_id: UUID, tokens: Sequence[str], k: int) -> list[ChunkHit]:
        if not tokens:
            return []
        query = " | ".join(tokens)
        rows = self._conn.execute(
            f"SELECT {_HIT_COLUMNS}, ts_rank_cd(tokens, to_tsquery('simple', %(q)s)) AS score"
            " FROM chunks WHERE subject_id = %(sid)s AND tokens @@ to_tsquery('simple', %(q)s)"
            " ORDER BY score DESC LIMIT %(k)s",
            {"q": query, "sid": subject_id, "k": k},
        ).fetchall()
        return [_row_to_hit(row) for row in rows]


def _row_to_hit(row: dict) -> ChunkHit:
    return ChunkHit(
        chunk_id=row["id"], source_id=row["source_id"], content=f"{row['context']}\n\n{row['text']}",
        page_start=row["page_start"], page_end=row["page_end"], score=float(row["score"]),
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/adapters/test_chunk_search_contract.py`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add api/teachme/adapters/chunk_search api/tests/adapters/test_chunk_search_contract.py
git commit -m "feat: in-memory and pgvector chunk search with contract test"
```

---

## Phase E: Telemetry

### Task 18: Price table, usage recorder and recording wrappers

**Files:**
- Create: `api/teachme/telemetry/__init__.py`, `prices.py`, `usage.py`, `recording.py`
- Test: `api/tests/telemetry/test_telemetry.py`

- [ ] **Step 1: Write the failing test** (`api/tests/telemetry/__init__.py` empty)

```python
from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.llm.fake import FakeLLM
from teachme.ports.llm import ContentPart, LLMUsage, StructuredRequest
from teachme.telemetry.prices import ModelPrice, PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder, current_usage_context, usage_context


class _Repo:
    def __init__(self):
        self.rows = []

    def insert(self, row):
        self.rows.append(row)


def test_price_table_costs():
    table = PriceTable({"m": ModelPrice(input_per_m=5, output_per_m=25, cache_read_per_m=0.5, cache_write_per_m=6.25)})
    usage = LLMUsage(input_tokens=1000, output_tokens=1000, cache_read_tokens=1000, cache_write_tokens=1000)
    assert round(table.cost_llm("m", usage), 6) == round(0.005 + 0.025 + 0.0005 + 0.00625, 6)
    assert table.cost_tokens("m", 2_000_000) == 10.0
    assert table.cost_llm("unknown-model", usage) == 0.0


def test_default_prices_cover_configured_models():
    table = PriceTable()
    for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "voyage-4", "rerank-2.5", "fake-model"):
        assert table.price_for(model) is not None


def test_usage_context_nests_and_resets():
    assert current_usage_context().subject_id is None
    sid, src = uuid4(), uuid4()
    with usage_context(subject_id=sid):
        with usage_context(source_id=src):
            ctx = current_usage_context()
            assert ctx.subject_id == sid and ctx.source_id == src
        assert current_usage_context().source_id is None
    assert current_usage_context().subject_id is None


def test_recorder_writes_row_with_context_and_cost():
    repo = _Repo()
    recorder = UsageRecorder(repo, PriceTable({"m": ModelPrice(input_per_m=1, output_per_m=1)}))
    sid = uuid4()
    with usage_context(subject_id=sid):
        recorder.record_llm(purpose="p", provider="fake", model="m",
                            usage=LLMUsage(input_tokens=500_000, output_tokens=500_000), latency_ms=12)
    row = repo.rows[0]
    assert row.purpose == "p" and row.subject_id == sid and row.cost_usd == 1.0 and row.latency_ms == 12


class Out(BaseModel):
    ok: bool


def test_recording_llm_and_embedder_delegate_and_record():
    repo = _Repo()
    recorder = UsageRecorder(repo, PriceTable())
    llm = RecordingLLM(FakeLLM({Out: lambda r: Out(ok=True)}), recorder)
    req = StructuredRequest(purpose="ingest.test", model="fake-model", system="s", parts=(ContentPart.of_text("x"),))
    assert llm.generate_structured(req, Out).output.ok is True
    assert llm.name == "fake" and "application/pdf" in llm.capabilities().media_types
    embedder = RecordingEmbedder(FakeEmbedder(dimension=8), recorder)
    assert len(embedder.embed_documents(["a", "b"]).vectors) == 2
    assert embedder.dimension == 8 and embedder.model == "fake-embed"
    purposes = [r.purpose for r in repo.rows]
    assert purposes == ["ingest.test", "embed.documents"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/telemetry/test_telemetry.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `telemetry/__init__.py`** (empty) **and `prices.py`**

```python
from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from teachme.ports.llm import LLMUsage

log = logging.getLogger(__name__)


class ModelPrice(BaseModel):
    """USD per million tokens."""

    model_config = ConfigDict(frozen=True)

    input_per_m: float
    output_per_m: float
    cache_read_per_m: float = 0.0
    cache_write_per_m: float = 0.0


# Anthropic first-party rates as of 2026-06. Voyage rates: verify at voyageai.com/pricing and
# override through PriceTable(prices=...) if they differ; they are small relative to Claude.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(input_per_m=5.0, output_per_m=25.0, cache_read_per_m=0.5, cache_write_per_m=6.25),
    "claude-sonnet-5": ModelPrice(input_per_m=2.0, output_per_m=10.0, cache_read_per_m=0.2, cache_write_per_m=2.5),
    "claude-haiku-4-5": ModelPrice(input_per_m=1.0, output_per_m=5.0, cache_read_per_m=0.1, cache_write_per_m=1.25),
    "voyage-4": ModelPrice(input_per_m=0.12, output_per_m=0.0),
    "rerank-2.5": ModelPrice(input_per_m=0.05, output_per_m=0.0),
    "fake-model": ModelPrice(input_per_m=0.0, output_per_m=0.0),
    "fake-embed": ModelPrice(input_per_m=0.0, output_per_m=0.0),
}


class PriceTable:
    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = dict(prices) if prices is not None else dict(DEFAULT_PRICES)
        self._warned: set[str] = set()

    def price_for(self, model: str) -> ModelPrice | None:
        price = self._prices.get(model)
        if price is None and model not in self._warned:
            log.warning("no price configured for model %r; recording cost 0", model)
            self._warned.add(model)
        return price

    def cost_llm(self, model: str, usage: LLMUsage) -> float:
        price = self.price_for(model)
        if price is None:
            return 0.0
        return (
            usage.input_tokens * price.input_per_m
            + usage.output_tokens * price.output_per_m
            + usage.cache_read_tokens * price.cache_read_per_m
            + usage.cache_write_tokens * price.cache_write_per_m
        ) / 1_000_000

    def cost_tokens(self, model: str, tokens: int) -> float:
        price = self.price_for(model)
        return 0.0 if price is None else tokens * price.input_per_m / 1_000_000
```

- [ ] **Step 4: Write `usage.py`**

```python
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.ports.llm import LLMUsage
from teachme.repositories.usage import UsageRepository, UsageRow
from teachme.telemetry.prices import PriceTable


class UsageContext(BaseModel):
    """Who and what a call was for. Set by services, read by the recorder."""

    model_config = ConfigDict(frozen=True)

    subject_id: UUID | None = None
    source_id: UUID | None = None
    user_id: str | None = None
    attempt_id: UUID | None = None


_current: ContextVar[UsageContext] = ContextVar("teachme_usage_context", default=UsageContext())


def current_usage_context() -> UsageContext:
    return _current.get()


@contextmanager
def usage_context(**fields: object) -> Iterator[None]:
    """Nest freely; inner fields override, everything else is inherited."""
    merged = _current.get().model_copy(update=fields)
    token = _current.set(merged)
    try:
        yield
    finally:
        _current.reset(token)


class UsageRecorder:
    def __init__(self, repo: UsageRepository, prices: PriceTable) -> None:
        self._repo = repo
        self._prices = prices

    def record_llm(self, *, purpose: str, provider: str, model: str, usage: LLMUsage, latency_ms: int) -> UsageRow:
        row = self._row(
            purpose=purpose, provider=provider, model=model, latency_ms=latency_ms,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens, cache_write_tokens=usage.cache_write_tokens,
            cost_usd=self._prices.cost_llm(model, usage),
        )
        self._repo.insert(row)
        return row

    def record_embedding(self, *, purpose: str, provider: str, model: str, tokens: int, latency_ms: int) -> UsageRow:
        row = self._row(
            purpose=purpose, provider=provider, model=model, latency_ms=latency_ms,
            input_tokens=tokens, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=self._prices.cost_tokens(model, tokens),
        )
        self._repo.insert(row)
        return row

    @staticmethod
    def _row(**fields: object) -> UsageRow:
        ctx = current_usage_context()
        return UsageRow(
            user_id=ctx.user_id, subject_id=ctx.subject_id, source_id=ctx.source_id, attempt_id=ctx.attempt_id,
            **fields,  # type: ignore[arg-type]
        )
```

- [ ] **Step 5: Write `recording.py`**

```python
from __future__ import annotations

import time
from collections.abc import Sequence

from teachme.ports.embeddings import Embedder, EmbeddingResult
from teachme.ports.llm import LLMCapabilities, LLMProvider, StructuredRequest, StructuredResult, T
from teachme.telemetry.usage import UsageRecorder


class RecordingLLM:
    """Wraps any LLMProvider and writes one usage row per call. Adapters stay pure."""

    def __init__(self, inner: LLMProvider, recorder: UsageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder
        self.name = inner.name

    def capabilities(self) -> LLMCapabilities:
        return self._inner.capabilities()

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        started = time.perf_counter()
        result = self._inner.generate_structured(request, schema)
        self._recorder.record_llm(
            purpose=request.purpose, provider=self._inner.name, model=result.model, usage=result.usage,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result


class RecordingEmbedder:
    def __init__(self, inner: Embedder, recorder: UsageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder
        self.name = inner.name
        self.model = inner.model
        self.dimension = inner.dimension

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        return self._timed("embed.documents", lambda: self._inner.embed_documents(texts))

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._timed("embed.query", lambda: self._inner.embed_query(text))

    def _timed(self, purpose: str, call) -> EmbeddingResult:
        started = time.perf_counter()
        result = call()
        self._recorder.record_embedding(
            purpose=purpose, provider=self._inner.name, model=self._inner.model, tokens=result.tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result
```

- [ ] **Step 6: Run to verify it passes**

Run: `pytest -q api/tests/telemetry/test_telemetry.py`
Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
git add api/teachme/telemetry api/tests/telemetry
git commit -m "feat: price table, usage recorder and recording wrappers"
```

---

## Phase F: Retrieval

### Task 19: Hybrid search over the ports

**Files:**
- Create: `api/teachme/retrieval/__init__.py`, `api/teachme/retrieval/hybrid.py`
- Test: `api/tests/retrieval/test_hybrid.py`

- [ ] **Step 1: Write the failing test** (`api/tests/retrieval/__init__.py` empty)

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.reranker.noop import NoopReranker
from teachme.domain.models import Chunk, ChunkRecord
from teachme.domain.text.normalize import tokenize
from teachme.retrieval.hybrid import HybridSearch


def _record(subject_id, text, embedder):
    return ChunkRecord(
        id=uuid4(), source_id=uuid4(), subject_id=subject_id,
        chunk=Chunk(context="ctx", text=text, page_start=0, page_end=0),
        embedding=tuple(embedder.embed_documents([f"ctx\n\n{text}"]).vectors[0]),
        embedding_model=embedder.model, tokens=tuple(tokenize(text, "en")),
    )


def test_hybrid_returns_lexical_match_even_when_dense_misses():
    embedder = FakeEmbedder(dimension=32)
    search = InMemoryChunkSearch(dimension=32)
    subject_id = uuid4()
    target = _record(subject_id, "The atmosphere protects the biosphere", embedder)
    search.upsert([target] + [_record(subject_id, f"filler text number {i}", embedder) for i in range(5)])

    hybrid = HybridSearch(embedder, search, NoopReranker(), candidates=10, final_k=3)
    hits = hybrid.search(subject_id, "what protects the biosphere?", language_code="en")
    assert hits and hits[0].chunk_id == target.id
    assert len(hits) <= 3


def test_hybrid_empty_subject():
    embedder = FakeEmbedder(dimension=8)
    hybrid = HybridSearch(embedder, InMemoryChunkSearch(dimension=8), NoopReranker())
    assert hybrid.search(uuid4(), "anything", language_code="he") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/retrieval/test_hybrid.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `retrieval/__init__.py`** (empty) **and `hybrid.py`**

```python
from __future__ import annotations

from uuid import UUID

from teachme.domain.models import ChunkHit
from teachme.domain.retrieval.fusion import reciprocal_rank_fusion
from teachme.domain.text.normalize import tokenize
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder
from teachme.ports.reranker import Reranker


class HybridSearch:
    """dense + lexical -> reciprocal rank fusion -> rerank -> top k.

    Anthropic's contextual-retrieval measurements: 150 candidates reranked to 20 beats 5 or 10."""

    def __init__(
        self, embedder: Embedder, search: ChunkSearch, reranker: Reranker, candidates: int = 150, final_k: int = 20
    ) -> None:
        self._embedder = embedder
        self._search = search
        self._reranker = reranker
        self._candidates = candidates
        self._final_k = final_k

    def search(self, subject_id: UUID, query: str, language_code: str, k: int | None = None) -> list[ChunkHit]:
        k = k or self._final_k
        vector = self._embedder.embed_query(query).vectors[0]
        dense = self._search.dense(subject_id, vector, self._candidates)
        lexical = self._search.lexical(subject_id, tokenize(query, language_code), self._candidates)
        fused = reciprocal_rank_fusion([dense, lexical])[: self._candidates]
        if not fused:
            return []
        order = self._reranker.rerank(query, [hit.content for hit in fused], top_k=k)
        return [fused[index] for index in order]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/retrieval/test_hybrid.py`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/retrieval api/tests/retrieval
git commit -m "feat: hybrid search over chunk search, embedder and reranker ports"
```

---

## Phase G: Ingestion pipeline

### Task 20: Errors, prompt loader and prompt files

**Files:**
- Create: `api/teachme/ingestion/__init__.py`, `api/teachme/ingestion/errors.py`, `api/teachme/ingestion/prompts/__init__.py`, `api/teachme/ingestion/prompts/read_pages.md`, `detect_language.md`, `contextualize.md`
- Modify: `pyproject.toml` (package data)
- Test: `api/tests/ingestion/test_prompts.py`

- [ ] **Step 1: Write the failing test** (`api/tests/ingestion/__init__.py` empty)

```python
from __future__ import annotations

import pytest

from teachme.ingestion.prompts import load_prompt


def test_prompts_load_and_are_non_empty():
    for name in ("read_pages", "detect_language", "contextualize"):
        text = load_prompt(name)
        assert len(text) > 100


def test_contextualize_prompt_has_placeholders():
    text = load_prompt("contextualize")
    assert "{subject}" in text and "{source}" in text


def test_unknown_prompt():
    with pytest.raises(FileNotFoundError):
        load_prompt("nope")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_prompts.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `ingestion/__init__.py`** (empty), **`errors.py`**

```python
from __future__ import annotations


class IngestionError(Exception):
    """Base class; the pipeline records str(exc) on the source."""


class UnsupportedMediaType(IngestionError):
    pass


class TooManyPages(IngestionError):
    pass


class ExtractionError(IngestionError):
    pass


class CoverageError(IngestionError):
    pass


class SubjectLocked(IngestionError):
    pass
```

- [ ] **Step 4: Write `prompts/__init__.py`**

```python
from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load_prompt(name: str) -> str:
    """Prompt text from `<name>.md` next to this file. Raises FileNotFoundError for unknown names."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
```

- [ ] **Step 5: Write `prompts/read_pages.md`**

```markdown
You transcribe textbook pages for a tutoring system. You receive a PDF fragment of consecutive pages (the user message states the exact count) and you return exactly one entry per page, in order, even for blank pages.

For each page:
- page_offset: 0 for the first page of this fragment, 1 for the second, and so on.
- printed_number: the page number printed on the page, exactly as printed, or null if none is visible.
- text_markdown: the complete text of the page as Markdown, in the original language. Preserve headings, lists, tables (as Markdown tables), footnotes and the reading order across columns. Do not summarize, translate or omit anything. Figure captions go in the figures list, not here, unless they carry body text.
- figures: every visual element that carries meaning: map, diagram, chart, photo, illustration, or a table rendered as an image. For each: kind (one of map, diagram, chart, photo, illustration, table, other), caption exactly as printed (empty string if none), and description: two to four sentences saying what the figure shows and what a student should notice, including legible labels, places, quantities and dates. Purely decorative elements are not figures.

Accuracy matters more than speed. If a word is illegible write [illegible]. Never invent text that is not on the page.
```

- [ ] **Step 6: Write `prompts/detect_language.md`**

```markdown
Identify the main language of the body text you are given. Return the ISO 639-1 two-letter code and the English name of the language. If the text mixes languages, pick the language of the majority of the body text, ignoring quotations, glossaries and page furniture. If you cannot tell, return code "und" and name "Undetermined".
```

- [ ] **Step 7: Write `prompts/contextualize.md`**

```markdown
You split textbook pages into overlapping chunks for a retrieval index, following the contextual retrieval technique: a chunk that cannot be understood on its own cannot be retrieved on its own, so every chunk gets a short situating context.

The pages belong to the subject "{subject}", from the source "{source}". They are wrapped in <page index="N" printed="P"> tags. Pages inside <context_before> and <context_after> are for orientation only: do not produce chunks from them.

For each chunk produce:
1. original_text: verbatim text copied from the batch pages, unchanged. Together the chunks must cover every batch page completely; leave nothing out. Overlap neighbouring chunks by roughly a quarter so the same sentence appears in two chunks where a topic continues. Aim for chunks of 100 to 300 words that can each answer a specific question alone.
2. context: 50 to 100 tokens, written in the language of the source text, situating the chunk within the source: the chapter or section it belongs to, the concept it discusses, and the named places, people, dates and figures it refers to. It orients a reader who sees only this chunk. Do not summarize the chunk itself.
3. page_start and page_end: the index attributes of the first and last page the original_text spans.

Figure blocks (lines beginning with "> **[Figure") are part of the page text and must be included in chunks like any other text.
```

- [ ] **Step 8: Add package data to `pyproject.toml`** so the Markdown prompts ship with the package

Add under the `[tool.setuptools.packages.find]` block:

```toml
[tool.setuptools.package-data]
teachme = ["**/*.md", "**/*.sql"]
```

Then run `uv pip install -e ".[dev]"` again.

- [ ] **Step 9: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_prompts.py`
Expected: `3 passed`

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml api/teachme/ingestion api/tests/ingestion
git commit -m "feat: ingestion errors, prompt loader and prompt files"
```

---

### Task 21: Digest bundle writer and reader

**Files:**
- Create: `api/teachme/adapters/file_store/prefixed.py`, `api/teachme/ingestion/bundle.py`
- Test: `api/tests/ingestion/test_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import UUID, uuid4

from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.domain.models import Chunk, ChunkRecord, Figure, Page
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug


def test_bundle_slug_is_ascii_and_unique_for_hebrew_names():
    sid = UUID("12345678-0000-0000-0000-000000000000")
    assert bundle_slug("History ch. 3", sid) == "history-ch-3-12345678"
    assert bundle_slug("היסטוריה", sid) == "item-12345678"


def test_prefixed_store_maps_keys():
    inner = InMemoryFileStore()
    store = PrefixedFileStore(inner, "digest/")
    store.put("a/b.md", b"x", "text/markdown")
    assert inner.get("digest/a/b.md") == b"x"
    assert store.get("a/b.md") == b"x" and store.exists("a/b.md")
    assert store.list_keys("a/") == ["a/b.md"]
    store.delete("a/b.md")
    assert not inner.exists("digest/a/b.md")


def test_writer_writes_every_store_and_reader_round_trips(tmp_path):
    memory = InMemoryFileStore()
    local = LocalFileStore(tmp_path)
    writer = BundleWriter([memory, local], subject_slug="geo-1234abcd")
    pages = [Page(page_index=0, printed_number="12", text="# Earth\n\nText."), Page(page_index=1, printed_number=None, text="More.")]
    figures = [Figure(page_index=0, ordinal=0, kind="map", caption="World", description="A map.")]
    chunks = [Chunk(context="c1", text="Text.", page_start=0, page_end=0), Chunk(context="c2", text="More.", page_start=1, page_end=1)]
    meta = SourceMeta(source_id=uuid4(), filename="ch1.pdf", media_type="application/pdf", size=10, page_count=2,
                      vision_pages=2, language="en", models={"read_pages": "fake-model"}, embedding_model="fake-embed")
    records = [
        ChunkRecord(id=uuid4(), source_id=meta.source_id, subject_id=uuid4(), chunk=c, embedding=(0.5, 0.5),
                    embedding_model="fake-embed", tokens=("t",))
        for c in chunks
    ]
    writer.write_meta("ch1-abcd1234", meta)
    writer.write_pages("ch1-abcd1234", pages)
    writer.write_figures("ch1-abcd1234", figures)
    writer.write_chunks("ch1-abcd1234", chunks)
    writer.write_embeddings("ch1-abcd1234", records)

    assert (tmp_path / "geo-1234abcd" / "ch1-abcd1234" / "pages" / "001.md").is_file()
    assert memory.exists("geo-1234abcd/ch1-abcd1234/chunks.jsonl")

    reader = BundleReader(memory, "geo-1234abcd/ch1-abcd1234")
    assert reader.meta() == meta
    assert reader.pages() == pages
    assert reader.figures() == figures
    assert reader.chunks() == chunks
    embeddings = reader.embeddings()
    assert embeddings is not None and embeddings[1].vector == (0.5, 0.5) and embeddings[1].index == 1

    local_reader = BundleReader(LocalFileStore(tmp_path / "geo-1234abcd" / "ch1-abcd1234"), "")
    assert local_reader.pages() == pages


def test_reader_without_embeddings_returns_none():
    memory = InMemoryFileStore()
    BundleWriter([memory], "s").write_chunks("x", [Chunk(context="c", text="t", page_start=0, page_end=0)])
    assert BundleReader(memory, "s/x").embeddings() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_bundle.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `adapters/file_store/prefixed.py`**

```python
from __future__ import annotations

from teachme.ports.file_store import FileStore


class PrefixedFileStore:
    """View of another store under a fixed key prefix. Lets the digest bundle live at
    digest/... in the primary store while bundle code sees plain relative keys."""

    def __init__(self, inner: FileStore, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix
        self.name = f"{inner.name}:{prefix}"

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._inner.put(self._key(key), data, content_type)

    def get(self, key: str) -> bytes:
        return self._inner.get(self._key(key))

    def exists(self, key: str) -> bool:
        return self._inner.exists(self._key(key))

    def delete(self, key: str) -> None:
        self._inner.delete(self._key(key))

    def list_keys(self, prefix: str) -> list[str]:
        return [k[len(self._prefix) :] for k in self._inner.list_keys(self._key(prefix))]
```

- [ ] **Step 4: Write `ingestion/bundle.py`**

```python
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import Chunk, ChunkRecord, Figure, Page
from teachme.ports.file_store import FileNotFound, FileStore

PIPELINE_VERSION = 1
_PAGE_HEADER = re.compile(r'^<!-- teach-me page index=(\d+) printed=(null|"(.*?)") -->\n\n', re.DOTALL)


class SourceMeta(BaseModel):
    """meta.json: everything needed to re-import the source without the original file."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    filename: str
    media_type: str
    size: int
    page_count: int
    vision_pages: int
    language: str | None
    models: dict[str, str]
    embedding_model: str | None = None
    pipeline_version: int = PIPELINE_VERSION


class ChunkRow(BaseModel):
    index: int
    context: str
    text: str
    page_start: int
    page_end: int


class EmbeddingRow(BaseModel):
    index: int
    chunk_id: UUID
    model: str
    vector: tuple[float, ...]


def slugify(name: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug or "item"


def bundle_slug(name: str, identifier: UUID) -> str:
    """Readable and unique even for non-Latin names: `<slug>-<first 8 hex of id>`."""
    return f"{slugify(name)}-{str(identifier)[:8]}"


def page_filename(page_index: int) -> str:
    return f"pages/{page_index + 1:03d}.md"


class BundleWriter:
    def __init__(self, stores: Sequence[FileStore], subject_slug: str) -> None:
        self._stores = list(stores)
        self._subject_slug = subject_slug

    def prefix(self, source_slug: str) -> str:
        return f"{self._subject_slug}/{source_slug}"

    def write_meta(self, source_slug: str, meta: SourceMeta) -> None:
        self._write(source_slug, "meta.json", meta.model_dump_json(indent=2).encode(), "application/json")

    def write_pages(self, source_slug: str, pages: Sequence[Page]) -> None:
        for page in pages:
            printed = "null" if page.printed_number is None else json.dumps(page.printed_number)
            body = f"<!-- teach-me page index={page.page_index} printed={printed} -->\n\n{page.text}"
            self._write(source_slug, page_filename(page.page_index), body.encode(), "text/markdown")

    def write_figures(self, source_slug: str, figures: Sequence[Figure]) -> None:
        payload = json.dumps([f.model_dump() for f in figures], ensure_ascii=False, indent=2)
        self._write(source_slug, "figures.json", payload.encode(), "application/json")

    def write_chunks(self, source_slug: str, chunks: Sequence[Chunk]) -> None:
        rows = [ChunkRow(index=i, **c.model_dump()) for i, c in enumerate(chunks)]
        self._write(source_slug, "chunks.jsonl", _jsonl(rows), "application/x-ndjson")

    def write_embeddings(self, source_slug: str, records: Sequence[ChunkRecord]) -> None:
        rows = [
            EmbeddingRow(index=i, chunk_id=r.id, model=r.embedding_model, vector=r.embedding)
            for i, r in enumerate(records)
        ]
        self._write(source_slug, "embeddings.jsonl", _jsonl(rows), "application/x-ndjson")

    def _write(self, source_slug: str, relative: str, data: bytes, content_type: str) -> None:
        key = f"{self.prefix(source_slug)}/{relative}"
        for store in self._stores:
            store.put(key, data, content_type)


class BundleReader:
    """Reads one source bundle from any store. `prefix` is '' when the store is rooted at the bundle."""

    def __init__(self, store: FileStore, prefix: str) -> None:
        self._store = store
        self._prefix = prefix.strip("/")

    def _key(self, relative: str) -> str:
        return f"{self._prefix}/{relative}" if self._prefix else relative

    def meta(self) -> SourceMeta:
        return SourceMeta.model_validate_json(self._store.get(self._key("meta.json")))

    def pages(self) -> list[Page]:
        pages: list[Page] = []
        for key in self._store.list_keys(self._key("pages/")):
            raw = self._store.get(key).decode("utf-8")
            match = _PAGE_HEADER.match(raw)
            if match is None:
                raise ValueError(f"{key} has no teach-me page header")
            printed = None if match.group(2) == "null" else json.loads(match.group(2))
            pages.append(Page(page_index=int(match.group(1)), printed_number=printed, text=raw[match.end() :]))
        return sorted(pages, key=lambda p: p.page_index)

    def figures(self) -> list[Figure]:
        return [Figure.model_validate(item) for item in json.loads(self._store.get(self._key("figures.json")))]

    def chunks(self) -> list[Chunk]:
        rows = _read_jsonl(self._store.get(self._key("chunks.jsonl")), ChunkRow)
        rows.sort(key=lambda r: r.index)
        return [Chunk(context=r.context, text=r.text, page_start=r.page_start, page_end=r.page_end) for r in rows]

    def embeddings(self) -> list[EmbeddingRow] | None:
        try:
            data = self._store.get(self._key("embeddings.jsonl"))
        except FileNotFound:
            return None
        rows = _read_jsonl(data, EmbeddingRow)
        rows.sort(key=lambda r: r.index)
        return rows

    def has_chunks(self) -> bool:
        return self._store.exists(self._key("chunks.jsonl"))


def _jsonl(rows: Sequence[BaseModel]) -> bytes:
    return ("".join(row.model_dump_json() + "\n" for row in rows)).encode("utf-8")


def _read_jsonl(data: bytes, model: type):
    return [model.model_validate_json(line) for line in data.decode("utf-8").splitlines() if line.strip()]
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_bundle.py`
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add api/teachme/adapters/file_store/prefixed.py api/teachme/ingestion/bundle.py api/tests/ingestion/test_bundle.py
git commit -m "feat: digest bundle writer/reader and prefixed file store"
```

---

### Task 22: PDF page splitting

**Files:**
- Create: `api/teachme/ingestion/pdf_pages.py`
- Test: `api/tests/ingestion/test_pdf_pages.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import page_count, split_pdf
from tests.helpers import make_pdf


def test_page_count():
    assert page_count(make_pdf(7)) == 7


def test_split_into_batches_with_valid_pdfs():
    batches = split_pdf(make_pdf(7), pages_per_batch=3)
    assert [(b.first_index, b.last_index) for b in batches] == [(0, 2), (3, 5), (6, 6)]
    assert [b.page_count for b in batches] == [3, 3, 1]
    assert all(page_count(b.data) == b.page_count for b in batches)


def test_split_single_batch_when_small():
    batches = split_pdf(make_pdf(2), pages_per_batch=6)
    assert len(batches) == 1 and batches[0].page_count == 2


def test_invalid_pdf_raises():
    with pytest.raises(ExtractionError):
        page_count(b"not a pdf")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_pdf_pages.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `pdf_pages.py`**

```python
from __future__ import annotations

import io

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from teachme.ingestion.errors import ExtractionError


class PdfBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_index: int
    last_index: int
    data: bytes

    @property
    def page_count(self) -> int:
        return self.last_index - self.first_index + 1


def _reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        _ = len(reader.pages)
        return reader
    except (PyPdfError, ValueError, TypeError) as exc:
        raise ExtractionError(f"not a readable PDF: {exc}") from exc


def page_count(data: bytes) -> int:
    return len(_reader(data).pages)


def split_pdf(data: bytes, pages_per_batch: int) -> list[PdfBatch]:
    """Consecutive page ranges, each written as its own small PDF for one model call."""
    reader = _reader(data)
    total = len(reader.pages)
    batches: list[PdfBatch] = []
    for first in range(0, total, pages_per_batch):
        last = min(first + pages_per_batch, total) - 1
        writer = PdfWriter()
        for index in range(first, last + 1):
            writer.add_page(reader.pages[index])
        buffer = io.BytesIO()
        writer.write(buffer)
        batches.append(PdfBatch(first_index=first, last_index=last, data=buffer.getvalue()))
    return batches
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_pdf_pages.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/ingestion/pdf_pages.py api/tests/ingestion/test_pdf_pages.py
git commit -m "feat: pdf page counting and batch splitting"
```

---

### Task 23: Reading pages with Claude (text, printed numbers, figures)

**Files:**
- Create: `api/teachme/ingestion/read_pages.py`
- Test: `api/tests/ingestion/test_read_pages.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.read_pages import (
    ReadFigure,
    ReadPage,
    ReadPagesOutput,
    format_figure_block,
    read_image,
    read_pdf_batch,
)


def _output(n, with_figure=True):
    pages = []
    for i in range(n):
        figures = [ReadFigure(kind="map", caption="World 1850", description="A world map.")] if with_figure and i == 0 else []
        pages.append(ReadPage(page_offset=i, printed_number=str(10 + i), text_markdown=f"Page {i} text.", figures=figures))
    return ReadPagesOutput(pages=pages)


def test_read_pdf_batch_maps_offsets_to_source_indices_and_appends_figure_blocks():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(2)})
    batch = PdfBatch(first_index=4, last_index=5, data=b"%PDF")
    pages, figures = read_pdf_batch(llm, "fake-model", batch, language_hint="pt")
    assert [p.page_index for p in pages] == [4, 5]
    assert pages[0].printed_number == "10"
    assert pages[0].text.startswith("Page 0 text.")
    assert "> **[Figure: World 1850]** A world map." in pages[0].text
    assert "[Figure" not in pages[1].text
    assert figures == [type(figures[0])(page_index=4, ordinal=0, kind="map", caption="World 1850", description="A world map.")]
    request = llm.calls[0]
    assert request.purpose == "ingest.read_pages" and request.parts[0].kind == "document"
    assert "2 pages" in request.parts[1].text and "pt" in request.parts[1].text


def test_wrong_page_count_is_an_extraction_error():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(1)})
    with pytest.raises(ExtractionError):
        read_pdf_batch(llm, "fake-model", PdfBatch(first_index=0, last_index=2, data=b"%PDF"), language_hint=None)


def test_read_image_is_a_single_page():
    llm = FakeLLM({ReadPagesOutput: lambda req: _output(1, with_figure=False)})
    pages, figures = read_image(llm, "fake-model", b"\x89PNG", "image/png", page_index=0)
    assert len(pages) == 1 and pages[0].page_index == 0 and figures == []
    assert llm.calls[0].parts[0].kind == "image"


def test_format_figure_block_without_caption():
    block = format_figure_block(ReadFigure(kind="photo", caption="", description="A harbour."))
    assert block == "\n\n> **[Figure: photo]** A harbour.\n"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_read_pages.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `read_pages.py`**

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from teachme.domain.models import Figure, Page
from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

READ_MAX_TOKENS = 32000


class ReadFigure(BaseModel):
    kind: str = Field(description="One of: map, diagram, chart, photo, illustration, table, other")
    caption: str = Field(description="The caption exactly as printed; empty string if none")
    description: str = Field(description="Two to four sentences on what the figure shows and what to notice")


class ReadPage(BaseModel):
    page_offset: int = Field(ge=0, description="0 for the first page of this fragment, 1 for the second, ...")
    printed_number: str | None = Field(description="Page number printed on the page, or null")
    text_markdown: str = Field(description="Complete page text as Markdown in the original language")
    figures: list[ReadFigure]


class ReadPagesOutput(BaseModel):
    pages: list[ReadPage]


def format_figure_block(figure: ReadFigure) -> str:
    label = figure.caption.strip() or figure.kind
    return f"\n\n> **[Figure: {label}]** {figure.description.strip()}\n"


def read_pdf_batch(
    llm: LLMProvider, model: str, batch: PdfBatch, language_hint: str | None
) -> tuple[list[Page], list[Figure]]:
    parts = (
        ContentPart.of_document(batch.data, "application/pdf"),
        ContentPart.of_text(_instruction(batch.page_count, language_hint)),
    )
    return _read(llm, model, parts, first_index=batch.first_index, expected=batch.page_count)


def read_image(
    llm: LLMProvider, model: str, data: bytes, media_type: str, page_index: int, language_hint: str | None = None
) -> tuple[list[Page], list[Figure]]:
    parts = (ContentPart.of_image(data, media_type), ContentPart.of_text(_instruction(1, language_hint)))
    return _read(llm, model, parts, first_index=page_index, expected=1)


def _instruction(page_count: int, language_hint: str | None) -> str:
    language = language_hint or "unknown"
    return (
        f"This fragment contains exactly {page_count} pages. The document language is probably {language}. "
        "Transcribe every page and list its figures."
    )


def _read(
    llm: LLMProvider, model: str, parts: tuple[ContentPart, ...], *, first_index: int, expected: int
) -> tuple[list[Page], list[Figure]]:
    request = StructuredRequest(
        purpose="ingest.read_pages", model=model, system=load_prompt("read_pages"), parts=parts,
        max_tokens=READ_MAX_TOKENS, effort="medium",
    )
    output = llm.generate_structured(request, ReadPagesOutput).output
    offsets = sorted(p.page_offset for p in output.pages)
    if offsets != list(range(expected)):
        raise ExtractionError(f"expected pages 0..{expected - 1}, model returned offsets {offsets}")

    pages: list[Page] = []
    figures: list[Figure] = []
    for read_page in sorted(output.pages, key=lambda p: p.page_offset):
        index = first_index + read_page.page_offset
        text = read_page.text_markdown.rstrip()
        for ordinal, figure in enumerate(read_page.figures):
            text += format_figure_block(figure)
            figures.append(
                Figure(page_index=index, ordinal=ordinal, kind=figure.kind, caption=figure.caption,
                       description=figure.description)
            )
        pages.append(Page(page_index=index, printed_number=read_page.printed_number, text=text))
    return pages, figures
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_read_pages.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/ingestion/read_pages.py api/tests/ingestion/test_read_pages.py
git commit -m "feat: page reading with figures via structured output"
```

---

### Task 24: Extraction dispatch and language detection

**Files:**
- Create: `api/teachme/ingestion/extract.py`, `api/teachme/ingestion/detect_language.py`
- Test: `api/tests/ingestion/test_extract.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.ingestion.detect_language import DetectedLanguage, detect_language
from teachme.ingestion.errors import TooManyPages, UnsupportedMediaType
from teachme.ingestion.extract import extract
from teachme.ingestion.read_pages import ReadPage, ReadPagesOutput
from teachme.settings import Settings
from tests.helpers import make_pdf


def _responder(req):
    count = int(req.parts[1].text.split("exactly ")[1].split(" ")[0])
    return ReadPagesOutput(pages=[
        ReadPage(page_offset=i, printed_number=None, text_markdown=f"p{i}", figures=[]) for i in range(count)
    ])


def _settings(**overrides):
    return Settings(_env_file=None, llm_provider="fake", **overrides)


def test_pdf_is_read_in_batches():
    llm = FakeLLM({ReadPagesOutput: _responder})
    result = extract(llm, _settings(pages_per_read_batch=3), make_pdf(7), "application/pdf", language_hint=None)
    assert [p.page_index for p in result.pages] == list(range(7))
    assert result.vision_pages == 7 and len(llm.calls) == 3


def test_text_file_needs_no_model():
    llm = FakeLLM({})
    result = extract(llm, _settings(), "# Title\n\nBody".encode(), "text/markdown", language_hint=None)
    assert len(result.pages) == 1 and result.pages[0].text.startswith("# Title") and result.vision_pages == 0
    assert llm.calls == []


def test_image_is_one_vision_page():
    llm = FakeLLM({ReadPagesOutput: _responder})
    result = extract(llm, _settings(), b"\x89PNG", "image/png", language_hint="he")
    assert len(result.pages) == 1 and result.vision_pages == 1


def test_unsupported_and_too_many_pages():
    llm = FakeLLM({ReadPagesOutput: _responder})
    with pytest.raises(UnsupportedMediaType):
        extract(llm, _settings(), b"x", "application/zip", language_hint=None)
    with pytest.raises(TooManyPages):
        extract(llm, _settings(max_pages_per_source=3), make_pdf(4), "application/pdf", language_hint=None)


def test_detect_language_uses_first_pages():
    llm = FakeLLM({DetectedLanguage: lambda req: DetectedLanguage(code="pt", name="Portuguese")})
    from teachme.domain.models import Page
    pages = [Page(page_index=i, printed_number=None, text=f"texto {i}") for i in range(5)]
    assert detect_language(llm, "fake-model", pages) == "pt"
    assert "texto 0" in llm.calls[0].parts[0].text and llm.calls[0].purpose == "ingest.detect_language"


def test_detect_language_empty_pages_is_none():
    assert detect_language(FakeLLM({}), "fake-model", []) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_extract.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `detect_language.py`**

```python
from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import Page
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

SAMPLE_PAGES = 3
SAMPLE_CHARS = 6000


class DetectedLanguage(BaseModel):
    code: str = Field(description="ISO 639-1 two-letter code, or 'und'")
    name: str = Field(description="English name of the language")


def detect_language(llm: LLMProvider, model: str, pages: Sequence[Page]) -> str | None:
    """Two-letter code of the dominant body-text language, from a sample of the first pages."""
    sample = "\n\n".join(page.text for page in pages[:SAMPLE_PAGES])[:SAMPLE_CHARS].strip()
    if not sample:
        return None
    request = StructuredRequest(
        purpose="ingest.detect_language", model=model, system=load_prompt("detect_language"),
        parts=(ContentPart.of_text(sample),), max_tokens=256, effort="low",
    )
    return llm.generate_structured(request, DetectedLanguage).output.code.lower()
```

- [ ] **Step 4: Write `extract.py`**

```python
from __future__ import annotations

from pydantic import BaseModel

from teachme.domain.models import Figure, Page
from teachme.ingestion.errors import TooManyPages, UnsupportedMediaType
from teachme.ingestion.pdf_pages import page_count, split_pdf
from teachme.ingestion.read_pages import read_image, read_pdf_batch
from teachme.ports.llm import LLMProvider
from teachme.settings import Settings

TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
PDF_TYPE = "application/pdf"


class Extraction(BaseModel):
    pages: list[Page]
    figures: list[Figure]
    vision_pages: int


def extract(
    llm: LLMProvider, settings: Settings, data: bytes, media_type: str, language_hint: str | None
) -> Extraction:
    """Dispatch on media type. Every PDF and image page goes through the model so figures are
    described; text files become one page without a model call."""
    if media_type == PDF_TYPE:
        total = page_count(data)
        if total > settings.max_pages_per_source:
            raise TooManyPages(f"{total} pages exceeds MAX_PAGES_PER_SOURCE={settings.max_pages_per_source}")
        pages: list[Page] = []
        figures: list[Figure] = []
        for batch in split_pdf(data, settings.pages_per_read_batch):
            batch_pages, batch_figures = read_pdf_batch(llm, settings.model_read_pages, batch, language_hint)
            pages.extend(batch_pages)
            figures.extend(batch_figures)
        return Extraction(pages=pages, figures=figures, vision_pages=total)
    if media_type in IMAGE_TYPES:
        pages, figures = read_image(llm, settings.model_read_pages, data, media_type, page_index=0,
                                    language_hint=language_hint)
        return Extraction(pages=pages, figures=figures, vision_pages=1)
    if media_type in TEXT_TYPES:
        text = data.decode("utf-8", errors="replace").strip()
        return Extraction(pages=[Page(page_index=0, printed_number=None, text=text)], figures=[], vision_pages=0)
    raise UnsupportedMediaType(f"cannot extract {media_type!r}")
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_extract.py`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add api/teachme/ingestion/extract.py api/teachme/ingestion/detect_language.py api/tests/ingestion/test_extract.py
git commit -m "feat: extraction dispatch and language detection"
```

---

### Task 25: Contextual chunking with coverage validation

**Files:**
- Create: `api/teachme/ingestion/contextualize.py`
- Test: `api/tests/ingestion/test_contextualize.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import re

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Chunk, Page
from teachme.ingestion.contextualize import (
    ChunkOut,
    ChunksOut,
    batch_pages,
    contextualize,
    render_pages,
    validate_coverage,
)
from teachme.ingestion.errors import CoverageError


def _pages(n):
    return [Page(page_index=i, printed_number=str(i + 1), text=f"Text of page {i}.") for i in range(n)]


def _one_chunk_per_page(req):
    body = req.parts[0].text
    batch = body.split("<batch>")[1].split("</batch>")[0]
    indices = [int(m) for m in re.findall(r'<page index="(\d+)"', batch)]
    return ChunksOut(chunks=[
        ChunkOut(context=f"ctx {i}", original_text=f"Text of page {i}.", page_start=i, page_end=i) for i in indices
    ])


def test_batch_pages():
    assert [[p.page_index for p in b] for b in batch_pages(_pages(5), 2)] == [[0, 1], [2, 3], [4]]


def test_render_pages_wraps_with_tags():
    rendered = render_pages(_pages(1))
    assert rendered == '<page index="0" printed="1">\nText of page 0.\n</page>'


def test_validate_coverage_reports_missing_pages():
    chunks = [Chunk(context="c", text="t", page_start=0, page_end=1)]
    validate_coverage(_pages(2), chunks)
    with pytest.raises(CoverageError, match="2"):
        validate_coverage(_pages(3), chunks)


def test_contextualize_includes_neighbours_and_returns_domain_chunks():
    llm = FakeLLM({ChunksOut: _one_chunk_per_page})
    chunks = contextualize(llm, "fake-model", "Geo", "ch1.pdf", "en", _pages(5), pages_per_batch=2)
    assert [(c.page_start, c.page_end) for c in chunks] == [(i, i) for i in range(5)]
    assert chunks[2].content == "ctx 2\n\nText of page 2."
    second_call = llm.calls[1].parts[0].text
    assert "<context_before>" in second_call and 'index="1"' in second_call.split("<batch>")[0]
    assert "<context_after>" in second_call and 'index="4"' in second_call.split("</batch>")[1]
    assert "Geo" in llm.calls[0].system and "ch1.pdf" in llm.calls[0].system
    assert llm.calls[0].purpose == "ingest.contextualize"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_contextualize.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `contextualize.py`**

```python
from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import Chunk, Page
from teachme.ingestion.errors import CoverageError
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

CHUNK_MAX_TOKENS = 32000


class ChunkOut(BaseModel):
    context: str = Field(description="50-100 tokens situating the chunk within the source, in the source language")
    original_text: str = Field(description="Verbatim text from the batch pages, unchanged")
    page_start: int = Field(ge=0, description="index attribute of the first page this text spans")
    page_end: int = Field(ge=0, description="index attribute of the last page this text spans")


class ChunksOut(BaseModel):
    chunks: list[ChunkOut]


def batch_pages(pages: Sequence[Page], pages_per_batch: int) -> list[list[Page]]:
    return [list(pages[i : i + pages_per_batch]) for i in range(0, len(pages), pages_per_batch)]


def render_pages(pages: Sequence[Page]) -> str:
    return "\n".join(
        f'<page index="{p.page_index}" printed="{p.printed_number or ""}">\n{p.text}\n</page>' for p in pages
    )


def validate_coverage(pages: Sequence[Page], chunks: Sequence[Chunk]) -> None:
    """Every page index must fall inside at least one chunk's page range."""
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.page_start, chunk.page_end + 1))
    missing = sorted(p.page_index for p in pages if p.page_index not in covered)
    if missing:
        raise CoverageError(f"pages not covered by any chunk: {missing}")


def contextualize(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    source_title: str,
    language: str | None,
    pages: Sequence[Page],
    pages_per_batch: int,
) -> list[Chunk]:
    system = load_prompt("contextualize").format(subject=subject_name, source=source_title)
    batches = batch_pages(pages, pages_per_batch)
    chunks: list[Chunk] = []
    for position, batch in enumerate(batches):
        before = batches[position - 1][-1:] if position > 0 else []
        after = batches[position + 1][:1] if position + 1 < len(batches) else []
        chunks.extend(_contextualize_batch(llm, model, system, language, batch, before, after))
    validate_coverage(pages, chunks)
    return chunks


def _contextualize_batch(
    llm: LLMProvider,
    model: str,
    system: str,
    language: str | None,
    batch: Sequence[Page],
    before: Sequence[Page],
    after: Sequence[Page],
) -> list[Chunk]:
    body = ""
    if before:
        body += f"<context_before>\n{render_pages(before)}\n</context_before>\n"
    body += f"<batch>\n{render_pages(batch)}\n</batch>\n"
    if after:
        body += f"<context_after>\n{render_pages(after)}\n</context_after>\n"
    body += f"\nThe source language is {language or 'unknown'}. Chunk every page inside <batch>."
    request = StructuredRequest(
        purpose="ingest.contextualize", model=model, system=system, parts=(ContentPart.of_text(body),),
        max_tokens=CHUNK_MAX_TOKENS, effort="medium",
    )
    output = llm.generate_structured(request, ChunksOut).output
    first, last = batch[0].page_index, batch[-1].page_index
    result: list[Chunk] = []
    for out in output.chunks:
        start = min(max(out.page_start, first), last)
        end = min(max(out.page_end, start), last)
        result.append(Chunk(context=out.context.strip(), text=out.original_text.strip(), page_start=start, page_end=end))
    validate_coverage(batch, result)
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_contextualize.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/ingestion/contextualize.py api/tests/ingestion/test_contextualize.py
git commit -m "feat: contextual chunking with page ranges and coverage validation"
```

---

### Task 26: Indexing, cost estimate, and fake responders for the whole pipeline

**Files:**
- Create: `api/teachme/ingestion/index.py`, `api/teachme/ingestion/estimate.py`, `api/teachme/ingestion/fake_responders.py`
- Test: `api/tests/ingestion/test_index_estimate.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from uuid import uuid4

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import Chunk, Page
from teachme.ingestion.contextualize import ChunksOut, contextualize
from teachme.ingestion.detect_language import DetectedLanguage, detect_language
from teachme.ingestion.estimate import estimate_ingest
from teachme.ingestion.fake_responders import default_responders
from teachme.ingestion.index import index_chunks
from teachme.ingestion.pdf_pages import PdfBatch
from teachme.ingestion.read_pages import ReadPagesOutput, read_pdf_batch
from teachme.telemetry.prices import ModelPrice, PriceTable


def test_index_chunks_embeds_tokenizes_and_replaces_previous():
    embedder = FakeEmbedder(dimension=16)
    search = InMemoryChunkSearch(dimension=16)
    source_id, subject_id = uuid4(), uuid4()
    chunks = [Chunk(context="ctx", text="The biosphere and the atmosphere", page_start=0, page_end=0)]
    records = index_chunks(embedder, search, source_id, subject_id, chunks, language_code="en")
    assert len(records) == 1 and records[0].embedding_model == "fake-embed"
    assert set(records[0].tokens) == {"ctx", "biosphere", "atmosphere"}
    assert search.count(subject_id) == 1
    index_chunks(embedder, search, source_id, subject_id, chunks * 2, language_code="en")
    assert search.count(subject_id) == 2


def test_estimate_scales_with_pages():
    table = PriceTable({"m": ModelPrice(input_per_m=10, output_per_m=10)})
    small = estimate_ingest(page_count=10, model="m", prices=table)
    large = estimate_ingest(page_count=20, model="m", prices=table)
    assert large.cost_usd == 2 * small.cost_usd > 0
    assert small.page_count == 10 and small.input_tokens > small.output_tokens > 0


def test_default_responders_drive_every_ingestion_schema():
    llm = FakeLLM(default_responders())
    pages, figures = read_pdf_batch(llm, "fake-model", PdfBatch(first_index=3, last_index=4, data=b"%PDF"), None)
    assert [p.page_index for p in pages] == [3, 4] and len(figures) == 1
    assert detect_language(llm, "fake-model", pages) == "en"
    chunks = contextualize(llm, "fake-model", "S", "f.pdf", "en", pages, pages_per_batch=1)
    assert [c.page_start for c in chunks] == [3, 4]
    assert {ReadPagesOutput, DetectedLanguage, ChunksOut} <= set(default_responders())
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_index_estimate.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `index.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from teachme.domain.models import Chunk, ChunkRecord
from teachme.domain.text.normalize import tokenize
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder

EMBED_BATCH = 128


def index_chunks(
    embedder: Embedder,
    search: ChunkSearch,
    source_id: UUID,
    subject_id: UUID,
    chunks: Sequence[Chunk],
    language_code: str | None,
) -> list[ChunkRecord]:
    """Embed and write chunks, replacing whatever the source had before. Returns the records
    so the bundle can store the vectors."""
    records: list[ChunkRecord] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vectors = embedder.embed_documents([c.content for c in batch]).vectors
        for chunk, vector in zip(batch, vectors, strict=True):
            records.append(
                ChunkRecord(
                    id=uuid4(), source_id=source_id, subject_id=subject_id, chunk=chunk, embedding=tuple(vector),
                    embedding_model=embedder.model, tokens=tuple(tokenize(chunk.content, language_code or "")),
                )
            )
    search.delete_by_source(source_id)
    search.upsert(records)
    return records
```

- [ ] **Step 4: Write `estimate.py`**

```python
from __future__ import annotations

from pydantic import BaseModel

from teachme.telemetry.prices import PriceTable

# Rough per-page figures for a dense textbook page read as a PDF document block (text + image)
# and then re-emitted as Markdown, followed by contextual chunking of that text.
READ_INPUT_PER_PAGE = 2500
READ_OUTPUT_PER_PAGE = 700
CHUNK_INPUT_PER_PAGE = 1200
CHUNK_OUTPUT_PER_PAGE = 900


class IngestEstimate(BaseModel):
    page_count: int
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def describe(self) -> str:
        return (
            f"{self.page_count} pages via {self.model}: about {self.input_tokens:,} input and "
            f"{self.output_tokens:,} output tokens, roughly ${self.cost_usd:.2f}"
        )


def estimate_ingest(*, page_count: int, model: str, prices: PriceTable) -> IngestEstimate:
    input_tokens = page_count * (READ_INPUT_PER_PAGE + CHUNK_INPUT_PER_PAGE)
    output_tokens = page_count * (READ_OUTPUT_PER_PAGE + CHUNK_OUTPUT_PER_PAGE)
    price = prices.price_for(model)
    cost = 0.0
    if price is not None:
        cost = (input_tokens * price.input_per_m + output_tokens * price.output_per_m) / 1_000_000
    return IngestEstimate(
        page_count=page_count, model=model, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost
    )
```

- [ ] **Step 5: Write `fake_responders.py`**

```python
from __future__ import annotations

import re

from pydantic import BaseModel

from teachme.adapters.llm.fake import Responder
from teachme.ingestion.contextualize import ChunkOut, ChunksOut
from teachme.ingestion.detect_language import DetectedLanguage
from teachme.ingestion.read_pages import ReadFigure, ReadPage, ReadPagesOutput
from teachme.ports.llm import StructuredRequest

_COUNT = re.compile(r"exactly (\d+) pages")
_PAGE_TAG = re.compile(r'<page index="(\d+)" printed="[^"]*">\n(.*?)\n</page>', re.DOTALL)


def _read_pages(request: StructuredRequest) -> BaseModel:
    text_part = next(p for p in request.parts if p.kind == "text")
    count = int(_COUNT.search(text_part.text or "").group(1))
    pages = []
    for offset in range(count):
        figures = [ReadFigure(kind="map", caption="Fake map", description="A fake map for tests.")] if offset == 0 else []
        pages.append(ReadPage(page_offset=offset, printed_number=str(offset + 1),
                              text_markdown=f"Fake text of page offset {offset}.", figures=figures))
    return ReadPagesOutput(pages=pages)


def _detect_language(request: StructuredRequest) -> BaseModel:
    return DetectedLanguage(code="en", name="English")


def _contextualize(request: StructuredRequest) -> BaseModel:
    body = request.parts[0].text or ""
    batch = body.split("<batch>")[1].split("</batch>")[0]
    chunks = [
        ChunkOut(context=f"Fake context for page {index}.", original_text=text.strip(),
                 page_start=int(index), page_end=int(index))
        for index, text in _PAGE_TAG.findall(batch)
    ]
    return ChunksOut(chunks=chunks)


def default_responders() -> dict[type[BaseModel], Responder]:
    """Responders for every ingestion schema, so the pipeline runs end to end without a key."""
    return {ReadPagesOutput: _read_pages, DetectedLanguage: _detect_language, ChunksOut: _contextualize}
```

- [ ] **Step 6: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_index_estimate.py`
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add api/teachme/ingestion/index.py api/teachme/ingestion/estimate.py api/teachme/ingestion/fake_responders.py api/tests/ingestion/test_index_estimate.py
git commit -m "feat: chunk indexing, ingest cost estimate, fake responders"
```

---

### Task 27: The resumable ingestion pipeline

**Files:**
- Create: `api/teachme/ingestion/pipeline.py`
- Test: `api/tests/ingestion/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import SourceStatus, SubjectState
from teachme.ingestion.bundle import BundleReader, bundle_slug
from teachme.ingestion.contextualize import ChunksOut
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.fake_responders import default_responders
from teachme.ingestion.pipeline import IngestionPipeline, PipelineDeps
from teachme.repositories.figures import FigureRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from teachme.telemetry.prices import PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder
from tests.helpers import make_pdf


@pytest.fixture
def env(db):
    settings = Settings(_env_file=None, llm_provider="fake", embeddings_provider="fake", pages_per_read_batch=2,
                        pages_per_chunk_batch=2)
    files = InMemoryFileStore()
    recorder = UsageRecorder(UsageRepository(db), PriceTable())
    fake_llm = FakeLLM(default_responders())
    deps = PipelineDeps(
        conn=db, settings=settings,
        llm=RecordingLLM(fake_llm, recorder),
        embedder=RecordingEmbedder(FakeEmbedder(dimension=1024), recorder),
        search=PgVectorChunkSearch(db), files=files,
        bundle_stores=[PrefixedFileStore(files, "digest/")],
        subjects=SubjectRepository(db), sources=SourceRepository(db),
        pages=PageRepository(db), figures=FigureRepository(db),
    )
    subject = deps.subjects.create("Geo", ["en"])
    pdf = make_pdf(5)
    files.put("sources/x/ch1.pdf", pdf, "application/pdf")
    source = deps.sources.create(subject.id, "ch1.pdf", "application/pdf", "sources/x/ch1.pdf", len(pdf))
    db.commit()
    return deps, subject, source, fake_llm


def test_full_run_ends_ready_with_pages_chunks_bundle_and_usage(env):
    deps, subject, source, _ = env
    result = IngestionPipeline(deps).ingest_source(source.id)
    assert result.status == SourceStatus.READY and result.page_count == 5 and result.vision_pages == 5
    assert result.detected_language == "en"
    assert len(deps.pages.list(source.id)) == 5
    assert len(deps.figures.list(source.id)) == 3  # one per read batch of 2,2,1
    assert deps.search.count(subject.id) == 5

    reader = BundleReader(deps.bundle_stores[0], f"{bundle_slug('Geo', subject.id)}/{bundle_slug('ch1.pdf', source.id)}")
    assert reader.meta().page_count == 5 and reader.meta().embedding_model == "fake-embed"
    assert len(reader.pages()) == 5 and len(reader.chunks()) == 5 and len(reader.embeddings()) == 5

    usage = UsageRepository(deps.conn).summarize(subject_id=subject.id)
    purposes = {row["purpose"] for row in usage}
    assert {"ingest.read_pages", "ingest.detect_language", "ingest.contextualize", "embed.documents"} <= purposes
    assert all(row["source_id"] == source.id for row in deps.conn.execute(
        "SELECT source_id FROM llm_usage").fetchall())


def test_failure_records_resume_point_and_rerun_skips_extraction(env):
    deps, subject, source, fake_llm = env
    calls = {"n": 0}
    good = default_responders()[ChunksOut]

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("upstream hiccup")
        return good(request)

    fake_llm._responders[ChunksOut] = flaky
    pipeline = IngestionPipeline(deps)
    with pytest.raises(RuntimeError):
        pipeline.ingest_source(source.id)
    failed = deps.sources.get(source.id)
    assert failed.status == SourceStatus.FAILED and failed.resume_status == SourceStatus.CHUNKING
    assert "upstream hiccup" in failed.error
    read_calls_before = sum(1 for r in fake_llm.calls if r.purpose == "ingest.read_pages")

    result = pipeline.ingest_source(source.id)
    assert result.status == SourceStatus.READY
    read_calls_after = sum(1 for r in fake_llm.calls if r.purpose == "ingest.read_pages")
    assert read_calls_after == read_calls_before  # pages were reused, not re-read


def test_published_subject_is_locked(env):
    deps, subject, source, _ = env
    deps.subjects.set_state(subject.id, SubjectState.PUBLISHED)
    deps.conn.commit()
    with pytest.raises(SubjectLocked):
        IngestionPipeline(deps).ingest_source(source.id)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/ingestion/test_pipeline.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `pipeline.py`**

```python
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from teachme.domain.models import Chunk, Source, SourceStatus, Subject, SubjectState
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug
from teachme.ingestion.contextualize import contextualize
from teachme.ingestion.detect_language import detect_language
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.extract import extract
from teachme.ingestion.index import index_chunks
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.embeddings import Embedder
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMProvider
from teachme.repositories.figures import FigureRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings
from teachme.telemetry.usage import usage_context

log = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    conn: psycopg.Connection
    settings: Settings
    llm: LLMProvider
    embedder: Embedder
    search: ChunkSearch
    files: FileStore
    bundle_stores: Sequence[FileStore]  # first one is the primary store; resume reads from it
    subjects: SubjectRepository
    sources: SourceRepository
    pages: PageRepository
    figures: FigureRepository


class IngestionPipeline:
    """uploaded -> extracting -> chunking -> indexing -> ready, resumable from the recorded status.

    Each step commits when its outputs are persisted. On failure the source is marked FAILED with
    resume_status = the step that failed, and re-running continues from there. Chunks are recovered
    from the bundle when resuming from INDEXING, so no model call is repeated."""

    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps

    def ingest_source(self, source_id: UUID) -> Source:
        source = self.d.sources.get(source_id)
        subject = self.d.subjects.get(source.subject_id)
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before ingesting")

        bundle = BundleWriter(self.d.bundle_stores, bundle_slug(subject.name, subject.id))
        source_slug = bundle_slug(source.filename, source.id)
        step = self._resume_point(source)
        with usage_context(subject_id=subject.id, source_id=source.id):
            try:
                if step in (SourceStatus.UPLOADED, SourceStatus.EXTRACTING):
                    step = SourceStatus.EXTRACTING
                    self._extract(source, subject, bundle, source_slug)
                    step = SourceStatus.CHUNKING
                if step == SourceStatus.CHUNKING:
                    chunks = self._chunk(source, subject, bundle, source_slug)
                    step = SourceStatus.INDEXING
                else:
                    chunks = None
                if step == SourceStatus.INDEXING:
                    self._index(source, subject, bundle, source_slug, chunks)
            except Exception as exc:
                log.exception("ingestion of %s failed during %s", source.id, step.value)
                self.d.sources.set_status(
                    source.id, SourceStatus.FAILED, error=f"{type(exc).__name__}: {exc}", resume_status=step
                )
                self.d.conn.commit()
                raise
        return self.d.sources.get(source.id)

    @staticmethod
    def _resume_point(source: Source) -> SourceStatus:
        if source.status == SourceStatus.FAILED:
            return source.resume_status or SourceStatus.UPLOADED
        if source.status == SourceStatus.READY:
            return SourceStatus.UPLOADED  # explicit re-ingest starts over
        return source.status

    def _extract(self, source: Source, subject: Subject, bundle: BundleWriter, source_slug: str) -> None:
        self.d.sources.set_status(source.id, SourceStatus.EXTRACTING)
        self.d.conn.commit()
        data = self.d.files.get(source.file_key)
        extraction = extract(self.d.llm, self.d.settings, data, source.media_type, language_hint=None)
        language = detect_language(self.d.llm, self.d.settings.model_detect_language, extraction.pages)

        self.d.pages.replace(source.id, extraction.pages)
        self.d.figures.replace(source.id, extraction.figures)
        self.d.sources.set_extraction_result(
            source.id, page_count=len(extraction.pages), vision_pages=extraction.vision_pages,
            detected_language=language,
        )
        bundle.write_meta(source_slug, self._meta(source, len(extraction.pages), extraction.vision_pages, language))
        bundle.write_pages(source_slug, extraction.pages)
        bundle.write_figures(source_slug, extraction.figures)
        self.d.sources.set_status(source.id, SourceStatus.CHUNKING)
        self.d.conn.commit()

    def _chunk(self, source: Source, subject: Subject, bundle: BundleWriter, source_slug: str) -> list[Chunk]:
        self.d.sources.set_status(source.id, SourceStatus.CHUNKING)
        self.d.conn.commit()
        current = self.d.sources.get(source.id)
        pages = self.d.pages.list(source.id)
        chunks = contextualize(
            self.d.llm, self.d.settings.model_contextualize, subject.name, source.filename,
            current.detected_language, pages, self.d.settings.pages_per_chunk_batch,
        )
        bundle.write_chunks(source_slug, chunks)
        self.d.sources.set_status(source.id, SourceStatus.INDEXING)
        self.d.conn.commit()
        return chunks

    def _index(
        self, source: Source, subject: Subject, bundle: BundleWriter, source_slug: str, chunks: list[Chunk] | None
    ) -> None:
        self.d.sources.set_status(source.id, SourceStatus.INDEXING)
        self.d.conn.commit()
        current = self.d.sources.get(source.id)
        if chunks is None:
            reader = BundleReader(self.d.bundle_stores[0], bundle.prefix(source_slug))
            if not reader.has_chunks():
                chunks = self._chunk(source, subject, bundle, source_slug)
            else:
                chunks = reader.chunks()
        records = index_chunks(
            self.d.embedder, self.d.search, source.id, subject.id, chunks, language_code=current.detected_language
        )
        bundle.write_embeddings(source_slug, records)
        bundle.write_meta(
            source_slug,
            self._meta(current, current.page_count or 0, current.vision_pages or 0, current.detected_language),
        )
        self.d.sources.set_status(source.id, SourceStatus.READY)
        self.d.conn.commit()

    def _meta(self, source: Source, page_count: int, vision_pages: int, language: str | None) -> SourceMeta:
        s = self.d.settings
        return SourceMeta(
            source_id=source.id, filename=source.filename, media_type=source.media_type, size=source.size,
            page_count=page_count, vision_pages=vision_pages, language=language,
            models={"read_pages": s.model_read_pages, "detect_language": s.model_detect_language,
                    "contextualize": s.model_contextualize},
            embedding_model=self.d.embedder.model,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/ingestion/test_pipeline.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/ingestion/pipeline.py api/tests/ingestion/test_pipeline.py
git commit -m "feat: resumable ingestion pipeline with bundle and usage recording"
```

---

## Phase H: Composition root, services and CLI

### Task 28: Container (composition root)

**Files:**
- Create: `api/teachme/container.py`
- Test: `api/tests/test_container.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from teachme.container import ConfigurationError, Container
from teachme.settings import Settings


def _settings(migrated_database, tmp_path, **overrides):
    base = dict(
        database_url=migrated_database, llm_provider="fake", embeddings_provider="fake", reranker_provider="noop",
        file_store="local", local_files_dir=tmp_path / "files", digest_dir=tmp_path / "digest",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_container_builds_fake_stack_and_is_ready(migrated_database, tmp_path):
    container = Container(_settings(migrated_database, tmp_path))
    container.check_ready()
    assert container.llm.name == "fake" and container.embedder.model == "fake-embed"
    assert container.files.name == "local" and container.job_runner.name == "inprocess"
    assert [s.name for s in container.bundle_stores] == ["local:digest/", "local"]
    assert container.pipeline is container.pipeline  # cached
    container.close()


def test_s3_without_bucket_is_a_configuration_error(migrated_database, tmp_path):
    container = Container(_settings(migrated_database, tmp_path, file_store="s3"))
    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        _ = container.files


def test_dimension_mismatch_is_a_configuration_error(migrated_database, tmp_path, monkeypatch):
    container = Container(_settings(migrated_database, tmp_path))
    monkeypatch.setattr(container.embedder, "dimension", 8)
    with pytest.raises(ConfigurationError, match="dimension"):
        container.check_ready()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/test_container.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `container.py`**

```python
from __future__ import annotations

from functools import cached_property
from uuid import UUID

import psycopg

from teachme.adapters.chunk_search.pgvector import PgVectorChunkSearch
from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import ensure_schema_current
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.embeddings.voyage import VoyageEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.adapters.file_store.s3 import S3FileStore
from teachme.adapters.file_store.vercel_blob import VercelBlobFileStore
from teachme.adapters.job_runner.inprocess import InProcessJobRunner
from teachme.adapters.job_runner.sqs import SqsJobRunner
from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.adapters.llm.fake import FakeLLM
from teachme.adapters.reranker.noop import NoopReranker
from teachme.adapters.reranker.voyage import VoyageReranker
from teachme.ingestion.fake_responders import default_responders
from teachme.ingestion.pipeline import IngestionPipeline, PipelineDeps
from teachme.ports.embeddings import Embedder
from teachme.ports.file_store import FileStore
from teachme.ports.job_runner import JobPayload, JobRunner
from teachme.ports.llm import LLMProvider
from teachme.ports.reranker import Reranker
from teachme.repositories.figures import FigureRepository
from teachme.repositories.jobs import JobRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.repositories.usage import UsageRepository
from teachme.retrieval.hybrid import HybridSearch
from teachme.services.export_import import ExportImportService
from teachme.services.sources import SourceService
from teachme.services.subjects import SubjectService
from teachme.services.usage import UsageService
from teachme.settings import Settings
from teachme.telemetry.prices import PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder


class ConfigurationError(Exception):
    pass


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM()
    return FakeLLM(default_responders())


def build_embedder(settings: Settings) -> Embedder:
    if settings.embeddings_provider == "voyage":
        return VoyageEmbedder(model=settings.embedding_model)
    return FakeEmbedder()


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker_provider == "voyage":
        return VoyageReranker(model=settings.rerank_model)
    return NoopReranker()


def build_file_store(settings: Settings) -> FileStore:
    if settings.file_store == "local":
        return LocalFileStore(settings.local_files_dir)
    if settings.file_store == "vercel_blob":
        return VercelBlobFileStore(prefix=settings.blob_prefix)
    if not settings.s3_bucket:
        raise ConfigurationError("FILE_STORE=s3 requires S3_BUCKET")
    return S3FileStore(bucket=settings.s3_bucket, region=settings.aws_region)


class Container:
    """Builds every adapter, repository and service once from Settings. The only place that
    knows which concrete class stands behind each port."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # infrastructure -------------------------------------------------------------------------
    @cached_property
    def conn(self) -> psycopg.Connection:
        return connect(self.settings.database_url)

    @cached_property
    def prices(self) -> PriceTable:
        return PriceTable()

    @cached_property
    def usage_recorder(self) -> UsageRecorder:
        return UsageRecorder(self.usage_repo, self.prices)

    @cached_property
    def llm(self) -> LLMProvider:
        return RecordingLLM(build_llm(self.settings), self.usage_recorder)

    @cached_property
    def embedder(self) -> Embedder:
        return RecordingEmbedder(build_embedder(self.settings), self.usage_recorder)

    @cached_property
    def reranker(self) -> Reranker:
        return build_reranker(self.settings)

    @cached_property
    def files(self) -> FileStore:
        return build_file_store(self.settings)

    @cached_property
    def bundle_stores(self) -> list[FileStore]:
        stores: list[FileStore] = [PrefixedFileStore(self.files, "digest/")]
        if self.settings.write_local_bundle:
            stores.append(LocalFileStore(self.settings.digest_dir))
        return stores

    @cached_property
    def search(self) -> PgVectorChunkSearch:
        return PgVectorChunkSearch(self.conn)

    # repositories ---------------------------------------------------------------------------
    @cached_property
    def subjects(self) -> SubjectRepository:
        return SubjectRepository(self.conn)

    @cached_property
    def sources(self) -> SourceRepository:
        return SourceRepository(self.conn)

    @cached_property
    def pages(self) -> PageRepository:
        return PageRepository(self.conn)

    @cached_property
    def figures(self) -> FigureRepository:
        return FigureRepository(self.conn)

    @cached_property
    def jobs(self) -> JobRepository:
        return JobRepository(self.conn)

    @cached_property
    def usage_repo(self) -> UsageRepository:
        return UsageRepository(self.conn)

    # pipeline, jobs, services ---------------------------------------------------------------
    @cached_property
    def pipeline_deps(self) -> PipelineDeps:
        return PipelineDeps(
            conn=self.conn, settings=self.settings, llm=self.llm, embedder=self.embedder, search=self.search,
            files=self.files, bundle_stores=self.bundle_stores, subjects=self.subjects, sources=self.sources,
            pages=self.pages, figures=self.figures,
        )

    @cached_property
    def pipeline(self) -> IngestionPipeline:
        return IngestionPipeline(self.pipeline_deps)

    def _ingest_job(self, payload: JobPayload) -> None:
        self.pipeline.ingest_source(UUID(payload["source_id"]))

    @cached_property
    def job_runner(self) -> JobRunner:
        if self.settings.job_runner == "sqs":
            if not self.settings.sqs_queue_url:
                raise ConfigurationError("JOB_RUNNER=sqs requires SQS_QUEUE_URL")
            return SqsJobRunner(self.settings.sqs_queue_url, self.settings.aws_region, jobs=self.jobs)
        return InProcessJobRunner({"ingest_source": self._ingest_job}, jobs=self.jobs)

    @cached_property
    def subject_service(self) -> SubjectService:
        return SubjectService(self.conn, self.subjects, self.settings)

    @cached_property
    def source_service(self) -> SourceService:
        return SourceService(
            self.conn, self.settings, self.llm, self.files, self.search, self.sources, self.subjects
        )

    @cached_property
    def usage_service(self) -> UsageService:
        return UsageService(self.usage_repo)

    @cached_property
    def export_import(self) -> ExportImportService:
        return ExportImportService(self.pipeline_deps)

    @cached_property
    def hybrid_search(self) -> HybridSearch:
        return HybridSearch(self.embedder, self.search, self.reranker)

    # lifecycle ------------------------------------------------------------------------------
    def check_ready(self) -> None:
        """Fail fast with a named reason instead of on the first request."""
        ensure_schema_current(self.conn)
        expected = self.search.dimension()
        if self.embedder.dimension != expected:
            raise ConfigurationError(
                f"embedder {self.embedder.model!r} has dimension {self.embedder.dimension}, "
                f"chunks table expects {expected}"
            )

    def close(self) -> None:
        if "conn" in self.__dict__:
            self.conn.close()
```

- [ ] **Step 4: Run to verify it fails for the right reason now**

Run: `pytest -q api/tests/test_container.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'teachme.services'` (the services are Task 29). Continue to Task 29 before committing; this task's commit is in Task 29 Step 8.

---

### Task 29: Subject, source and usage services

**Files:**
- Create: `api/teachme/services/__init__.py`, `subjects.py`, `sources.py`, `usage.py`, `export_import.py` (stub here, full in Task 30)
- Test: `api/tests/services/test_subjects_sources.py`

- [ ] **Step 1: Write the failing test** (`api/tests/services/__init__.py` empty)

```python
from __future__ import annotations

import pytest

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import SourceStatus, SubjectState
from teachme.ingestion.errors import SubjectLocked, UnsupportedMediaType
from teachme.repositories.errors import SubjectNotFound
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.services.sources import SourceService
from teachme.services.subjects import LanguageNotEnabled, SubjectService
from teachme.settings import Settings
from tests.helpers import make_pdf


@pytest.fixture
def services(db):
    settings = Settings(_env_file=None, llm_provider="fake")
    subjects = SubjectRepository(db)
    files = InMemoryFileStore()
    search = InMemoryChunkSearch()
    subject_service = SubjectService(db, subjects, settings)
    source_service = SourceService(db, settings, FakeLLM({}), files, search, SourceRepository(db), subjects)
    return subject_service, source_service, files, search


def test_subject_get_or_create_and_language_check(services):
    subject_service, *_ = services
    a = subject_service.get_or_create("Geo", ["he", "pt"])
    assert a.languages == ("he", "pt") and a.state == SubjectState.DRAFT
    assert subject_service.get_or_create("Geo") == a
    assert subject_service.require("Geo") == a
    with pytest.raises(SubjectNotFound):
        subject_service.require("Nope")
    with pytest.raises(LanguageNotEnabled):
        subject_service.get_or_create("Chem", ["fr"])


def test_source_register_validates_type_and_stores_file(services):
    subject_service, source_service, files, _ = services
    subject = subject_service.get_or_create("Geo")
    assert source_service.media_type_for("notes.md") == "text/markdown"
    assert source_service.media_type_for("ch1.PDF") == "application/pdf"
    assert source_service.media_type_for("weird.xyz") is None
    source = source_service.register(subject, "ch1.pdf", make_pdf(1))
    assert source.status == SourceStatus.UPLOADED and files.exists(source.file_key)
    assert [s.id for s in source_service.list(subject)] == [source.id]
    with pytest.raises(UnsupportedMediaType):
        source_service.register(subject, "archive.zip", b"PK")


def test_settings_can_narrow_accepted_types(db):
    settings = Settings(_env_file=None, llm_provider="fake", allowed_upload_types=["application/pdf"])
    subjects = SubjectRepository(db)
    service = SourceService(db, settings, FakeLLM({}), InMemoryFileStore(), InMemoryChunkSearch(),
                            SourceRepository(db), subjects)
    assert service.accepted_media_types() == frozenset({"application/pdf"})


def test_delete_and_reingest_respect_publish_lock(services):
    subject_service, source_service, files, search = services
    subject = subject_service.get_or_create("Geo")
    source = source_service.register(subject, "ch1.pdf", make_pdf(1))
    source_service.mark_for_reingest(source.id)
    subject_service.set_state(subject, SubjectState.PUBLISHED)
    with pytest.raises(SubjectLocked):
        source_service.delete(source.id)
    subject_service.set_state(subject, SubjectState.DRAFT)
    source_service.delete(source.id)
    assert not files.exists(source.file_key) and source_service.list(subject) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/services/test_subjects_sources.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `services/__init__.py`** (empty) **and `subjects.py`**

```python
from __future__ import annotations

from collections.abc import Sequence

import psycopg

from teachme.domain.models import Subject, SubjectState
from teachme.repositories.errors import SubjectNotFound
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings


class LanguageNotEnabled(ValueError):
    pass


class SubjectService:
    def __init__(self, conn: psycopg.Connection, subjects: SubjectRepository, settings: Settings) -> None:
        self._conn = conn
        self._subjects = subjects
        self._settings = settings

    def get_or_create(
        self, name: str, languages: Sequence[str] | None = None, created_by: str | None = None
    ) -> Subject:
        existing = self._subjects.get_by_name(name)
        if existing:
            return existing
        chosen = list(languages) if languages else list(self._settings.enabled_languages)
        disallowed = [code for code in chosen if code not in self._settings.enabled_languages]
        if disallowed:
            raise LanguageNotEnabled(f"languages not enabled in settings: {disallowed}")
        subject = self._subjects.create(name, chosen, created_by)
        self._conn.commit()
        return subject

    def require(self, name: str) -> Subject:
        subject = self._subjects.get_by_name(name)
        if subject is None:
            raise SubjectNotFound(name)
        return subject

    def list(self) -> list[Subject]:
        return self._subjects.list()

    def set_state(self, subject: Subject, state: SubjectState) -> None:
        self._subjects.set_state(subject.id, state)
        self._conn.commit()
```

- [ ] **Step 4: Write `sources.py`**

```python
from __future__ import annotations

import mimetypes
from uuid import UUID, uuid4

import psycopg

from teachme.domain.models import Source, SourceStatus, Subject, SubjectState
from teachme.ingestion.errors import SubjectLocked, UnsupportedMediaType
from teachme.ports.chunk_search import ChunkSearch
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMProvider
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings

_EXTRA_TYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}


class SourceService:
    """Registers, lists and removes sources. Accepted upload types are what the LLM adapter can
    read, optionally narrowed by ALLOWED_UPLOAD_TYPES, never widened."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        llm: LLMProvider,
        files: FileStore,
        search: ChunkSearch,
        sources: SourceRepository,
        subjects: SubjectRepository,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._llm = llm
        self._files = files
        self._search = search
        self._sources = sources
        self._subjects = subjects

    def accepted_media_types(self) -> frozenset[str]:
        accepted = self._llm.capabilities().media_types
        if self._settings.allowed_upload_types is not None:
            accepted = accepted & frozenset(self._settings.allowed_upload_types)
        return accepted

    @staticmethod
    def media_type_for(filename: str) -> str | None:
        lower = filename.lower()
        for suffix, media_type in _EXTRA_TYPES.items():
            if lower.endswith(suffix):
                return media_type
        guessed, _ = mimetypes.guess_type(lower)
        return guessed

    def register(self, subject: Subject, filename: str, data: bytes) -> Source:
        self._require_draft(subject)
        media_type = self.media_type_for(filename)
        if media_type is None or media_type not in self.accepted_media_types():
            raise UnsupportedMediaType(
                f"{filename!r} ({media_type}) is not accepted; accepted: {sorted(self.accepted_media_types())}"
            )
        key = f"sources/{subject.id}/{uuid4()}/{filename}"
        self._files.put(key, data, media_type)
        source = self._sources.create(subject.id, filename, media_type, key, len(data))
        self._conn.commit()
        return source

    def list(self, subject: Subject) -> list[Source]:
        return self._sources.list_by_subject(subject.id)

    def mark_for_reingest(self, source_id: UUID) -> Source:
        source = self._sources.get(source_id)
        self._require_draft(self._subjects.get(source.subject_id))
        self._sources.set_status(source.id, SourceStatus.UPLOADED)
        self._conn.commit()
        return self._sources.get(source.id)

    def delete(self, source_id: UUID) -> None:
        source = self._sources.get(source_id)
        self._require_draft(self._subjects.get(source.subject_id))
        self._search.delete_by_source(source.id)
        self._files.delete(source.file_key)
        self._sources.delete(source.id)  # pages and figures cascade
        self._conn.commit()

    @staticmethod
    def _require_draft(subject: Subject) -> None:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; sources are locked")
```

- [ ] **Step 5: Write `usage.py`**

```python
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from teachme.repositories.usage import UsageRepository


class UsageSummaryRow(BaseModel):
    purpose: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    avg_latency_ms: int


class UsageService:
    def __init__(self, usage: UsageRepository) -> None:
        self._usage = usage

    def summary(self, subject_id: UUID | None = None) -> list[UsageSummaryRow]:
        return [UsageSummaryRow.model_validate(row) for row in self._usage.summarize(subject_id=subject_id)]

    @staticmethod
    def format_table(rows: list[UsageSummaryRow]) -> str:
        if not rows:
            return "no usage recorded"
        header = f"{'purpose':<26} {'model':<18} {'calls':>6} {'in':>10} {'out':>9} {'cache_rd':>9} {'usd':>9}"
        lines = [header, "-" * len(header)]
        total = 0.0
        for r in rows:
            total += r.cost_usd
            lines.append(
                f"{r.purpose:<26} {r.model:<18} {r.calls:>6} {r.input_tokens:>10,} {r.output_tokens:>9,}"
                f" {r.cache_read_tokens:>9,} {r.cost_usd:>9.4f}"
            )
        lines.append(f"{'total':<26} {'':<18} {'':>6} {'':>10} {'':>9} {'':>9} {total:>9.4f}")
        return "\n".join(lines)
```

- [ ] **Step 6: Write a stub `export_import.py`** so the container imports (filled in Task 30)

```python
from __future__ import annotations

from teachme.ingestion.pipeline import PipelineDeps


class ExportImportService:
    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps
```

- [ ] **Step 7: Run to verify both test files pass**

Run: `pytest -q api/tests/services/test_subjects_sources.py api/tests/test_container.py`
Expected: `7 passed`

- [ ] **Step 8: Commit**

```bash
git add api/teachme/container.py api/teachme/services api/tests/test_container.py api/tests/services
git commit -m "feat: container composition root and subject/source/usage services"
```

---

### Task 30: Export and import of digest bundles

**Files:**
- Modify: `api/teachme/services/export_import.py`
- Test: `api/tests/services/test_export_import.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.container import Container
from teachme.ingestion.bundle import BundleReader
from teachme.adapters.file_store.local import LocalFileStore
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from tests.helpers import make_pdf


def _container(migrated_database, tmp_path, embed_model="fake-embed"):
    settings = Settings(
        _env_file=None, database_url=migrated_database, llm_provider="fake", embeddings_provider="fake",
        reranker_provider="noop", file_store="local", local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest", pages_per_read_batch=2, pages_per_chunk_batch=2,
    )
    container = Container(settings)
    if embed_model != "fake-embed":
        container.__dict__["embedder"] = FakeEmbedder(model=embed_model)
    return container


def _ingested(container, name="Geo"):
    subject = container.subject_service.get_or_create(name)
    source = container.source_service.register(subject, "ch1.pdf", make_pdf(3))
    container.pipeline.ingest_source(source.id)
    return subject, source


def _embed_calls(container):
    return sum(r["calls"] for r in UsageRepository(container.conn).summarize() if r["purpose"] == "embed.documents")


def test_export_writes_bundle_folder(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    reader = BundleReader(LocalFileStore(out), "")
    assert reader.meta().page_count == 3 and len(reader.pages()) == 3
    assert len(reader.chunks()) == 3 and len(reader.embeddings()) == 3
    container.close()


def test_import_reuses_vectors_when_model_matches(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    before = _embed_calls(container)

    target = container.subject_service.get_or_create("Geo copy")
    imported = container.export_import.import_source(target, out)
    assert imported.status.value == "ready" and imported.page_count == 3
    assert container.search.count(target.id) == 3
    assert _embed_calls(container) == before  # no re-embedding
    assert len(container.pages.list(imported.id)) == 3
    container.close()


def test_import_reembeds_when_model_differs(db, migrated_database, tmp_path):
    container = _container(migrated_database, tmp_path)
    subject, source = _ingested(container)
    out = container.export_import.export_source(source.id, tmp_path / "export")
    container.close()

    other = _container(migrated_database, tmp_path, embed_model="fake-embed-v2")
    target = other.subject_service.get_or_create("Geo v2")
    other.export_import.import_source(target, out)
    records = other.search.list_by_source(other.sources.list_by_subject(target.id)[0].id)
    assert {r.embedding_model for r in records} == {"fake-embed-v2"}
    other.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/services/test_export_import.py`
Expected: FAIL with `AttributeError: 'ExportImportService' object has no attribute 'export_source'`

- [ ] **Step 3: Write the full `export_import.py`**

```python
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from teachme.adapters.file_store.local import LocalFileStore
from teachme.domain.models import ChunkRecord, Source, SourceStatus, Subject, SubjectState
from teachme.domain.text.normalize import tokenize
from teachme.ingestion.bundle import BundleReader, BundleWriter, SourceMeta, bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.ingestion.index import index_chunks
from teachme.ingestion.pipeline import PipelineDeps


class ExportImportService:
    """The bundle is the portable artifact; the database is a derived index.
    export: database -> local folder. import: local folder -> database (+ primary bundle store)."""

    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps

    def export_source(self, source_id: UUID, out_root: Path) -> Path:
        source = self.d.sources.get(source_id)
        subject = self.d.subjects.get(source.subject_id)
        subject_slug = bundle_slug(subject.name, subject.id)
        source_slug = bundle_slug(source.filename, source.id)
        writer = BundleWriter([LocalFileStore(out_root)], subject_slug)

        records = self.d.search.list_by_source(source.id)
        embedding_model = records[0].embedding_model if records else None
        writer.write_meta(source_slug, self._meta(source, embedding_model))
        writer.write_pages(source_slug, self.d.pages.list(source.id))
        writer.write_figures(source_slug, self.d.figures.list(source.id))
        writer.write_chunks(source_slug, [r.chunk for r in records])
        if records:
            writer.write_embeddings(source_slug, records)
        return out_root / subject_slug / source_slug

    def import_source(self, subject: Subject, bundle_dir: Path) -> Source:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before importing")
        reader = BundleReader(LocalFileStore(bundle_dir), "")
        meta = reader.meta()
        pages, figures, chunks = reader.pages(), reader.figures(), reader.chunks()

        file_key = f"imported/{meta.source_id}/{meta.filename}"
        source = self.d.sources.create(subject.id, meta.filename, meta.media_type, file_key, meta.size)
        self.d.sources.set_status(source.id, SourceStatus.INDEXING)
        self.d.pages.replace(source.id, pages)
        self.d.figures.replace(source.id, figures)
        self.d.sources.set_extraction_result(
            source.id, page_count=meta.page_count, vision_pages=meta.vision_pages, detected_language=meta.language
        )

        embeddings = reader.embeddings()
        reuse = (
            embeddings is not None
            and meta.embedding_model == self.d.embedder.model
            and len(embeddings) == len(chunks)
        )
        if reuse:
            records = [
                ChunkRecord(
                    id=uuid4(), source_id=source.id, subject_id=subject.id, chunk=chunk,
                    embedding=row.vector, embedding_model=row.model,
                    tokens=tuple(tokenize(chunk.content, meta.language or "")),
                )
                for chunk, row in zip(chunks, embeddings, strict=True)
            ]
            self.d.search.delete_by_source(source.id)
            self.d.search.upsert(records)
        else:
            records = index_chunks(
                self.d.embedder, self.d.search, source.id, subject.id, chunks, language_code=meta.language
            )

        # Mirror the bundle into the primary store so the hosted copy is complete too.
        writer = BundleWriter(self.d.bundle_stores, bundle_slug(subject.name, subject.id))
        source_slug = bundle_slug(source.filename, source.id)
        writer.write_meta(source_slug, self._meta(self.d.sources.get(source.id), records[0].embedding_model if records else None))
        writer.write_pages(source_slug, pages)
        writer.write_figures(source_slug, figures)
        writer.write_chunks(source_slug, chunks)
        if records:
            writer.write_embeddings(source_slug, records)

        self.d.sources.set_status(source.id, SourceStatus.READY)
        self.d.conn.commit()
        return self.d.sources.get(source.id)

    def _meta(self, source: Source, embedding_model: str | None) -> SourceMeta:
        s = self.d.settings
        return SourceMeta(
            source_id=source.id, filename=source.filename, media_type=source.media_type, size=source.size,
            page_count=source.page_count or 0, vision_pages=source.vision_pages or 0,
            language=source.detected_language,
            models={"read_pages": s.model_read_pages, "detect_language": s.model_detect_language,
                    "contextualize": s.model_contextualize},
            embedding_model=embedding_model,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/services/test_export_import.py`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/teachme/services/export_import.py api/tests/services/test_export_import.py
git commit -m "feat: export and import of digest bundles"
```

---

### Task 31: Command-line interface

**Files:**
- Create: `api/teachme/cli/__init__.py`, `api/teachme/cli/main.py`
- Test: `api/tests/cli/test_cli.py`

- [ ] **Step 1: Write the failing test** (`api/tests/cli/__init__.py` empty)

```python
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from teachme.container import Container
from teachme.settings import Settings
from tests.helpers import make_pdf

runner = CliRunner()


@pytest.fixture
def cli(db, migrated_database, tmp_path, monkeypatch):
    import teachme.cli.main as main

    settings = Settings(
        _env_file=None, database_url=migrated_database, llm_provider="fake", embeddings_provider="fake",
        reranker_provider="noop", file_store="local", local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest", pages_per_read_batch=2, pages_per_chunk_batch=2,
    )
    container = Container(settings)
    monkeypatch.setattr(main, "build_container", lambda: container)
    monkeypatch.setattr(container, "close", lambda: None)  # commands call close(); keep it open for the test
    pdf = tmp_path / "ch1.pdf"
    pdf.write_bytes(make_pdf(3))
    yield main.app, pdf, tmp_path
    Container.close(container)


def test_subject_create_and_list(cli):
    app, *_ = cli
    result = runner.invoke(app, ["subject", "create", "Geo", "--languages", "he,en"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["subject", "list"])
    assert "Geo" in result.output and "draft" in result.output and "he,en" in result.output


def test_ingest_export_usage_flow(cli):
    app, pdf, tmp_path = cli
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)])
    assert result.exit_code == 0, result.output
    assert "3 pages" in result.output and "ready" in result.output

    result = runner.invoke(app, ["source", "list", "--subject", "Geo"])
    assert "ch1.pdf" in result.output and "ready" in result.output

    result = runner.invoke(app, ["usage", "--subject", "Geo"])
    assert result.exit_code == 0 and "ingest.read_pages" in result.output

    result = runner.invoke(app, ["export", "--subject", "Geo", "--out", str(tmp_path / "exp")])
    assert result.exit_code == 0, result.output
    exported = [p for p in (tmp_path / "exp").rglob("meta.json")]
    assert len(exported) == 1

    result = runner.invoke(app, ["import", "--subject", "Geo copy", str(exported[0].parent)])
    assert result.exit_code == 0, result.output
    assert "ready" in result.output


def test_ingest_rejects_unknown_type(cli):
    app, pdf, tmp_path = cli
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"PK")
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(bad)])
    assert result.exit_code == 1 and "not accepted" in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest -q api/tests/cli/test_cli.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `cli/__init__.py`** (empty) **and `cli/main.py`**

```python
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

import typer

from teachme.adapters.db.migrate import apply_migrations
from teachme.container import Container
from teachme.domain.models import Source
from teachme.ingestion.estimate import estimate_ingest
from teachme.ingestion.pdf_pages import page_count

app = typer.Typer(no_args_is_help=True, help="teach-me operator commands")
subject_app = typer.Typer(no_args_is_help=True, help="Manage subjects")
source_app = typer.Typer(no_args_is_help=True, help="Manage sources")
app.add_typer(subject_app, name="subject")
app.add_typer(source_app, name="source")


def build_container() -> Container:
    """Patched in tests. One Container per command invocation."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return Container()


def _describe(source: Source) -> str:
    pages = f"{source.page_count} pages" if source.page_count is not None else "pages unknown"
    detail = f", language {source.detected_language}" if source.detected_language else ""
    error = f" error: {source.error}" if source.error else ""
    return f"{source.filename}: {source.status.value} ({pages}{detail}){error}"


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""
    c = build_container()
    applied = apply_migrations(c.conn)
    typer.echo(f"applied: {applied}" if applied else "schema already current")
    c.close()


@subject_app.command("create")
def subject_create(
    name: str,
    languages: str = typer.Option("he,en,pt", help="Comma-separated teaching languages"),
) -> None:
    c = build_container()
    subject = c.subject_service.get_or_create(name, [code.strip() for code in languages.split(",") if code.strip()])
    typer.echo(f"{subject.name} [{subject.state.value}] languages={','.join(subject.languages)} id={subject.id}")
    c.close()


@subject_app.command("list")
def subject_list() -> None:
    c = build_container()
    for subject in c.subject_service.list():
        typer.echo(f"{subject.name} [{subject.state.value}] languages={','.join(subject.languages)} id={subject.id}")
    c.close()


@app.command()
def ingest(
    files: list[Path] = typer.Argument(..., exists=True, readable=True, help="PDF, image or text files"),
    subject: str = typer.Option(..., "--subject", "-s", help="Subject name; created if missing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation"),
) -> None:
    """Register files as sources of a subject and run the ingestion pipeline on each."""
    c = build_container()
    c.check_ready()
    subj = c.subject_service.get_or_create(subject)

    pdf_pages = sum(page_count(path.read_bytes()) for path in files if path.suffix.lower() == ".pdf")
    other = sum(1 for path in files if path.suffix.lower() != ".pdf")
    estimate = estimate_ingest(page_count=pdf_pages + other, model=c.settings.model_read_pages, prices=c.prices)
    typer.echo(f"Estimate: {estimate.describe()} (embeddings extra, small)")
    if not yes:
        typer.confirm("Proceed?", abort=True)

    failures = 0
    for path in files:
        try:
            source = c.source_service.register(subj, path.name, path.read_bytes())
            c.job_runner.enqueue("ingest_source", {"source_id": str(source.id)})
            typer.echo(_describe(c.sources.get(source.id)))
        except Exception as exc:  # report and continue with the next file
            failures += 1
            typer.echo(f"{path.name}: FAILED {type(exc).__name__}: {exc}", err=True)
    c.close()
    if failures:
        raise typer.Exit(code=1)


@source_app.command("list")
def source_list(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    c = build_container()
    for source in c.source_service.list(c.subject_service.require(subject)):
        typer.echo(f"{source.id}  {_describe(source)}")
    c.close()


@source_app.command("delete")
def source_delete(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    c = build_container()
    source = c.sources.get(source_id)
    if not yes:
        typer.confirm(f"Delete {source.filename} and its pages and chunks?", abort=True)
    c.source_service.delete(source_id)
    typer.echo(f"deleted {source.filename}")
    c.close()


@source_app.command("reingest")
def source_reingest(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Re-run the whole pipeline for one source (after fixing the file or the prompts)."""
    c = build_container()
    c.check_ready()
    source = c.source_service.mark_for_reingest(source_id)
    estimate = estimate_ingest(page_count=source.page_count or 1, model=c.settings.model_read_pages, prices=c.prices)
    typer.echo(f"Estimate: {estimate.describe()}")
    if not yes:
        typer.confirm("Proceed?", abort=True)
    c.job_runner.enqueue("ingest_source", {"source_id": str(source.id)})
    typer.echo(_describe(c.sources.get(source.id)))
    c.close()


@app.command()
def export(
    subject: str = typer.Option(..., "--subject", "-s"),
    out: Path = typer.Option(Path("digest-export"), "--out", "-o"),
) -> None:
    """Write every source of a subject as a digest bundle under OUT."""
    c = build_container()
    subj = c.subject_service.require(subject)
    for source in c.source_service.list(subj):
        folder = c.export_import.export_source(source.id, out)
        typer.echo(f"{source.filename} -> {folder}")
    c.close()


@app.command("import")
def import_bundle(
    bundle_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    subject: str = typer.Option(..., "--subject", "-s", help="Target subject; created if missing"),
) -> None:
    """Load one source bundle folder (the folder containing meta.json) into a subject."""
    c = build_container()
    c.check_ready()
    subj = c.subject_service.get_or_create(subject)
    source = c.export_import.import_source(subj, bundle_dir)
    typer.echo(_describe(source))
    c.close()


@app.command()
def usage(subject: str | None = typer.Option(None, "--subject", "-s")) -> None:
    """Cost and token summary per purpose and model."""
    c = build_container()
    subject_id = c.subject_service.require(subject).id if subject else None
    typer.echo(c.usage_service.format_table(c.usage_service.summary(subject_id)))
    c.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest -q api/tests/cli/test_cli.py`
Expected: `3 passed`

- [ ] **Step 5: Try the installed entry point**

Run: `teachme --help`
Expected: help text listing `migrate`, `subject`, `source`, `ingest`, `export`, `import`, `usage`.

- [ ] **Step 6: Commit**

```bash
git add api/teachme/cli api/tests/cli
git commit -m "feat: teachme command-line interface"
```

---

## Phase I: API entry, live checks, hosted infrastructure, cleanup

### Task 32: FastAPI entry with a health endpoint

**Files:**
- Create: `api/index.py`
- Modify: `pyproject.toml` (add `httpx` to dev deps for TestClient)
- Test: `api/tests/test_api_health.py`

- [ ] **Step 1: Add `"httpx>=0.27",` to the `dev` list in `pyproject.toml`, then run `uv pip install -e ".[dev]"`.**

- [ ] **Step 2: Write the failing test**

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from index import app


def test_health():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "teach-me"}
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest -q api/tests/test_api_health.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'index'`

- [ ] **Step 4: Write `api/index.py`**

```python
"""Vercel Python function entry. Routes for subjects, learning and progress mount here in stage 3."""

from __future__ import annotations

import os
import sys

# Vercel executes this file directly; make the sibling package importable without installation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI  # noqa: E402

app = FastAPI(title="teach-me")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "teach-me"}
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest -q api/tests/test_api_health.py`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add api/index.py api/tests/test_api_health.py pyproject.toml requirements.txt
git commit -m "feat: fastapi entry with health endpoint"
```

---

### Task 33: Live provider smoke tests (opt-in)

**Files:**
- Create: `api/tests/live/__init__.py`, `api/tests/live/test_live_providers.py`

- [ ] **Step 1: Write the tests** (skipped unless `RUN_LIVE=1`; they spend a few cents)

```python
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from teachme.adapters.embeddings.voyage import VoyageEmbedder
from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.adapters.reranker.voyage import VoyageReranker
from teachme.ports.llm import ContentPart, StructuredRequest
from teachme.settings import Settings

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call real providers")


class Capital(BaseModel):
    country: str
    capital: str


def test_anthropic_structured_call_returns_usage():
    settings = Settings()
    request = StructuredRequest(
        purpose="live.smoke", model=settings.model_detect_language, system="Answer precisely.",
        parts=(ContentPart.of_text("What is the capital of Portugal? Return country and capital."),),
        max_tokens=512, effort="low",
    )
    result = AnthropicLLM().generate_structured(request, Capital)
    assert result.output.capital.lower() == "lisbon"
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    print("anthropic usage:", result.usage, result.model)


def test_voyage_embedding_dimension_matches_schema():
    settings = Settings()
    embedder = VoyageEmbedder(model=settings.embedding_model)
    result = embedder.embed_documents(["A biosphere is the global sum of all ecosystems."])
    assert len(result.vectors[0]) == 1024, "voyage-4 dimension changed; chunks.embedding is vector(1024)"
    assert result.tokens > 0
    order = VoyageReranker(model=settings.rerank_model).rerank("what is a biosphere", ["ecosystems", "rocks"], 2)
    assert order[0] == 0
```

- [ ] **Step 2: Run them once with real keys**

Run: `set -a && source .env.local && set +a && RUN_LIVE=1 pytest -q -s api/tests/live`
Expected: `2 passed`, with the printed usage line. If the Voyage assertion fails, the schema dimension must change: add a migration `0002_embedding_dimension.sql` altering the column, and update `FakeEmbedder`'s default. Do not proceed to Task 34 with a mismatch.

- [ ] **Step 3: Commit**

```bash
git add api/tests/live
git commit -m "test: opt-in live smoke tests for anthropic and voyage"
```

---

### Task 34: Hosted database and file store on Vercel

This task is operational. It provisions the Marketplace Postgres and the Blob store, links the Vercel project, and runs the first real ingestion against the hosted database. It spends real money once (one short PDF).

- [ ] **Step 1: Rename the Vercel project** from `saas` to `teach-me` in the Vercel dashboard (Project Settings, General, Project Name), then in the repo run `vercel link` and choose the `teach-me` project. Confirm `.vercel/project.json` shows `"projectName":"teach-me"`.

- [ ] **Step 2: Provision storage through the Marketplace.** Invoke the `vercel:marketplace` skill and follow its discover flow twice: once for a Postgres database that supports the `vector` extension, once for Vercel Blob. Accept the environment variables each integration injects. The Postgres integration must expose a connection string; map it to `DATABASE_URL` in the project's environment variables if the integration uses a different name. Blob injects `BLOB_READ_WRITE_TOKEN`.

- [ ] **Step 3: Set the remaining production variables** with `vercel env add`: `ANTHROPIC_API_KEY` (a service-account key with an expiry, per the spec), `VOYAGE_API_KEY`, `FILE_STORE=vercel_blob`, `LLM_PROVIDER=anthropic`, `EMBEDDINGS_PROVIDER=voyage`, `RERANKER_PROVIDER=voyage`. Then `vercel env pull .env.local` so the same values are available locally for the CLI.

- [ ] **Step 4: Migrate the hosted database**

Run: `set -a && source .env.local && set +a && teachme migrate`
Expected: `applied: ['0001_initial']`

- [ ] **Step 5: Acceptance run on a real, short PDF** (under 20 pages). Put it under `sources/` (gitignored).

Run: `set -a && source .env.local && set +a && teachme ingest --subject "Pilot" sources/<file>.pdf`
Read the printed estimate, confirm, and wait. Expected last line: `<file>.pdf: ready (N pages, language xx)`.

Then verify:
```bash
teachme source list --subject Pilot
teachme usage --subject Pilot
ls digest/pilot-*/*/pages | head
```
Expected: the source is ready, the usage table lists `ingest.read_pages`, `ingest.detect_language`, `ingest.contextualize` and `embed.documents` with a non-zero total, and the local digest folder holds one Markdown file per page. Open two page files and one chunk line and check they read correctly, including a figure block if the PDF has figures.

- [ ] **Step 6: Record the measured cost** in `docs/superpowers/plans/2026-09-17-stage1-ingestion.md` under a new heading `## Pilot cost` with the page count and the total from `teachme usage`, so the estimate constants in `estimate.py` can be recalibrated later. Commit:

```bash
git add docs/superpowers/plans/2026-09-17-stage1-ingestion.md
git commit -m "docs: record pilot ingestion cost"
```

---

### Task 35: Remove the reference code, tidy docs, final verification

**Files:**
- Delete: `reference/`
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Confirm nothing imports the reference folder**

Run: `grep -rn "reference" api/ --include=*.py | grep -v "^api/tests" ; echo "exit=$?"`
Expected: no matching lines.

- [ ] **Step 2: Delete it and update the notes**

```bash
git rm -r reference
```

In `CLAUDE.md` replace the line about `reference/rag/` with:

```
- Stage 1 (ingestion library + CLI) is complete. Run `teachme --help` for operator commands.
```

Append to `README.md`:

```markdown
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
without any API key. Tests: `TEST_DATABASE_URL=postgresql://teachme:teachme@localhost:5432/teachme_test pytest -q`.
```

- [ ] **Step 3: Lint and run everything**

Run: `ruff check api && ruff format --check api && pytest -q`
Expected: ruff reports no errors; pytest reports all tests passed with only the live tests and Vercel Blob contract cases skipped. Fix any ruff findings before continuing (`ruff format api` for formatting).

- [ ] **Step 4: Sweep for old names**

Run: `grep -rniE "insurellm|ideagen|\bsaas\b" --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.next --exclude-dir=.git --exclude-dir=docs . ; echo "exit=$?"`
Expected: `exit=1` (no matches in code or config). The design spec and this plan under `docs/` may name the old project as history; nothing else may.

- [ ] **Step 5: Commit and push**

```bash
git add -A
git commit -m "chore: remove reference rag code, document operator workflow"
git push origin main
```

Expected: push succeeds to `LiorKoren77/teach-me` (the repo-local credential helper handles auth).

---

## Self-review against the spec

- Section 3.2 module layout: every stage-1 module in the layout exists in a task (ports, adapters incl. S3 and SQS, domain text/languages/fusion, ingestion steps, bundle, telemetry, repositories, services, cli, container, api/index). Deferred to later stages by design: `domain/relevance`, `domain/assessment`, `domain/glossary`, `generation/`, `grading/`, `retrieval/tool.py`, `auth/`, `routes/`, `adapters/identity/`, `adapters/job_runner/vercel_function.py`.
- Section 4 data model: stage-1 tables created in Task 9; the remaining tables arrive with stages 2 and 3 as new migrations.
- Section 5 pipeline: accepted types from `capabilities()` narrowed by settings (Task 29), all pages through Claude with figures (Tasks 23-24), language detection (Task 24), contextual chunking with page ranges and coverage check (Task 25), embedding and single-insert indexing (Tasks 17, 26), bundle written before the database on every step (Task 27), export/import (Task 30), idempotent re-ingest and publish lock (Tasks 27, 29), per-step failure with resume (Task 27), cost estimate and confirmation (Task 31).
- Section 9: settings fail by name (Task 2), fake stack without keys (Tasks 13, 14, 28), usage rows per call (Task 18), CLI usage summary (Task 31), federation is deferred to before students arrive (spec), hosted provisioning (Task 34).
