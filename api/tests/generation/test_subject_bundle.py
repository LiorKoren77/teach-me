from __future__ import annotations

import json
from uuid import uuid4

import pytest

from teachme.adapters.file_store.memory import InMemoryFileStore
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
from teachme.generation.bundle import OutlineDoc, SubjectBundleWriter


def test_writer_lays_out_subject_level_files():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678", 2)
    outline = Outline(id=uuid4(), subject_id=uuid4(), version=2, model="fake-model")
    part = Part(id=uuid4(), outline_id=outline.id, position=0, title="Intro", page_start=0, page_end=3)
    sections = [Section(id=uuid4(), part_id=part.id, position=0, title="What", page_start=0, page_end=3)]
    terms = [
        GlossaryTerm(
            id=uuid4(),
            outline_id=outline.id,
            slug="biosphere",
            source_term="biosfera",
            definition="d",
            pages=(0,),
        )
    ]

    writer.write_outline(outline, [(part, sections)])
    writer.write_glossary(terms)
    writer.write_translations("he", {"biosphere": "ביוספרה"})
    writer.write_part_content(
        part,
        PartContent(
            part_id=part.id,
            language="he",
            title="מבוא",
            body="{{term:biosphere|x}} body",
            key_points=("a",),
            status=ContentStatus.READY,
            model="fake-model",
        ),
    )
    writer.write_questions(
        "he",
        [
            Question(
                id=uuid4(),
                section_id=sections[0].id,
                language="he",
                kind=QuestionKind.FREE_TEXT,
                prompt="q",
                expected_answer="a",
                rubric=("r",),
                key_terms=("k",),
                exact_values=(),
                position=0,
            )
        ],
        {sections[0].id: (part.position, sections[0].position)},
    )

    keys = store.list_keys("geo-12345678/")
    assert keys == [
        "geo-12345678/v2/glossary.he.json",
        "geo-12345678/v2/glossary.json",
        "geo-12345678/v2/outline.json",
        "geo-12345678/v2/parts/01.he.md",
        "geo-12345678/v2/questions.he.jsonl",
    ]
    doc = OutlineDoc.model_validate_json(store.get("geo-12345678/v2/outline.json"))
    assert doc.version == 2 and doc.parts[0].sections[0].title == "What"

    md = store.get("geo-12345678/v2/parts/01.he.md").decode()
    assert md.startswith("<!-- teach-me part position=0 language=he model=fake-model status=ready -->\n\n")
    assert "# מבוא" in md and "{{term:biosphere|x}} body" in md
    assert "## Key points" in md and "- a" in md

    row = json.loads(store.get("geo-12345678/v2/questions.he.jsonl").decode().splitlines()[0])
    assert row["part_position"] == 0 and row["section_position"] == 0 and row["prompt"] == "q"
    assert row["kind"] == "free_text"

    assert json.loads(store.get("geo-12345678/v2/glossary.he.json")) == {"biosphere": "ביוספרה"}
    glossary_rows = json.loads(store.get("geo-12345678/v2/glossary.json"))
    assert glossary_rows == [{"slug": "biosphere", "term": "biosfera", "definition": "d", "pages": [0]}]
    assert "id" not in glossary_rows[0] and "outline_id" not in glossary_rows[0]


def test_write_part_content_omits_key_points_section_when_empty():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678", 1)
    part = Part(id=uuid4(), outline_id=uuid4(), position=0, title="Intro", page_start=0, page_end=3)
    writer.write_part_content(
        part,
        PartContent(
            part_id=part.id,
            language="he",
            title="מבוא",
            body="body text",
            key_points=(),
            status=ContentStatus.READY,
            model="fake-model",
        ),
    )
    md = store.get("geo-12345678/v1/parts/01.he.md").decode()
    assert "## Key points" not in md


def test_write_part_content_rejects_mismatched_part_id():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678", 1)
    part = Part(id=uuid4(), outline_id=uuid4(), position=0, title="Intro", page_start=0, page_end=3)
    content = PartContent(
        part_id=uuid4(),  # does not match part.id
        language="he",
        title="מבוא",
        body="body text",
        key_points=(),
        status=ContentStatus.READY,
        model="fake-model",
    )
    with pytest.raises(ValueError, match=str(content.part_id)):
        writer.write_part_content(part, content)


def test_write_questions_names_the_missing_section():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678", 1)
    section_id = uuid4()
    question = Question(
        id=uuid4(),
        section_id=section_id,
        language="he",
        kind=QuestionKind.FREE_TEXT,
        prompt="q",
        expected_answer="a",
        rubric=("r",),
        key_terms=("k",),
        exact_values=(),
        position=0,
    )
    with pytest.raises(ValueError, match=str(section_id)):
        writer.write_questions("he", [question], {})


def test_write_outline_rejects_a_version_the_writer_was_not_built_for():
    store = InMemoryFileStore()
    writer = SubjectBundleWriter([store], "geo-12345678", 1)
    outline = Outline(id=uuid4(), subject_id=uuid4(), version=2, model="fake-model")
    with pytest.raises(ValueError, match="version 2"):
        writer.write_outline(outline, [])
    assert store.list_keys("geo-12345678/") == []
