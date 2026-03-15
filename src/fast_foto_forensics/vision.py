"""Pluggable vision backends for evidence image analysis."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fast_foto_forensics.models import EvidenceObservation, VisionResult


class VisionExtractionError(RuntimeError):
    """Raised when a vision backend fails to extract structured data."""


@runtime_checkable
class VisionBackend(Protocol):
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...


class StaticVisionBackend:
    """Return canned VisionResult objects keyed by evidence_id."""

    def __init__(self, fixtures: dict[str, VisionResult]) -> None:
        self._fixtures = fixtures

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        result = self._fixtures.get(observation.evidence_id)
        if result is None:
            raise VisionExtractionError(
                f"no fixture for evidence_id={observation.evidence_id!r}"
            )
        return result
