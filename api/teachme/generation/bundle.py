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
                part_position=positions[q.section_id][0],
                section_position=positions[q.section_id][1],
                position=q.position,
                kind=q.kind.value,
                prompt=q.prompt,
                expected_answer=q.expected_answer,
                rubric=list(q.rubric),
                key_terms=list(q.key_terms),
                exact_values=list(q.exact_values),
                choices=list(q.choices) if q.choices else None,
                correct_choice=q.correct_choice,
            )
            for q in questions
        ]
        data = "".join(r.model_dump_json() + "\n" for r in rows).encode()
        self._write(f"questions.{language}.jsonl", data, "application/x-ndjson")

    def _write(self, relative: str, data: bytes, content_type: str) -> None:
        for store in self._stores:
            store.put(f"{self._slug}/{relative}", data, content_type)
