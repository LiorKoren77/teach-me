from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict

from teachme.domain.models import Question, RelevanceBand
from teachme.domain.text.normalize import normalize, tokenize

MIN_TOKENS_FOR_JUDGEMENT = 3
FUZZY_RATIO = 0.8


class RelevanceThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    high: float = 0.5
    low: float = 0.15


class RelevanceSignals(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer_tokens: int
    key_term_hits: int
    key_terms_total: int
    exact_value_hit: bool
    topic_overlap: float  # share of content tokens found in the section vocabulary
    echo_ratio: float  # share of answer tokens copied from the question


class RelevanceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float
    band: RelevanceBand
    signals: RelevanceSignals


def _fuzzy_contains(term: str, tokens: Iterable[str], answer_norm: str) -> bool:
    """A key term matches if any answer token is close to it, or if the whole phrase appears."""
    term_norm = normalize(term)
    if term_norm in answer_norm:
        return True
    term_tokens = term_norm.split()
    if len(term_tokens) > 1:
        return False
    for token in tokens:
        if token == term_norm or SequenceMatcher(None, token, term_norm).ratio() >= FUZZY_RATIO:
            return True
        if len(token) >= 5 and len(term_norm) >= 5:
            if token.startswith(term_norm[:5]) or term_norm.startswith(token[:5]):
                return True
    return False


def score_relevance(
    answer: str,
    question: Question,
    section_vocabulary: frozenset[str],
    language_code: str,
    thresholds: RelevanceThresholds | None = None,
) -> RelevanceResult:
    """Cheap, model-free estimate of whether an answer is an attempt at the question.

    Never rejects on its own: LOW and UNCERTAIN go to the Haiku check; HIGH skips it. Short answers
    cannot be judged lexically and land in UNCERTAIN, so brevity never fails a student."""
    thresholds = thresholds or RelevanceThresholds()
    answer_norm = normalize(answer)
    tokens = tokenize(answer, language_code)
    question_tokens = set(tokenize(question.prompt, language_code))

    exact_hit = any(normalize(v) in answer_norm for v in question.exact_values if v.strip())
    hits = sum(1 for term in question.key_terms if _fuzzy_contains(term, tokens, answer_norm))
    non_echo = [t for t in tokens if t not in question_tokens]
    echo_ratio = 1.0 - (len(non_echo) / len(tokens)) if tokens else 0.0
    overlap = (sum(1 for t in non_echo if t in section_vocabulary) / len(non_echo)) if non_echo else 0.0

    signals = RelevanceSignals(
        answer_tokens=len(tokens),
        key_term_hits=hits,
        key_terms_total=len(question.key_terms),
        exact_value_hit=exact_hit,
        topic_overlap=overlap,
        echo_ratio=echo_ratio,
    )

    if exact_hit:
        return RelevanceResult(score=1.0, band=RelevanceBand.HIGH, signals=signals)
    if len(non_echo) < MIN_TOKENS_FOR_JUDGEMENT:
        return RelevanceResult(score=0.0, band=RelevanceBand.UNCERTAIN, signals=signals)

    term_ratio = hits / len(question.key_terms) if question.key_terms else 0.0
    score = 0.6 * min(1.0, term_ratio * 2) + 0.4 * overlap
    if score >= thresholds.high:
        band = RelevanceBand.HIGH
    elif score >= thresholds.low:
        band = RelevanceBand.UNCERTAIN
    else:
        band = RelevanceBand.LOW
    return RelevanceResult(score=round(score, 4), band=band, signals=signals)
