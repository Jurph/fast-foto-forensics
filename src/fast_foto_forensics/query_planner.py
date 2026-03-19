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
from dataclasses import dataclass

from fast_foto_forensics.models import EvidenceObservation, QueryCandidate, QueryPlan

_MAC_ADDRESS_PATTERN = re.compile(
    r"^(?:[0-9A-Fa-f]{2}([:\-.]))(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}$"
)
_TRIM_TOKEN_PATTERN = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")


@dataclass(frozen=True, slots=True)
class IdentifierSignal:
    """One identifier-like token plus its planner classification."""

    token: str
    kind: str


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


def _clean_token(token: str) -> str:
    """Trim obvious punctuation while preserving model separators like dots and hyphens."""
    return _TRIM_TOKEN_PATTERN.sub("", token.strip())


def _classify_shape_based_identifier(token: str) -> str:
    """Classify an alphanumeric token when only its shape is known."""
    compact = re.sub(r"[^A-Za-z0-9]", "", token)
    if _MAC_ADDRESS_PATTERN.match(token):
        return "instance_like"
    if len(compact) >= 12 and is_alphanumeric(token):
        return "instance_like"
    if 4 <= len(compact) <= 10 and is_alphanumeric(token):
        return "ambiguous"
    return "ambiguous"


def _gather_identifier_signals(obs: EvidenceObservation) -> list[IdentifierSignal]:
    """Collect identifier-like tokens with source-aware classifications."""
    signals: list[IdentifierSignal] = []
    seen: set[str] = set()

    def add(token: str, kind: str) -> None:
        cleaned = _clean_token(token)
        if not cleaned or not is_alphanumeric(cleaned):
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        signals.append(IdentifierSignal(token=cleaned, kind=kind))

    for token in obs.candidate_identifiers:
        add(token, "model_like")
    for token in obs.serial_numbers:
        add(token, "instance_like")

    for token in obs.detected_labels:
        cleaned = _clean_token(token)
        if cleaned and is_alphanumeric(cleaned):
            add(cleaned, _classify_shape_based_identifier(cleaned))

    for token in _extract_tokens(obs.ocr_text):
        cleaned = _clean_token(token)
        if cleaned and is_alphanumeric(cleaned):
            add(cleaned, _classify_shape_based_identifier(cleaned))

    for token in _extract_tokens(obs.caption):
        cleaned = _clean_token(token)
        if cleaned and is_alphanumeric(cleaned):
            add(cleaned, _classify_shape_based_identifier(cleaned))

    return signals


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
    identifier_signals = _gather_identifier_signals(obs)
    alphanumerics = [signal.token for signal in identifier_signals]
    alphanum_seen = {token.casefold() for token in alphanumerics}
    all_tokens: list[str] = []

    # Start with the vision model's structured output
    all_tokens.extend(obs.detected_labels)

    # Add OCR and caption tokens
    all_tokens.extend(_extract_tokens(obs.ocr_text))
    all_tokens.extend(_extract_tokens(obs.caption))

    # Separate into alphanumerics and words
    word_seen: set[str] = set()
    words: list[str] = []

    for token in all_tokens:
        stripped = _clean_token(token)
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


def _choose_query_mode(obs: EvidenceObservation, signals: list[IdentifierSignal]) -> str:
    """Choose whether to search for identity, mixed evidence, or documents."""
    has_context = bool(obs.vendor or obs.object_class)
    if has_context and any(signal.kind == "model_like" for signal in signals):
        return "document"
    if has_context and any(signal.kind == "ambiguous" for signal in signals):
        return "mixed"
    return "identity"


def _preferred_doc_anchors(obs: EvidenceObservation, signals: list[IdentifierSignal]) -> list[str]:
    """Build doc-intent anchors from the best available identifier signals."""
    anchors: list[str] = []
    seen: set[str] = set()
    preferred_signals = [signal for signal in signals if signal.kind in {"model_like", "ambiguous"}]

    for signal in preferred_signals:
        candidates: list[str] = []
        if obs.vendor:
            candidates.append(f"{obs.vendor} {signal.token}")
        if obs.object_class:
            candidates.append(f"{signal.token} {obs.object_class}")
        if not candidates:
            candidates.append(signal.token)

        for anchor in candidates:
            key = anchor.casefold()
            if key in seen:
                continue
            seen.add(key)
            anchors.append(anchor)

    return anchors


def _record_candidate(
    candidates: dict[str, QueryCandidate],
    score_buckets: dict[str, float],
    text: str,
    provenance: list[str],
    score: float,
    explanation: str,
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
            explanation=explanation,
        )
        return

    candidate = candidates[key]
    for item in provenance:
        if item not in candidate.provenance:
            candidate.provenance.append(item)
    candidate.score = score_buckets[key]
    if explanation and explanation not in candidate.explanation:
        candidate.explanation = explanation


def _build_query_explanation(query_text: str, provenance: list[str]) -> str:
    """Render a concise human-readable explanation for one query."""
    evidence_refs = [
        item for item in provenance if item.startswith("img-") or item.startswith("obs-")
    ]
    evidence_label = ", ".join(evidence_refs) if evidence_refs else "this observation"
    if "document_query" in provenance:
        return f"Doc-seeking query built from vendor/model anchors in {evidence_label}."
    if "mixed_query" in provenance:
        return f"Mixed identity/doc query built from an ambiguous identifier in {evidence_label}."
    if "analyst_hint" in provenance:
        return f"Analyst hint carried into search from {evidence_label}."
    if "ocr_blob" in provenance:
        return f"OCR fallback query launched from text seen in {evidence_label}."
    if "word_x_alphanum" in provenance:
        return (
            f"Context-word plus identifier query built from extracted evidence in {evidence_label}."
        )
    return f"Search launched for '{query_text}' based on extracted evidence in {evidence_label}."


def build_query_plan(observations: list[EvidenceObservation], max_queries: int = 5) -> QueryPlan:
    """Build search queries by pairing context words with alphanumeric tokens.

    For each observation, every context word is paired with every
    alphanumeric token.  Queries that include the vendor get a score
    boost.  The raw OCR blob is included as a low-scoring fallback.
    """
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for obs in observations:
        identifier_signals = _gather_identifier_signals(obs)
        alphanumerics, words = _gather_alphanumerics_and_words(obs)
        vendor_lower = obs.vendor.casefold() if obs.vendor else ""
        query_mode = _choose_query_mode(obs, identifier_signals)

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
                    _build_query_explanation(query_text, ["word_x_alphanum", obs.evidence_id]),
                )

        # --- Technical-document variants when the anchor signal is strong enough ---
        doc_anchors = _preferred_doc_anchors(obs, identifier_signals)
        if query_mode == "document":
            for anchor in doc_anchors[:1]:
                for suffix, score in (
                    ("datasheet", 4.5),
                    ("manual", 4.0),
                    ("specifications", 3.5),
                ):
                    _record_candidate(
                        candidates,
                        score_buckets,
                        f"{anchor} {suffix}",
                        [f"{query_mode}_query", obs.evidence_id],
                        score,
                        _build_query_explanation(
                            f"{anchor} {suffix}",
                            [f"{query_mode}_query", obs.evidence_id],
                        ),
                    )
        elif query_mode == "mixed" and doc_anchors:
            _record_candidate(
                candidates,
                score_buckets,
                f"{doc_anchors[0]} datasheet",
                [f"{query_mode}_query", obs.evidence_id],
                2.5,
                _build_query_explanation(
                    f"{doc_anchors[0]} datasheet",
                    [f"{query_mode}_query", obs.evidence_id],
                ),
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
                _build_query_explanation(truncated, ["ocr_blob", obs.evidence_id]),
            )

        # --- Analyst hints (always included if present) ---
        if obs.analyst_hints:
            _record_candidate(
                candidates,
                score_buckets,
                " ".join(obs.analyst_hints[:3]),
                ["analyst_hint", obs.evidence_id],
                1.0,
                _build_query_explanation(
                    " ".join(obs.analyst_hints[:3]),
                    ["analyst_hint", obs.evidence_id],
                ),
            )

    ranked = sorted(candidates.values(), key=lambda c: (-c.score, c.text))
    return QueryPlan(selected_queries=ranked[:max_queries])
