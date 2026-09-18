from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

from teachme.domain.models import Frozen, Question, RelevanceBand
from teachme.domain.text.normalize import normalize, tokenize

MIN_WORDS_FOR_JUDGEMENT = 3
"""Distinct words of the student's own, counted on the answer itself rather than on the
tokenizer's output: Hebrew emits a prefix-stripped variant per word, and counting those made a
two-word Hebrew answer look judgeable while the same answer in English did not."""

FUZZY_RATIO = 0.8
PREFIX_MIN_CHARS = 7
PREFIX_MIN_SHARE = 0.7
"""A shared prefix counts as the same word only when it is long in absolute terms and covers
most of the shorter token: "prote" is neither, so "protects" is not a hit for "protein"."""

_WORD = re.compile(r"\w+", re.UNICODE)


class RelevanceThresholds(Frozen):
    high: float = 0.5
    low: float = 0.15


class RelevanceSignals(Frozen):
    answer_tokens: int
    key_term_hits: int
    key_terms_total: int
    exact_value_hit: bool
    topic_overlap: float  # share of content tokens found in the section vocabulary
    echo_ratio: float  # share of answer tokens copied from the question


class RelevanceResult(Frozen):
    score: float
    band: RelevanceBand
    signals: RelevanceSignals


def _words(text: str) -> set[str]:
    return set(_WORD.findall(normalize(text)))


def _fold(text: str) -> str:
    """Accent-blind form for comparing words: "radiacao" typed without diacritics is the same
    word as "radiação", and a student should not lose a key term over a keyboard."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _whole_word(needle: str, haystack: str) -> bool:
    """`\\b`-style anchoring, spelled with lookarounds so a needle that begins or ends in
    punctuation still anchors on the word next to it: "ion" must not match inside "nation",
    nor "1789" inside "17890"."""
    return re.search(rf"(?<!\w){re.escape(_fold(needle))}(?!\w)", _fold(haystack)) is not None


def _common_prefix(left: str, right: str) -> int:
    shared = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        shared += 1
    return shared


def _fuzzy_token(term: str, tokens: Sequence[str]) -> bool:
    """One answer token close enough to the term: an inflection or a typo, not a shared stem."""
    folded_term = _fold(term)
    for raw in tokens:
        token = _fold(raw)
        if token == folded_term or SequenceMatcher(None, token, folded_term).ratio() >= FUZZY_RATIO:
            return True
        shared = _common_prefix(token, folded_term)
        if shared >= PREFIX_MIN_CHARS and shared >= PREFIX_MIN_SHARE * min(len(token), len(folded_term)):
            return True
    return False


def _term_matches(term: str, tokens: Sequence[str], answer_norm: str) -> bool:
    """A key term hits when the whole phrase appears as words, or when every word of the term
    finds a fuzzy match among the answer's tokens - in any order, so a multi-word term matches
    "a layer of ozone" as well as "the ozone layer"."""
    term_norm = normalize(term)
    if _whole_word(term_norm, answer_norm):
        return True
    term_tokens = _WORD.findall(term_norm)
    return bool(term_tokens) and all(_fuzzy_token(word, tokens) for word in term_tokens)


def score_relevance(
    answer: str,
    question: Question,
    *,
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
    content_words = _words(answer) - _words(question.prompt)

    exact_hit = any(
        _whole_word(normalize(value), answer_norm) or normalize(value) in tokens
        for value in question.exact_values
        if value.strip()
    )
    hits = sum(1 for term in question.key_terms if term.strip() and _term_matches(term, tokens, answer_norm))
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
    if len(content_words) < MIN_WORDS_FOR_JUDGEMENT:
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
