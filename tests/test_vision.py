"""Tests for the vision module (issues #4, #5)."""

from __future__ import annotations

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.vision import (
    FilenameVisionBackend,
    StaticVisionBackend,
    VisionBackend,
    VisionExtractionError,
)


def _sample_fixture() -> VisionResult:
    """Build a VisionResult directly — no from_dict dependency."""
    return VisionResult(
        evidence_id="img-001",
        source_path="evidence/router.jpg",
        source_sha256="abc123",
        backend_name="static",
        model_name="static",
        caption="A blue wireless router with two antennas.",
        ocr_text="WRT54G LINKSYS",
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
        detected_labels=["router", "networking"],
    )


def _sample_observation(evidence_id: str = "img-001") -> EvidenceObservation:
    return EvidenceObservation(
        evidence_id=evidence_id,
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="abc123",
        order_index=0,
    )


class TestStaticVisionBackend:
    def test_returns_fixture_by_evidence_id(self) -> None:
        fixture = _sample_fixture()
        backend = StaticVisionBackend(fixtures={"img-001": fixture})
        observation = _sample_observation()

        result = backend.extract(observation)

        assert result.evidence_id == "img-001"
        assert result.caption == "A blue wireless router with two antennas."
        assert result.candidate_identifiers == ["WRT54G"]

    def test_raises_for_unknown_evidence_id(self) -> None:
        backend = StaticVisionBackend(fixtures={})
        observation = _sample_observation("unknown")

        with pytest.raises(VisionExtractionError, match="unknown"):
            backend.extract(observation)

    def test_satisfies_vision_backend_protocol(self) -> None:
        assert isinstance(StaticVisionBackend(fixtures={}), VisionBackend)


class TestFilenameVisionBackend:
    def test_extracts_labels_and_identifiers_from_filename(self) -> None:
        backend = FilenameVisionBackend()
        observation = EvidenceObservation(
            evidence_id="img-002",
            source_path="evidence/001-WRT54G-router.jpg",
            media_kind="image",
            sha256="def456",
            order_index=0,
        )
        result = backend.extract(observation)
        assert result.evidence_id == "img-002"
        assert result.backend_name == "filename"
        assert result.model_name == "filename"
        assert "WRT54G" in result.candidate_identifiers
        assert "router" in result.detected_labels

    def test_handles_simple_filename(self) -> None:
        backend = FilenameVisionBackend()
        observation = EvidenceObservation(
            evidence_id="img-003",
            source_path="photos/gpu-card.jpg",
            media_kind="image",
            sha256="aaa",
            order_index=0,
        )
        result = backend.extract(observation)
        assert "gpu" in result.detected_labels
        assert "card" in result.detected_labels
        assert result.candidate_identifiers == []  # no alphanumeric tokens
        assert result.caption == "gpu card"

    def test_satisfies_vision_backend_protocol(self) -> None:
        assert isinstance(FilenameVisionBackend(), VisionBackend)

    def test_enrich_compat_method_populates_observation(self) -> None:
        """The backward-compat enrich() method should work for pipeline.py."""
        backend = FilenameVisionBackend()
        observation = EvidenceObservation(
            evidence_id="img-004",
            source_path="evidence/001-WRT54G-router.jpg",
            media_kind="image",
            sha256="def456",
            order_index=0,
        )
        enriched = backend.enrich(observation)
        assert enriched is observation  # mutates in place
        assert "router" in enriched.detected_labels
        assert "WRT54G" in enriched.candidate_identifiers


class TestVisionExtractionError:
    def test_inherits_from_runtime_error(self) -> None:
        assert issubclass(VisionExtractionError, RuntimeError)

    def test_carries_message(self) -> None:
        err = VisionExtractionError("something went wrong")
        assert "something went wrong" in str(err)
