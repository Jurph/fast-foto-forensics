"""Deterministic search query planning."""

from __future__ import annotations

from collections import defaultdict

from fast_foto_forensics.models import EvidenceObservation, QueryCandidate, QueryPlan, tokenize_text


def build_query_plan(observations: list[EvidenceObservation], max_queries: int = 5) -> QueryPlan:
    """Rank a small set of high-value queries from extracted evidence."""
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for observation in observations:
        for identifier in observation.candidate_identifiers:
            text = (
                f"{identifier} {observation.detected_labels[0]}"
                if observation.detected_labels
                else identifier
            )
            score_buckets[text] += 10.0
            candidates[text] = QueryCandidate(
                text=text,
                provenance=["candidate_identifier", observation.evidence_id],
                score=score_buckets[text],
            )
        ocr_tokens = tokenize_text(observation.ocr_text)
        if ocr_tokens:
            text = " ".join(ocr_tokens[:3])
            score_buckets[text] += 5.0
            candidates[text] = QueryCandidate(
                text=text,
                provenance=["ocr_text", observation.evidence_id],
                score=score_buckets[text],
            )
        caption_tokens = tokenize_text(observation.caption, *observation.detected_labels)
        if caption_tokens:
            text = " ".join(caption_tokens[:3])
            score_buckets[text] += 2.0
            candidates[text] = QueryCandidate(
                text=text,
                provenance=["caption_tokens", observation.evidence_id],
                score=score_buckets[text],
            )
        if observation.analyst_hints:
            text = " ".join(observation.analyst_hints[:3])
            score_buckets[text] += 1.0
            candidates[text] = QueryCandidate(
                text=text,
                provenance=["analyst_hint", observation.evidence_id],
                score=score_buckets[text],
            )

    ranked = sorted(candidates.values(), key=lambda candidate: (-candidate.score, candidate.text))
    return QueryPlan(selected_queries=ranked[:max_queries])
