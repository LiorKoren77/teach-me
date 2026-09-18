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
        llm,
        "fake-model",
        "Geo",
        "he",
        corpus,
        part,
        [sections[0]],
        summaries,
        wrong,
        terms,
        {"biosphere": "ביוספרה"},
        on_delta=seen.append,
    )
    assert "".join(seen) == result.text and "{{term:biosphere" in result.text
    call = llm.calls[0]
    assert call.purpose == "learn.reexplain" and call.cached_context == corpus.render()
    text = call.parts[0].text
    assert "SECTION 0: What (pages 0-1)" in text and "SUMMARY 0: Summary of what." in text
    assert "WRONG: What is X? | Y | Not Y." in text and "TERM: biosphere | biosfera | ביוספרה" in text
    assert '<page index="1"' in text and '<page index="3"' not in text  # only the weak section's pages


def test_reexplain_refuses_an_empty_section_list():
    """Nothing to re-explain is a caller mistake, not a prompt to invent a lesson."""
    part, _sections, terms = _structure()
    llm = FakeLLM({}, text_responder=lambda req: "should not be called")
    with pytest.raises(ValueError, match="no weak sections"):
        reexplain_sections(
            llm,
            "fake-model",
            "Geo",
            "he",
            _corpus(4),
            part,
            [],
            [],
            [],
            terms,
            {},
            on_delta=lambda d: None,
        )
    assert llm.calls == []
