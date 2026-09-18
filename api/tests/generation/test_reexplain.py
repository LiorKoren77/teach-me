from __future__ import annotations

import pytest

from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import SectionContent
from teachme.generation.reexplain import WrongAnswer, reexplain_sections
from tests.generation.test_outline import _corpus
from tests.generation.test_teaching import _structure


def test_reexplain_streams_and_builds_brief():
    part, sections, terms = _structure()
    corpus = _corpus(4)
    llm = FakeLLM(
        {}, text_responder=lambda req: "## Another way\n\n{{term:biosphere|x}} explained differently."
    )
    seen = []
    summaries = [
        SectionContent(section_id=sections[0].id, language="he", title="מה", summary="Summary of what.")
    ]
    wrong = [WrongAnswer(question="What is X?", student_answer="Y", feedback="Not Y.")]
    result = reexplain_sections(
        llm=llm,
        model="fake-model",
        subject_name="Geo",
        language="he",
        corpus=corpus,
        part=part,
        sections=[sections[0]],
        summaries=summaries,
        wrong=wrong,
        terms=terms,
        translations={"biosphere": "ביוספרה"},
        on_delta=seen.append,
    )
    assert "".join(seen) == result.text and "{{term:biosphere" in result.text
    call = llm.calls[0]
    assert call.purpose == "learn.reexplain"
    # the brief's restated weak pages are the whole source: no cached copy of the corpus
    assert call.cached_context is None
    text = call.parts[0].text
    assert "SECTION 0: What (pages 0-1)" in text and "SUMMARY 0: Summary of what." in text
    assert "WRONG: What is X? | Y | Not Y." in text and "TERM: biosphere | biosfera | ביוספרה" in text
    assert corpus.render(0, 1) in text  # the weak section's pages, verbatim
    assert '<page index="1"' in text and '<page index="3"' not in text  # only the weak section's pages


def test_reexplain_refuses_an_empty_section_list():
    """Nothing to re-explain is a caller mistake, not a prompt to invent a lesson."""
    part, _sections, terms = _structure()
    llm = FakeLLM({}, text_responder=lambda req: "should not be called")
    with pytest.raises(ValueError, match="no weak sections"):
        reexplain_sections(
            llm=llm,
            model="fake-model",
            subject_name="Geo",
            language="he",
            corpus=_corpus(4),
            part=part,
            sections=[],
            summaries=[],
            wrong=[],
            terms=terms,
            translations={},
            on_delta=lambda d: None,
        )
    assert llm.calls == []
