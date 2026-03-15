"""Deterministic search query planning."""

from __future__ import annotations

from collections import Counter, defaultdict

from fast_foto_forensics.models import EvidenceObservation, QueryCandidate, QueryPlan, tokenize_text

_STOPWORDS = {
    "and",
    "for",
    "from",
    "the",
    "this",
    "that",
    "with",
    "into",
    "onto",
    "over",
    "under",
    "near",
    "blue",
    "dusty",
    "old",
    "tall",
    "small",
    "large",
    "shelf",
    "workbench",
}

_LOW_VALUE_OCR_TOKENS = {
    "fcc",
    "id",
    "mac",
    "pn",
    "part",
    "rev",
    "serial",
    "sn",
    "ssid",
    "ver",
}


def _unique_terms(parts: list[str]) -> list[str]:
    """Preserve order while deduplicating terms case-insensitively."""
    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = part.strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_parts.append(value)
    return unique_parts


def _record_candidate(
    candidates: dict[str, QueryCandidate],
    score_buckets: dict[str, float],
    text: str,
    provenance: list[str],
    score: float,
) -> None:
    """Accumulate scores and merge provenance for one normalized query."""
    normalized_terms = _unique_terms(text.split())
    if not normalized_terms:
        return
    normalized_text = " ".join(normalized_terms)
    key = normalized_text.casefold()
    score_buckets[key] += score
    if key not in candidates:
        candidates[key] = QueryCandidate(
            text=normalized_text,
            provenance=list(provenance),
            score=score_buckets[key],
        )
        return

    candidate = candidates[key]
    for item in provenance:
        if item not in candidate.provenance:
            candidate.provenance.append(item)
    candidate.score = score_buckets[key]


def _build_brand_tokens(observation: EvidenceObservation) -> list[str]:
    """Extract likely brand tokens from OCR and caption evidence."""
    identifier_tokens = {
        token.casefold() for token in tokenize_text(*observation.candidate_identifiers)
    }
    object_tokens = {token.casefold() for token in tokenize_text(*observation.detected_labels)}
    brand_scores: Counter[str] = Counter()

    for token in tokenize_text(observation.ocr_text):
        key = token.casefold()
        if (
            key in _STOPWORDS
            or key in _LOW_VALUE_OCR_TOKENS
            or key in identifier_tokens
            or key in object_tokens
            or key.isdigit()
        ):
            continue
        brand_scores[key] += 3

    for token in tokenize_text(observation.caption):
        key = token.casefold()
        if key in _STOPWORDS or key in identifier_tokens or key in object_tokens or key.isdigit():
            continue
        brand_scores[key] += 1

    return [token for token, _score in brand_scores.most_common(2)]


def _build_object_term(observation: EvidenceObservation, brand_tokens: list[str]) -> str | None:
    """Pick a compact object-class term from labels or caption text."""
    if observation.detected_labels:
        return observation.detected_labels[0].strip().lower() or None

    excluded = {token.casefold() for token in brand_tokens}
    excluded.update(token.casefold() for token in tokenize_text(*observation.candidate_identifiers))
    for token in tokenize_text(observation.caption):
        key = token.casefold()
        if key in _STOPWORDS or key in excluded or key.isdigit():
            continue
        return key
    return None


def _build_ocr_terms(
    observation: EvidenceObservation,
    brand_tokens: list[str],
    object_term: str | None,
) -> list[str]:
    """Create a compact OCR-derived query fragment without noisy boilerplate."""
    excluded = {token.casefold() for token in brand_tokens}
    excluded.update(token.casefold() for token in tokenize_text(*observation.candidate_identifiers))
    terms: list[str] = []

    if brand_tokens:
        terms.append(brand_tokens[0])

    for token in tokenize_text(observation.ocr_text):
        key = token.casefold()
        if key in _STOPWORDS or key in _LOW_VALUE_OCR_TOKENS or key in excluded or key.isdigit():
            continue
        terms.append(key)

    if object_term:
        terms.append(object_term)

    return _unique_terms(terms)[:3]


def _build_caption_terms(
    observation: EvidenceObservation,
    brand_tokens: list[str],
    object_term: str | None,
) -> list[str]:
    """Create a compact caption-led query from salient non-noise tokens."""
    excluded = {token.casefold() for token in brand_tokens}
    excluded.update(token.casefold() for token in tokenize_text(*observation.candidate_identifiers))
    if object_term:
        excluded.update(token.casefold() for token in tokenize_text(object_term))

    terms: list[str] = []
    for token in tokenize_text(observation.caption, *observation.detected_labels):
        key = token.casefold()
        if key in _STOPWORDS or key in excluded or key.isdigit():
            continue
        terms.append(key)

    return _unique_terms(terms)[:3]


def build_query_plan(observations: list[EvidenceObservation], max_queries: int = 5) -> QueryPlan:
    """Rank a small set of high-value queries from extracted evidence."""
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for observation in observations:
        brand_tokens = _build_brand_tokens(observation)
        object_term = _build_object_term(observation, brand_tokens)

        for identifier in observation.candidate_identifiers:
            query_terms = []
            if brand_tokens:
                query_terms.append(brand_tokens[0])
            query_terms.append(identifier)
            if object_term:
                query_terms.append(object_term)

            provenance = ["candidate_identifier", observation.evidence_id]
            if brand_tokens:
                provenance.append(f"brand:{brand_tokens[0]}")
            if object_term:
                provenance.append(f"object:{object_term}")

            _record_candidate(
                candidates,
                score_buckets,
                " ".join(query_terms),
                provenance,
                10.0 + (2.0 if brand_tokens else 0.0) + (1.0 if object_term else 0.0),
            )

        ocr_tokens = _build_ocr_terms(observation, brand_tokens, object_term)
        if ocr_tokens:
            _record_candidate(
                candidates,
                score_buckets,
                " ".join(ocr_tokens),
                ["ocr_text", observation.evidence_id],
                5.0,
            )

        caption_tokens = _build_caption_terms(observation, brand_tokens, object_term)
        if caption_tokens:
            _record_candidate(
                candidates,
                score_buckets,
                " ".join(caption_tokens),
                ["caption_tokens", observation.evidence_id],
                2.0,
            )

        if observation.analyst_hints:
            _record_candidate(
                candidates,
                score_buckets,
                " ".join(observation.analyst_hints[:3]),
                ["analyst_hint", observation.evidence_id],
                1.0,
            )

    ranked = sorted(candidates.values(), key=lambda candidate: (-candidate.score, candidate.text))
    return QueryPlan(selected_queries=ranked[:max_queries])
