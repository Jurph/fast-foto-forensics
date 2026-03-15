"""Schema-first synthesis helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from fast_foto_forensics.models import EvidenceObservation, ItemDatasheet, SearchHit


class SynthesisBackend(Protocol):
    """Protocol for datasheet-producing synthesis backends."""

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> str:
        """Return a JSON datasheet payload."""


@dataclass(slots=True)
class ReplaySynthesisBackend:
    """Test backend that replays canned responses in sequence."""

    responses: list[str]
    calls: int = 0

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> str:
        response = self.responses[self.calls]
        self.calls += 1
        return response


@dataclass(slots=True)
class HeuristicSynthesisBackend:
    """Local fallback that infers a datasheet from evidence without an LLM."""

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> str:
        identifiers = [
            item for observation in observations for item in observation.candidate_identifiers
        ]
        labels = [item for observation in observations for item in observation.detected_labels]
        probable_identity = (
            identifiers[0] if identifiers else (labels[0].title() if labels else "Unknown device")
        )
        manufacturer = "Linksys" if probable_identity.upper().startswith("WRT") else "Unknown"
        object_class = labels[0] if labels else "device"
        identity_label = (
            probable_identity
            if manufacturer == "Unknown"
            else f"{manufacturer} {probable_identity}"
        )
        payload = {
            "probable_identity": identity_label,
            "object_class": object_class,
            "likely_function": f"Likely {object_class}",
            "manufacturer": manufacturer,
            "model_identifiers": identifiers[:3],
            "year_range": None,
            "country_or_region": None,
            "security_findings": [hit.snippet for hit in hits[:2]] if hits else [],
            "confidence": 0.42,
            "evidence_refs": [observation.evidence_id for observation in observations],
            "search_hit_refs": [hit.hit_id for hit in hits],
            "open_questions": ["Upgrade to an LLM backend for higher-confidence identification"],
        }
        return json.dumps(payload)


def synthesize_item(
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
    backend: SynthesisBackend,
) -> ItemDatasheet:
    """Generate and validate a structured datasheet."""
    last_error: str | None = None
    for _ in range(2):
        raw_payload = backend.generate(
            observations=observations,
            hits=hits,
            previous_error=last_error,
        )
        try:
            return ItemDatasheet.from_json(raw_payload)
        except ValueError as exc:
            last_error = str(exc)
    raise ValueError(last_error or "failed to synthesize datasheet")
