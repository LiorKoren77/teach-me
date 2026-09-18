from __future__ import annotations

from uuid import UUID

from teachme.domain.glossary.render import PLACEHOLDER
from teachme.domain.models import ChunkHit, Question
from teachme.retrieval.hybrid import HybridSearch

EVIDENCE_K = 5


def gather_evidence(
    hybrid: HybridSearch, subject_id: UUID, question: Question, language: str, k: int = EVIDENCE_K
) -> list[ChunkHit]:
    """Retrieve-then-grade: the chunks a grader needs, fetched once with the question and the
    expected answer as the query. Placeholders are reduced to their words for retrieval."""
    query = PLACEHOLDER.sub(lambda m: m.group(2), f"{question.prompt} {question.expected_answer}")
    return hybrid.search(subject_id, query, language_code=language, k=k)
