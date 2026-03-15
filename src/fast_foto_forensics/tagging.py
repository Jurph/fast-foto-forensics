"""Sidecar tag generation for parsed evidence."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fast_foto_forensics.models import EvidenceObservation, ImageTagSet, ItemDatasheet, SearchHit


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def build_tag_set(
    observation: EvidenceObservation,
    datasheet: ItemDatasheet,
    search_hits: list[SearchHit],
) -> ImageTagSet:
    """Build a reusable sidecar tag payload from extracted evidence."""
    tags = _dedupe_keep_order(
        observation.detected_labels
        + observation.candidate_identifiers
        + [datasheet.object_class, datasheet.manufacturer, datasheet.probable_identity]
        + datasheet.model_identifiers
        + observation.analyst_hints
    )
    search_terms = [hit.query for hit in search_hits]
    return ImageTagSet(tags=tags, caption=observation.caption, search_terms=search_terms)


def write_tag_sidecar(source_path: Path, tag_set: ImageTagSet) -> Path:
    """Persist a JSON sidecar next to the original evidence file."""
    sidecar_path = source_path.with_suffix(source_path.suffix + ".fff-tags.json")
    sidecar_path.write_text(json.dumps(asdict(tag_set), indent=2, sort_keys=True), encoding="utf-8")
    return sidecar_path
