"""Tests for the vision module (issue #4)."""

from __future__ import annotations

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.vision import (
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


class TestVisionExtractionError:
    def test_inherits_from_runtime_error(self) -> None:
        assert issubclass(VisionExtractionError, RuntimeError)

    def test_carries_message(self) -> None:
        err = VisionExtractionError("something went wrong")
        assert "something went wrong" in str(err)
