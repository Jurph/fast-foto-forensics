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

2. **Serial number queries** — one per serial_number, combined with
   vendor.  We don't try to guess whether a serial is "really" a model
   number — if searching for it returns product pages, great.  If it
   returns nothing, no harm done.
   Example: ``"Verizon G1A117060503877"``

3. **Label queries** — substantive detected_labels (filtering out port
   names and single-character noise) combined with vendor.
   Example: ``"TP-Link Omada Hardware Controller"``

4. **Fallback** — only when vendor is blank.  Attempts to extract a brand
   from OCR/caption tokens using heuristics.

Vendor + object_class alone (e.g., "Verizon wireless router") is
deliberately excluded — it's too vague to return useful results.
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
    """Rank a small set of high-value queries from extracted evidence.

    Every alphanumeric string the vision model found gets searched.  We
    don't try to classify identifiers as "model" vs. "serial" — that's
    the search engine's job.  If a query returns product pages, it was a
    model number.  If it returns nothing, it was a serial.  Either way,
    the cost of one extra query is low.
    """
    candidates: dict[str, QueryCandidate] = {}
    score_buckets: dict[str, float] = defaultdict(float)

    for obs in observations:
        vendor = obs.vendor
        obj_class = obs.object_class

        # --- Tier 1: candidate_identifiers (highest value) ---
        # These are the alphanumeric strings the vision model flagged as
        # model numbers or part numbers.  Paired with vendor + object_class.
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

        # --- Tier 2: serial_numbers (still worth searching) ---
        # We don't know if these are "really" serials or model numbers.
        # The vision model's classification is a guess.  Searching for
        # them costs one query each, and the results disambiguate for us.
        for serial in obs.serial_numbers:
            parts = []
            provenance = ["serial", obs.evidence_id]
            if vendor:
                parts.append(vendor)
                provenance.append(f"vendor:{vendor}")
            parts.append(serial)

            _record_candidate(
                candidates, score_buckets,
                " ".join(parts), provenance, 5.0,
            )

        # --- Tier 3: substantive labels combined with vendor ---
        good_labels = _substantive_labels(obs)
        if good_labels:
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

        # --- Tier 5: raw OCR text (kitchen sink) ---
        # If we're out of structured data, the OCR blob itself might match
        # user manuals, FCC filings, or forum posts.  Even "boring" tokens
        # like port names can land hits when combined — "USB Reset LAN WAN
        # Coax" is a distinctive enough fingerprint.  Truncate to keep it
        # within a reasonable query length.
        if obs.ocr_text.strip():
            # Take the first ~120 chars — enough for a search engine to
            # work with, short enough to not be rejected as too long.
            truncated = obs.ocr_text.strip().replace("\n", " ")[:120].strip()
            _record_candidate(
                candidates, score_buckets,
                truncated,
                ["ocr_blob", obs.evidence_id],
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
