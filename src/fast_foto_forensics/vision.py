"""Pluggable vision backends for evidence image analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from fast_foto_forensics.models import EvidenceObservation, VisionResult


class VisionExtractionError(RuntimeError):
    """Raised when a vision backend fails to extract structured data."""


@runtime_checkable
class VisionBackend(Protocol):
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...


class FilenameVisionBackend:
    """Derive lightweight labels and identifiers from filenames.

    Moved from pipeline.py. Implements VisionBackend.extract() and retains
    a backward-compatible enrich() method until pipeline.py is rewired (#9).
    """

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        stem_tokens = [
            token
            for token in Path(observation.source_path).stem.replace("_", "-").split("-")
            if token and not token.isdigit()
        ]
        identifiers = [
            token.upper() for token in stem_tokens if any(char.isdigit() for char in token)
        ]
        labels = [token.lower() for token in stem_tokens if token.isalpha()]
        caption = " ".join(labels) if labels else Path(observation.source_path).stem

        return VisionResult(
            evidence_id=observation.evidence_id,
            source_path=observation.source_path,
            source_sha256=observation.sha256,
            backend_name="filename",
            model_name="filename",
            caption=caption,
            ocr_text="",
            candidate_identifiers=identifiers,
            vendor=None,
            object_class=None,
            detected_labels=labels,
        )

    def enrich(self, observation: EvidenceObservation) -> EvidenceObservation:
        """Backward-compatible wrapper used by pipeline.py until #9."""
        result = self.extract(observation)
        observation.caption = result.caption
        observation.ocr_text = result.ocr_text
        observation.detected_labels = list(result.detected_labels)
        observation.candidate_identifiers = list(result.candidate_identifiers)
        return observation


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
