from __future__ import annotations

from uuid import uuid4

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.llm.fake import FakeLLM
from teachme.adapters.reranker.noop import NoopReranker
from teachme.domain.glossary.render import GlossaryView
from teachme.domain.models import Chunk, ChunkRecord, Grade, Question, QuestionKind
from teachme.domain.text.normalize import tokenize
from teachme.grading.evidence import gather_evidence
from teachme.grading.grader import GradeOut, grade_answer
from teachme.grading.relevance_check import RelevanceVerdict, check_relevance
from teachme.retrieval.hybrid import HybridSearch


def _question():
    return Question(
        id=uuid4(),
        section_id=uuid4(),
        language="en",
        kind=QuestionKind.FREE_TEXT,
        prompt="Why does the {{term:atmosphere|atmosphere}} protect life?",
        expected_answer="It absorbs UV.",
        rubric=("mentions absorption", "names ultraviolet radiation"),
        key_terms=("ozone",),
        exact_values=(),
    )


def test_check_relevance_request_and_verdict():
    llm = FakeLLM({RelevanceVerdict: lambda req: RelevanceVerdict(verdict="off_topic")})
    verdict = check_relevance(llm, "fake-model", _question(), "I like football", "en")
    assert verdict == "off_topic"
    call = llm.calls[0]
    assert call.purpose == "learn.relevance_check" and call.effort == "low"
    assert "<student_answer>" in call.parts[0].text and "I like football" in call.parts[0].text


def test_gather_evidence_returns_hits_for_question():
    embedder = FakeEmbedder(dimension=16)
    search = InMemoryChunkSearch(dimension=16)
    subject_id = uuid4()
    chunk = Chunk(context="c", text="The ozone layer absorbs ultraviolet radiation", page_start=3, page_end=3)
    search.upsert(
        [
            ChunkRecord(
                id=uuid4(),
                source_id=uuid4(),
                subject_id=subject_id,
                chunk=chunk,
                embedding=tuple(embedder.embed_documents([chunk.content]).vectors[0]),
                embedding_model="fake-embed",
                tokens=tuple(tokenize(chunk.content, "en")),
            )
        ]
    )
    hybrid = HybridSearch(embedder, search, NoopReranker(), candidates=10, final_k=5)
    evidence = gather_evidence(hybrid, subject_id, _question(), "en", k=3)
    assert len(evidence) == 1 and evidence[0].page_start == 3


def test_grade_answer_builds_prompt_with_rubric_glossary_and_evidence():
    out = GradeOut(
        verdict="partial",
        rubric_covered=[0],
        missed_concepts=["ultraviolet"],
        feedback="Say what it absorbs.",
    )
    llm = FakeLLM({GradeOut: lambda req: out})
    view = GlossaryView(source_language="pt", source_terms={"atmosphere": "atmosfera"})
    evidence_hits = gather_evidence(
        HybridSearch(FakeEmbedder(8), InMemoryChunkSearch(8), NoopReranker()), uuid4(), _question(), "en"
    )
    result = grade_answer(llm, "fake-model", _question(), "It stops the sun", "en", view, evidence_hits)
    assert result.grade == Grade.PARTIAL and result.rubric_covered == (0,)
    assert result.feedback == "Say what it absorbs."
    text = llm.calls[0].parts[0].text
    assert "RUBRIC 0: mentions absorption" in text and "RUBRIC 1: names ultraviolet radiation" in text
    assert "atmosphere (atmosfera)" in text  # placeholders rendered for the grader
    assert "<student_answer>" in text and "It stops the sun" in text
    assert "EVIDENCE" in text and llm.calls[0].purpose == "learn.grade"


def test_grade_off_topic_verdict_maps_to_grade():
    out = GradeOut(
        verdict="off_topic", rubric_covered=[], missed_concepts=[], feedback="Not about the question."
    )
    llm = FakeLLM({GradeOut: lambda req: out})
    result = grade_answer(
        llm,
        "fake-model",
        _question(),
        "banana",
        "en",
        GlossaryView(source_language=None, source_terms={}),
        [],
    )
    assert result.grade == Grade.OFF_TOPIC
