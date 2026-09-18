from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import (
    ContentStatus,
    GlossaryTerm,
    Outline,
    Part,
    PartContent,
    Question,
    QuestionKind,
    Section,
)
from teachme.ports.file_store import FileStore


class SectionDoc(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int
    title: str
    page_start: int
    page_end: int


class PartDoc(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int
    title: str
    page_start: int
    page_end: int
    sections: list[SectionDoc]


class OutlineDoc(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    model: str
    parts: list[PartDoc]


class GlossaryTermRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    term: str
    definition: str
    pages: tuple[int, ...]


class QuestionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_position: int
    section_position: int
    position: int
    kind: QuestionKind
    prompt: str
    expected_answer: str
    rubric: list[str]
    key_terms: list[str]
    exact_values: list[str]
    choices: list[str] | None
    correct_choice: int | None


class SubjectBundleWriter:
    """One outline version's subject-level digest files, next to the per-source bundles:
    v<N>/outline.json, v<N>/glossary.json, v<N>/glossary.<lang>.json, v<N>/parts/NN.<lang>.md,
    v<N>/questions.<lang>.jsonl.

    The version prefix is what keeps a draft regeneration from overwriting the files of the
    version students are still being taught from: one writer only ever writes its own version."""

    def __init__(self, stores: Sequence[FileStore], subject_slug: str, outline_version: int) -> None:
        self._stores = list(stores)
        self._slug = subject_slug
        self._version = outline_version

    def write_outline(self, outline: Outline, parts: Sequence[tuple[Part, Sequence[Section]]]) -> None:
        if outline.version != self._version:
            raise ValueError(
                f"outline version {outline.version} does not match this writer's version {self._version}"
            )
        doc = OutlineDoc(
            version=outline.version,
            model=outline.model,
            parts=[
                PartDoc(
                    position=p.position,
                    title=p.title,
                    page_start=p.page_start,
                    page_end=p.page_end,
                    sections=[
                        SectionDoc(
                            position=s.position, title=s.title, page_start=s.page_start, page_end=s.page_end
                        )
                        for s in sections
                    ],
                )
                for p, sections in parts
            ],
        )
        self._write("outline.json", doc.model_dump_json(indent=2).encode(), "application/json")

    def write_glossary(self, terms: Sequence[GlossaryTerm]) -> None:
        rows = [
            GlossaryTermRow(slug=t.slug, term=t.source_term, definition=t.definition, pages=tuple(t.pages))
            for t in terms
        ]
        payload = json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False, indent=2)
        self._write("glossary.json", payload.encode(), "application/json")

    def write_translations(self, language: str, translations: Mapping[str, str]) -> None:
        payload = json.dumps(dict(sorted(translations.items())), ensure_ascii=False, indent=2)
        self._write(f"glossary.{language}.json", payload.encode(), "application/json")

    def write_part_content(self, part: Part, content: PartContent) -> None:
        """A ready part gets its full teaching text; anything else (a failed attempt) gets only
        the header, naming the error - no title, body or key points to look like real content."""
        if content.part_id != part.id:
            raise ValueError(
                f"content.part_id {content.part_id} does not match part {part.id} (position {part.position})"
            )
        header = (
            f"<!-- teach-me part position={part.position} language={content.language}"
            f" model={content.model} status={content.status.value}"
        )
        if content.error:
            header += f" error={json.dumps(content.error)}"
        header += " -->"
        relative = f"parts/{part.position + 1:02d}.{content.language}.md"
        if content.status != ContentStatus.READY:
            self._write(relative, f"{header}\n".encode(), "text/markdown")
            return
        body = f"# {content.title}\n\n{content.body.strip()}\n"
        if content.key_points:
            points = "\n".join(f"- {p}" for p in content.key_points)
            body += f"\n## Key points\n\n{points}\n"
        self._write(relative, f"{header}\n\n{body}".encode(), "text/markdown")

    def write_questions(
        self, language: str, questions: Sequence[Question], positions: Mapping[UUID, tuple[int, int]]
    ) -> None:
        rows = []
        for q in questions:
            try:
                part_position, section_position = positions[q.section_id]
            except KeyError:
                raise ValueError(f"no part/section position recorded for section {q.section_id}") from None
            rows.append(
                QuestionRow(
                    part_position=part_position,
                    section_position=section_position,
                    position=q.position,
                    kind=q.kind,
                    prompt=q.prompt,
                    expected_answer=q.expected_answer,
                    rubric=list(q.rubric),
                    key_terms=list(q.key_terms),
                    exact_values=list(q.exact_values),
                    choices=list(q.choices) if q.choices else None,
                    correct_choice=q.correct_choice,
                )
            )
        data = "".join(r.model_dump_json() + "\n" for r in rows).encode()
        self._write(f"questions.{language}.jsonl", data, "application/x-ndjson")

    def _write(self, relative: str, data: bytes, content_type: str) -> None:
        for store in self._stores:
            store.put(f"{self._slug}/v{self._version}/{relative}", data, content_type)
