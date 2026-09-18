from __future__ import annotations

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
            qs.append(
                QuestionOut(
                    section_position=pos,
                    kind=QuestionKind.FREE_TEXT,
                    prompt=f"q{pos}{i} {{{{term:biosphere|biosfera}}}}",
                    expected_answer="a",
                    rubric=["r1", "r2"],
                    key_terms=["k"],
                    exact_values=[],
                )
            )
    if mc:
        qs.append(
            QuestionOut(
                section_position=0,
                kind=QuestionKind.MULTIPLE_CHOICE,
                prompt="mc",
                expected_answer="b",
                rubric=["r"],
                key_terms=[],
                exact_values=[],
                choices=["a", "b", "c", "d"],
                correct_choice=1,
            )
        )
    return QuestionBankOut(questions=qs)


def test_validate_bank():
    part, sections, terms = _structure()
    slugs = {t.slug for t in terms}
    assert validate_bank(_bank(), sections, slugs, min_per_section=2) == []
    errors = validate_bank(_bank(n_per_section=1, mc=False), sections, slugs, min_per_section=2)
    assert any("section 0" in e and "at least 2" in e for e in errors)
    assert any("multiple_choice" in e for e in errors)
    bad_pos = QuestionBankOut(
        questions=[
            QuestionOut(
                section_position=9,
                kind=QuestionKind.FREE_TEXT,
                prompt="p",
                expected_answer="a",
                rubric=["r"],
                key_terms=[],
                exact_values=[],
            )
        ]
    )
    assert any(
        "unknown section position 9" in e for e in validate_bank(bad_pos, sections, slugs, min_per_section=0)
    )
    bad_mc = QuestionBankOut(
        questions=[
            QuestionOut(
                section_position=0,
                kind=QuestionKind.MULTIPLE_CHOICE,
                prompt="p",
                expected_answer="a",
                rubric=["r"],
                key_terms=[],
                exact_values=[],
                choices=["a", "b"],
                correct_choice=5,
            )
        ]
    )
    assert any("correct_choice" in e for e in validate_bank(bad_mc, sections, slugs, min_per_section=0))


def test_augment_key_terms_adds_glossary_forms():
    q = QuestionOut(
        section_position=0,
        kind=QuestionKind.FREE_TEXT,
        prompt="{{term:biosphere|הביוספרה}}?",
        expected_answer="{{term:atmosphere|האטמוספרה}}",
        rubric=["r"],
        key_terms=["k"],
        exact_values=[],
    )
    terms = augment_key_terms(
        q, {"biosphere": "biosfera", "atmosphere": "atmosfera"}, {"biosphere": "ביוספרה"}
    )
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
    out = generate_question_bank(
        llm,
        "fake-model",
        "Geo",
        "he",
        corpus,
        part,
        sections,
        _good(),
        terms,
        {"biosphere": "ביוספרה"},
        count=5,
    )
    assert len(out.questions) == 5
    call = llm.calls[0]
    assert call.purpose == "gen.questions" and call.cached_context == corpus.render()
    assert (
        "COUNT: 5" in call.parts[0].text
        and "TEACHING:" in call.parts[0].text
        and "SECTION 1:" in call.parts[0].text
    )
    assert "{count}" not in call.system and "5 questions" in call.system
