from __future__ import annotations

import json
from uuid import uuid4

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
    writer = SubjectBundleWriter([store], "geo-12345678")
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
        "geo-12345678/glossary.he.json",
        "geo-12345678/glossary.json",
        "geo-12345678/outline.json",
        "geo-12345678/parts/01.he.md",
        "geo-12345678/questions.he.jsonl",
    ]
    doc = OutlineDoc.model_validate_json(store.get("geo-12345678/outline.json"))
    assert doc.version == 2 and doc.parts[0].sections[0].title == "What"
    md = store.get("geo-12345678/parts/01.he.md").decode()
    assert md.startswith("# מבוא\n") and "{{term:biosphere|x}} body" in md and "- a" in md
    row = json.loads(store.get("geo-12345678/questions.he.jsonl").decode().splitlines()[0])
    assert row["part_position"] == 0 and row["section_position"] == 0 and row["prompt"] == "q"
    assert json.loads(store.get("geo-12345678/glossary.he.json")) == {"biosphere": "ביוספרה"}
