"""Tests for schema validation and sidecar tag generation."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import (
    EvidenceObservation,
    ImageTagSet,
    ItemDatasheet,
    SearchHit,
)
from fast_foto_forensics.tagging import build_tag_set


def test_item_datasheet_from_json_requires_core_fields() -> None:
    """Datasheets should reject incomplete JSON payloads."""
    raw_payload = json.dumps(
        {
            "object_class": "gpu",
            "manufacturer": "NVIDIA",
        }
    )

    with pytest.raises(ValueError, match="probable_identity"):
        ItemDatasheet.from_json(raw_payload)


def test_build_tag_set_combines_datasheet_and_search_context() -> None:
    """Sidecar tags should preserve the most useful reusable terms."""
    observation = EvidenceObservation(
        evidence_id="img-001",
        source_path="evidence/gpu-card.jpg",
        media_kind="image",
        sha256="abc123",
        order_index=0,
        caption="A dusty graphics card on a workbench.",
        ocr_text="GEFORCE GTX 480",
        detected_labels=["gpu", "pc hardware"],
        candidate_identifiers=["GTX 480"],
        analyst_hints=["article-demo"],
    )
    datasheet = ItemDatasheet(
        probable_identity="NVIDIA GeForce GTX 480",
        object_class="gpu",
        likely_function="Legacy graphics accelerator",
        manufacturer="NVIDIA",
        model_identifiers=["GTX 480"],
        year_range="2010-2011",
        country_or_region="Taiwan",
        security_findings=["No known CVE from local data"],
        confidence=0.84,
        evidence_refs=["img-001"],
        search_hit_refs=["hit-001"],
        open_questions=["Confirm exact board partner"],
    )
    search_hits = [
        SearchHit(
            hit_id="hit-001",
            provider="duckduckgo",
            query="GTX 480 release date",
            title="GeForce GTX 480 specifications",
            snippet="The GTX 480 launched in 2010 as a high-end GPU.",
            url="https://example.com/gtx-480",
        )
    ]

    tags = build_tag_set(observation, datasheet, search_hits)

    assert isinstance(tags, ImageTagSet)
    assert "gpu" in tags.tags
    assert "nvidia" in tags.tags
    assert "gtx 480" in tags.tags
    assert tags.caption == observation.caption
    assert tags.search_terms[0] == "GTX 480 release date"
