"""Deterministic search query planning.

Builds ranked web-search queries from enriched EvidenceObservations.

Core idea
~~~~~~~~~
A token is **alphanumeric** if it contains both letters and digits (e.g.,
"OC200", "G1A117060503877", "WRT54G", "GTX480").  These are high-entropy
and likely to be model numbers, serial numbers, or part codes.  Everything
else is a **context word** (e.g., "Verizon", "router", "Omada").

The planner builds queries by pairing each context word with each
alphanumeric: ``"Verizon OC200"``, ``"Omada OC200"``, ``"Verizon ER605"``,
etc.  The search engine decides which pairings are meaningful.

When vendor is known from the vision backend, it's always included as the
first context word in every query, giving those queries a score boost.

As a last resort, the raw OCR blob is included as a low-scoring fallback.
"""

from __future__ import annotations

import re
from collections import defaultdict

from fast_foto_forensics.models import EvidenceObservation, QueryCandidate, QueryPlan


def is_alphanumeric(token: str) -> bool:
    """True if the token contains both letters and digits.

    These tokens are high-entropy — likely model numbers, serial numbers,
    part codes, MAC addresses, firmware versions, etc.  Pure-alpha tokens
    ("Verizon", "router") and pure-numeric tokens ("2024", "001") are not
    alphanumeric by this definition.

    >>> is_alphanumeric("OC200")
    True
    >>> is_alphanumeric("G1A117060503877")
    True
    >>> is_alphanumeric("Verizon")
    False
    >>> is_alphanumeric("12345")
    False
    >>> is_alphanumeric("20.C0.47.2F.F9.0F")
    True
    """
    has_letter = False
    has_digit = False
    for char in token:
        if char.isalpha():
            has_letter = True
        elif char.isdigit():
            has_digit = True
        if has_letter and has_digit:
            return True
    return False


def _extract_tokens(text: str) -> list[str]:
    """Split text into tokens on whitespace and common delimiters.

    Preserves tokens like "20.C0.47.2F.F9.0F" (MAC addresses) and
    "rev.1.03" as single tokens, but splits on newlines, commas, and
    other obvious boundaries.
    """
    # Split on whitespace and newlines, keep non-empty
    return [t for t in re.split(r"[\s,;]+", text) if t.strip()]


def _gather_alphanumerics_and_words(
    obs: EvidenceObservation,
) -> tuple[list[str], list[str]]:
    """Collect all unique alphanumeric tokens and context words from an observation.

    Sources (in priority order):
    - candidate_identifiers and serial_numbers (already extracted by vision)
    - detected_labels
    - ocr_text
    - caption
    - vendor and object_class (if set)

    Returns (alphanumerics, words) — both deduplicated, order preserved.
    """
    all_tokens: list[str] = []

    # Start with the vision model's structured output
    all_tokens.extend(obs.candidate_identifiers)
    all_tokens.extend(obs.serial_numbers)
    all_tokens.extend(obs.detected_labels)

    # Add OCR and caption tokens
    all_tokens.extend(_extract_tokens(obs.ocr_text))
    all_tokens.extend(_extract_tokens(obs.caption))

    # Separate into alphanumerics and words
    alphanum_seen: set[str] = set()
    word_seen: set[str] = set()
    alphanumerics: list[str] = []
    words: list[str] = []

    for token in all_tokens:
        stripped = token.strip()
        if not stripped or len(stripped) < 2:
            continue
        key = stripped.casefold()

        if is_alphanumeric(stripped):
            if key not in alphanum_seen:
                alphanum_seen.add(key)
                alphanumerics.append(stripped)
        else:
            # Skip pure-digit tokens ("2024", "001")
            if stripped.isdigit():
                continue
            if key not in word_seen:
                word_seen.add(key)
                words.append(stripped)

    # Ensure vendor and object_class are in the word list if set
    # (they may already be there from OCR/labels, but ensure presence)
    if obs.vendor and obs.vendor.casefold() not in word_seen:
        words.insert(0, obs.vendor)
        word_seen.add(obs.vendor.casefold())
    if obs.object_class and obs.object_class.casefold() not in word_seen:
        words.append(obs.object_class)
        word_seen.add(obs.object_class.casefold())

    return alphanumerics, words


def _record_candidate(
    candidates: dict[str, QueryCandidate],
    score_buckets: dict[str, float],
    text: str,
    provenance: list[str],
    score: float,
) -> None:
    """Accumulate scores and merge provenance for one normalized query."""
    key = text.casefold()
    if not key.strip():
        return
    score_buckets[key] += score
    if key not in candidates:
        candidates[key] = QueryCandidate(
            text=text,
            provenance=list(provenance),
            score=score_buckets[key],
        )
        return

    candidate = candidates[key]
    for item in provenance:
        if item not in candidate.provenance:
            candidate.provenance.append(item)
    candidate.score = score_buckets[key]


def build_query_plan(observations: list[EvidenceObservation], max_queries: int = 5) -> QueryPlan:
    """Build search queries by pairing context words with alphanumeric tokens.

    For each observation, every context word is paired with every
    alphanumeric token.  Queries that include the vendor get a score
    boost.  The raw OCR blob is included as a low-scoring fallback.
    """
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for obs in observations:
        alphanumerics, words = _gather_alphanumerics_and_words(obs)
        vendor_lower = obs.vendor.casefold() if obs.vendor else ""

        # --- Cross-product: each word × each alphanumeric ---
        for word in words:
            for alphanum in alphanumerics:
                query_text = f"{word} {alphanum}"
                # Queries anchored by vendor are more valuable
                score = 5.0 if word.casefold() == vendor_lower else 2.0
                _record_candidate(
                    candidates,
                    score_buckets,
                    query_text,
                    ["word_x_alphanum", obs.evidence_id],
                    score,
                )

        # --- OCR blob fallback (kitchen sink) ---
        if obs.ocr_text.strip():
            truncated = obs.ocr_text.strip().replace("\n", " ")[:120].strip()
            _record_candidate(
                candidates,
                score_buckets,
                truncated,
                ["ocr_blob", obs.evidence_id],
                1.0,
            )

        # --- Analyst hints (always included if present) ---
        if obs.analyst_hints:
            _record_candidate(
                candidates,
                score_buckets,
                " ".join(obs.analyst_hints[:3]),
                ["analyst_hint", obs.evidence_id],
                1.0,
            )

    ranked = sorted(candidates.values(), key=lambda c: (-c.score, c.text))
    return QueryPlan(selected_queries=ranked[:max_queries])
