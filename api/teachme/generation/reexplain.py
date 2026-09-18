from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from teachme.domain.models import GlossaryTerm, Part, Section, SectionContent
from teachme.generation.corpus import SubjectCorpus
from teachme.generation.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, OnDelta, TextRequest, TextResult

REEXPLAIN_MAX_TOKENS = 6000


class WrongAnswer(BaseModel):
    question: str
    student_answer: str
    feedback: str


def render_brief(
    part: Part,
    sections: Sequence[Section],
    summaries: Sequence[SectionContent],
    wrong: Sequence[WrongAnswer],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    corpus: SubjectCorpus,
) -> str:
    """Unlike the teaching brief this one restates pages, but only the weak sections' ones: the
    whole corpus is already the cached prefix, and naming the pages again focuses the model."""
    by_id = {s.section_id: s for s in summaries}
    lines = [f"PART: {part.title}"]
    for s in sections:
        lines.append(f"SECTION {s.position}: {s.title} (pages {s.page_start}-{s.page_end})")
        if s.id in by_id:
            lines.append(f"SUMMARY {s.position}: {by_id[s.id].summary}")
    lines += [f"WRONG: {w.question} | {w.student_answer} | {w.feedback}" for w in wrong]
    lines += [f"TERM: {t.slug} | {t.source_term} | {translations.get(t.slug, t.source_term)}" for t in terms]
    lines.append("")
    lines.append("Pages of these sections:")
    for s in sections:
        lines.append(corpus.render(s.page_start, s.page_end))
    return "\n".join(lines)


def reexplain_sections(
    llm: LLMProvider,
    model: str,
    subject_name: str,
    language: str,
    corpus: SubjectCorpus,
    part: Part,
    sections: Sequence[Section],
    summaries: Sequence[SectionContent],
    wrong: Sequence[WrongAnswer],
    terms: Sequence[GlossaryTerm],
    translations: Mapping[str, str],
    *,
    on_delta: OnDelta,
) -> TextResult:
    if not sections:
        raise ValueError("no weak sections to re-explain")
    request = TextRequest(
        purpose="learn.reexplain",
        model=model,
        system=load_prompt("reexplain").format(subject=subject_name, language=language),
        parts=(
            ContentPart.of_text(render_brief(part, sections, summaries, wrong, terms, translations, corpus)),
        ),
        cached_context=corpus.render(),
        max_tokens=REEXPLAIN_MAX_TOKENS,
        effort="high",
    )
    return llm.stream_text(request, on_delta=on_delta)
