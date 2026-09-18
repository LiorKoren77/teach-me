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
    glossary.replace_terms(
        outline.id,
        [
            GlossaryTerm(
                id=uuid4(),
                outline_id=outline.id,
                slug="biosphere",
                source_term="biosfera",
                definition="All living things",
                pages=(1, 2),
            ),
            GlossaryTerm(
                id=uuid4(),
                outline_id=outline.id,
                slug="atmosphere",
                source_term="atmosfera",
                definition="The air",
                pages=(3,),
            ),
        ],
    )
    terms = glossary.terms(outline.id)
    assert [t.slug for t in terms] == ["atmosphere", "biosphere"]
    glossary.replace_translations(
        outline.id,
        "he",
        [
            GlossaryTranslation(term_id=terms[0].id, language="he", term="אטמוספרה"),
            GlossaryTranslation(term_id=terms[1].id, language="he", term="ביוספרה"),
        ],
    )
    translated = glossary.translations(outline.id, "he")
    assert {t.term_id: t.term for t in translated} == {terms[0].id: "אטמוספרה", terms[1].id: "ביוספרה"}
    assert glossary.translations(outline.id, "pt") == []


def test_part_and_section_content(db):
    subject, repo, outline, parts, sections = _outline(db)
    content = ContentRepository(db)
    content.upsert_part(
        PartContent(
            part_id=parts[0].id,
            language="he",
            title="מבוא",
            body="{{term:biosphere|הביוספרה}} ...",
            key_points=("a", "b"),
            status=ContentStatus.READY,
            model="fake-model",
        )
    )
    content.upsert_sections(
        [
            SectionContent(section_id=sections[0].id, language="he", title="מה", summary="..."),
            SectionContent(section_id=sections[1].id, language="he", title="למה", summary="..."),
        ]
    )
    loaded = content.part(parts[0].id, "he")
    assert loaded is not None and loaded.title == "מבוא" and loaded.key_points == ("a", "b")
    assert content.part(parts[0].id, "en") is None
    assert [s.title for s in content.sections(parts[0].id, "he")] == ["מה", "למה"]
    content.upsert_part(loaded.model_copy(update={"status": ContentStatus.FAILED, "error": "boom"}))
    assert content.part(parts[0].id, "he").error == "boom"
    assert content.languages_ready(outline.id) == {}  # part 2 has no content yet
    content.upsert_part(
        PartContent(
            part_id=parts[1].id,
            language="he",
            title="x",
            body="y",
            key_points=(),
            status=ContentStatus.READY,
            model="m",
        )
    )
    content.upsert_part(loaded)  # back to READY
    assert content.languages_ready(outline.id) == {"he": 2}


def test_questions_replace_and_query(db):
    subject, repo, outline, parts, sections = _outline(db)
    questions = QuestionRepository(db)
    made = [
        Question(
            id=uuid4(),
            section_id=sections[0].id,
            language="he",
            kind=QuestionKind.FREE_TEXT,
            prompt="q1",
            expected_answer="a1",
            rubric=("r",),
            key_terms=("k",),
            exact_values=("1789",),
            position=0,
        ),
        Question(
            id=uuid4(),
            section_id=sections[1].id,
            language="he",
            kind=QuestionKind.MULTIPLE_CHOICE,
            prompt="q2",
            expected_answer="b",
            rubric=("r",),
            key_terms=(),
            exact_values=(),
            choices=("a", "b"),
            correct_choice=1,
            position=1,
        ),
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
