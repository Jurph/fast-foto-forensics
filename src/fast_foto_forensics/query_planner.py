"""Deterministic search query planning.

Builds ranked web-search queries from enriched EvidenceObservations.

The planner trusts the structured fields that the vision backend already
extracted (vendor, object_class, candidate_identifiers) rather than
re-deriving them from raw OCR text.  It only falls back to token-level
heuristics when those fields are empty — e.g., when using the lightweight
FilenameVisionBackend that can't identify a vendor.

Query tiers (highest value first)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Identifier queries** — one per candidate_identifier, combined with
   vendor and object_class when available.
   Example: ``"TP-Link OC200 wireless router"``

2. **Vendor + class query** — vendor and object_class without a specific
   model number.  Catches cases where identifiers are misread but the
   brand/category are solid.
   Example: ``"TP-Link wireless router"``

3. **Label queries** — substantive detected_labels (filtering out port
   names and single-character noise) combined with vendor.
   Example: ``"TP-Link Omada hardware controller"``

4. **Fallback** — only when vendor is blank.  Attempts to extract a brand
   from OCR/caption tokens using the old heuristic approach.

Serial numbers are deliberately excluded — they're unique to one physical
unit and won't return useful product-info results from a web search.
"""

from __future__ import annotations

from collections import defaultdict

from fast_foto_forensics.models import EvidenceObservation, QueryCandidate, QueryPlan, tokenize_text

# Labels that describe ports, buttons, or other noise — not useful as
# search terms on their own.
_NOISE_LABELS = {
    "act", "cloud", "coax", "dc", "eth", "eth1", "eth2", "eth3", "eth4",
    "lan", "led", "link", "poe", "power", "reset", "usb", "wan", "wlan",
    "wps", "link/act",
}

# OCR fragments that are metadata prefixes, not searchable product info.
_LOW_VALUE_OCR_TOKENS = {
    "fcc", "id", "mac", "pn", "part", "rev", "serial", "sn", "ssid", "ver",
    "hw", "firmware", "version", "shipped", "note", "important", "designed",
    "specifically", "impact", "performance", "services", "use", "other",
    "may", "network",
}

_STOPWORDS = {
    "and", "for", "from", "the", "this", "that", "with", "into", "onto",
    "over", "under", "near", "blue", "dusty", "old", "tall", "small",
    "large", "shelf", "workbench", "various", "cables", "connected",
    "back", "panel", "front", "side", "view", "image", "photo",
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


def _substantive_labels(observation: EvidenceObservation) -> list[str]:
    """Filter detected_labels to those worth searching for.

    Keeps multi-word labels and single-word labels that aren't port names
    or generic noise.
    """
    labels: list[str] = []
    for label in observation.detected_labels:
        stripped = label.strip()
        if not stripped:
            continue
        # Multi-word labels like "Omada Hardware Controller" are almost
        # always substantive product names.
        if " " in stripped:
            labels.append(stripped)
            continue
        # Single-word: skip port names and noise
        if stripped.casefold() in _NOISE_LABELS:
            continue
        # Skip the vendor name itself — it'll already be in the query
        if observation.vendor and stripped.casefold() == observation.vendor.casefold():
            continue
        labels.append(stripped)
    return labels


def _fallback_brand_tokens(observation: EvidenceObservation) -> list[str]:
    """Last-resort brand extraction from OCR/caption when vendor is blank.

    Only called when the vision backend didn't identify a vendor (e.g.,
    FilenameVisionBackend).  Scans OCR and caption tokens for anything
    that isn't a known stopword, noise token, or identifier.
    """
    identifier_tokens = {
        token.casefold() for token in tokenize_text(*observation.candidate_identifiers)
    }
    label_tokens = {
        token.casefold() for token in tokenize_text(*observation.detected_labels)
    }
    exclude = _STOPWORDS | _LOW_VALUE_OCR_TOKENS | identifier_tokens | label_tokens

    seen: set[str] = set()
    brands: list[str] = []
    for token in tokenize_text(observation.ocr_text, observation.caption):
        key = token.casefold()
        if key in exclude or key in seen or key.isdigit():
            continue
        seen.add(key)
        brands.append(token)
        if len(brands) >= 2:
            break
    return brands


def build_query_plan(observations: list[EvidenceObservation], max_queries: int = 5) -> QueryPlan:
    """Rank a small set of high-value queries from extracted evidence."""
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for obs in observations:
        vendor = obs.vendor
        obj_class = obs.object_class

        # --- Tier 1: identifier queries (highest value) ---
        for identifier in obs.candidate_identifiers:
            parts = []
            provenance = ["identifier", obs.evidence_id]
            if vendor:
                parts.append(vendor)
                provenance.append(f"vendor:{vendor}")
            parts.append(identifier)
            if obj_class:
                parts.append(obj_class)
                provenance.append(f"class:{obj_class}")

            _record_candidate(
                candidates, score_buckets,
                " ".join(parts), provenance, 10.0,
            )

        # --- Tier 2: vendor + object_class (no specific identifier) ---
        if vendor and obj_class:
            _record_candidate(
                candidates, score_buckets,
                f"{vendor} {obj_class}",
                ["vendor+class", obs.evidence_id],
                5.0,
            )

        # --- Tier 3: substantive labels combined with vendor ---
        good_labels = _substantive_labels(obs)
        if good_labels:
            # Build one query from the best labels
            parts = []
            if vendor:
                parts.append(vendor)
            # Take up to 3 substantive labels
            parts.extend(good_labels[:3])
            _record_candidate(
                candidates, score_buckets,
                " ".join(parts),
                ["labels", obs.evidence_id],
                3.0,
            )

        # --- Tier 4: fallback when vendor is blank ---
        if not vendor:
            fallback_brands = _fallback_brand_tokens(obs)
            if fallback_brands:
                parts = list(fallback_brands)
                if obj_class:
                    parts.append(obj_class)
                elif obs.detected_labels:
                    parts.append(obs.detected_labels[0])
                _record_candidate(
                    candidates, score_buckets,
                    " ".join(parts),
                    ["fallback_brand", obs.evidence_id],
                    1.0,
                )

        # --- Analyst hints (always included if present) ---
        if obs.analyst_hints:
            _record_candidate(
                candidates, score_buckets,
                " ".join(obs.analyst_hints[:3]),
                ["analyst_hint", obs.evidence_id],
                1.0,
            )

    ranked = sorted(candidates.values(), key=lambda c: (-c.score, c.text))
    return QueryPlan(selected_queries=ranked[:max_queries])
