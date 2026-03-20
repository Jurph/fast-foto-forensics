"""Tests for schema validation and sidecar tag generation."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import (
    EvidenceObservation,
    ImageTagSet,
    ItemDatasheet,
    SearchHit,
    SynthesisArtifact,
    VisionResult,
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


def test_vision_result_round_trips_through_dict() -> None:
    """Vision results should preserve structured fields through artifact storage."""
    result = VisionResult(
        evidence_id="img-001",
        source_path="evidence/router.jpg",
        source_sha256="deadbeef",
        backend_name="ollama",
        model_name="qwen2.5vl:7b",
        caption="A blue wireless router on a shelf.",
        ocr_text="WRT54G",
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
        detected_labels=["router", "wireless"],
    )

    restored = VisionResult.from_dict(result.to_dict())

    assert restored == result


def test_vision_result_from_dict_accepts_optional_fields_as_missing() -> None:
    """Vendor and object class should remain optional when not identified."""
    payload = {
        "evidence_id": "img-002",
        "source_path": "evidence/unknown.jpg",
        "source_sha256": "beadfeed",
        "backend_name": "static",
        "model_name": "fixture",
        "caption": "An unknown expansion card.",
        "ocr_text": "",
        "candidate_identifiers": [],
        "detected_labels": ["card"],
    }

    restored = VisionResult.from_dict(payload)

    assert restored.vendor is None
    assert restored.object_class is None
    assert restored.detected_labels == ["card"]


def test_vision_result_from_dict_requires_core_identity_fields() -> None:
    """Persisted vision artifacts should fail fast when required fields are missing."""
    payload = {
        "source_path": "evidence/missing-id.jpg",
        "source_sha256": "c0ffee",
        "backend_name": "ollama",
        "model_name": "qwen2.5vl:7b",
        "caption": "A blurry GPU photo.",
        "ocr_text": "GTX 480",
        "candidate_identifiers": ["GTX 480"],
        "detected_labels": ["gpu"],
    }

    with pytest.raises(ValueError, match="evidence_id"):
        VisionResult.from_dict(payload)


def test_vision_result_confidence_round_trips() -> None:
    """Confidence field should survive serialization and default to 0.0."""
    result = VisionResult(
        evidence_id="img-005",
        source_path="evidence/gpu.jpg",
        source_sha256="aabb",
        backend_name="ollama",
        model_name="qwen2.5vl:7b",
        caption="A GPU.",
        ocr_text="GTX 1080",
        candidate_identifiers=["GTX 1080"],
        vendor="NVIDIA",
        object_class="gpu",
        detected_labels=["gpu"],
        confidence=0.85,
    )
    payload = result.to_dict()
    assert payload["confidence"] == 0.85

    restored = VisionResult.from_dict(payload)
    assert restored.confidence == 0.85

    # Default when missing from payload
    del payload["confidence"]
    restored_default = VisionResult.from_dict(payload)
    assert restored_default.confidence == 0.0


def test_synthesis_artifact_round_trips_through_dict() -> None:
    """Synthesis artifacts should preserve provenance through artifact storage."""
    artifact = SynthesisArtifact(
        backend_name="ollama",
        model_name="qwen2.5vl:7b",
        schema_name="ItemDatasheet",
        prompt_text="Return only structured datasheet JSON.",
        raw_payload='{"probable_identity":"WRT54G"}',
        accepted=True,
        attempt_count=1,
        last_error=None,
    )

    restored = SynthesisArtifact.from_dict(artifact.to_dict())

    assert restored == artifact


def test_synthesis_artifact_requires_core_metadata() -> None:
    """Persisted synthesis artifacts should fail fast when identity fields are missing."""
    payload = {
        "backend_name": "ollama",
        "model_name": "qwen2.5vl:7b",
        "raw_payload": "{}",
        "accepted": False,
        "attempt_count": 2,
    }

    with pytest.raises(ValueError, match="schema_name"):
        SynthesisArtifact.from_dict(payload)


def test_synthesis_artifact_defaults_last_error_to_none() -> None:
    """Synthesis artifacts should tolerate a missing last_error field."""
    payload = {
        "backend_name": "ollama",
        "model_name": "qwen2.5vl:7b",
        "schema_name": "ItemDatasheet",
        "raw_payload": "{}",
        "accepted": False,
        "attempt_count": 2,
    }

    restored = SynthesisArtifact.from_dict(payload)

    assert restored.last_error is None
    assert restored.prompt_text is None
    assert restored.accepted is False
    assert restored.attempt_count == 2
