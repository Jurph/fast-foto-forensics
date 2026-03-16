"""Schema-first synthesis helpers."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from typing import Any, Protocol

from fast_foto_forensics.models import (
    EvidenceObservation,
    ItemDatasheet,
    SearchHit,
    SynthesisArtifact,
)

_ITEM_DATASHEET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "probable_identity": {"type": "string"},
        "object_class": {"type": "string"},
        "likely_function": {"type": "string"},
        "manufacturer": {"type": "string"},
        "model_identifiers": {"type": "array", "items": {"type": "string"}},
        "year_range": {"type": ["string", "null"]},
        "country_or_region": {"type": ["string", "null"]},
        "security_findings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "search_hit_refs": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "probable_identity",
        "object_class",
        "likely_function",
        "manufacturer",
        "model_identifiers",
    ],
}


class SynthesisError(RuntimeError):
    """Raised when a synthesis backend cannot produce a usable payload."""


class SynthesisFailure(ValueError):
    """Raised when synthesis could not produce a valid datasheet payload."""

    def __init__(self, artifact: SynthesisArtifact):
        super().__init__(artifact.last_error or "failed to synthesize datasheet")
        self.artifact = artifact


class SynthesisBackend(Protocol):
    """Protocol for datasheet-producing synthesis backends."""

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> SynthesisArtifact | str:
        """Return synthesis provenance, or a raw payload for legacy callers."""


def _build_synthesis_prompt(
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
) -> str:
    """Build a compact synthesis prompt from normalized evidence and search hits."""
    payload = {
        "observations": [
            {
                "evidence_id": observation.evidence_id,
                "caption": observation.caption,
                "ocr_text": observation.ocr_text,
                "candidate_identifiers": observation.candidate_identifiers,
                "vendor": observation.vendor,
                "object_class": observation.object_class,
                "detected_labels": observation.detected_labels,
            }
            for observation in observations
        ],
        "search_hits": [
            {
                "hit_id": hit.hit_id,
                "provider": hit.provider,
                "query": hit.query,
                "title": hit.title,
                "snippet": hit.snippet,
                "url": hit.url,
            }
            for hit in hits
        ],
    }
    return (
        "Analyze the evidence observations and search hits. "
        "Return only a datasheet that matches the provided JSON schema.\n\n"
        f"{json.dumps(payload, indent=2)}"
    )


def _strip_code_fences(raw_payload: str) -> str:
    """Remove accidental Markdown fences around a JSON payload."""
    raw = raw_payload.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    return raw


def _coerce_artifact(
    generated: SynthesisArtifact | str,
    backend: SynthesisBackend,
) -> SynthesisArtifact:
    """Wrap legacy raw JSON payloads in a provenance artifact."""
    if isinstance(generated, SynthesisArtifact):
        return generated
    backend_name = getattr(backend, "__class__", type(backend)).__name__
    return SynthesisArtifact(
        backend_name=backend_name,
        model_name=backend_name,
        schema_name="ItemDatasheet",
        raw_payload=str(generated),
        accepted=False,
        attempt_count=1,
        last_error=None,
    )


def _artifact_from_backend_error(
    backend: SynthesisBackend,
    attempt_count: int,
    error: Exception,
) -> SynthesisArtifact:
    """Build a provenance record for a backend-level failure."""
    backend_name = getattr(backend, "__class__", type(backend)).__name__
    model_name = getattr(backend, "model", backend_name)
    return SynthesisArtifact(
        backend_name=str(backend_name),
        model_name=str(model_name),
        schema_name="ItemDatasheet",
        raw_payload="",
        accepted=False,
        attempt_count=attempt_count,
        last_error=str(error),
    )


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
    ) -> SynthesisArtifact:
        response = self.responses[self.calls]
        self.calls += 1
        return SynthesisArtifact(
            backend_name="replay",
            model_name="fixture",
            schema_name="ItemDatasheet",
            raw_payload=response,
            accepted=False,
            attempt_count=1,
            last_error=None,
        )


@dataclass(slots=True)
class HeuristicSynthesisBackend:
    """Local fallback that infers a datasheet from evidence without an LLM."""

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> SynthesisArtifact:
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
        return SynthesisArtifact(
            backend_name="heuristic",
            model_name="heuristic",
            schema_name="ItemDatasheet",
            raw_payload=json.dumps(payload),
            accepted=False,
            attempt_count=1,
            last_error=None,
        )


@dataclass
class OllamaDatasheetSynthesisBackend:
    """Generate ItemDatasheet payloads via Ollama structured-output mode."""

    model: str = "qwen3:8b"

    def _call_ollama(self, **kwargs):
        """Thin wrapper around ollama.chat() for monkeypatching in tests."""
        try:
            ollama_module: Any = importlib.import_module("ollama")
        except ImportError as exc:
            raise SynthesisError(
                "ollama package not installed. Install with: "
                "pip install fast-foto-forensics[vision_ollama]"
            ) from exc
        return ollama_module.chat(**kwargs)

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> SynthesisArtifact:
        response = self._call_ollama(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a digital forensics assistant. "
                        "Return only structured datasheet JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_synthesis_prompt(observations, hits),
                },
            ],
            format=_ITEM_DATASHEET_SCHEMA,
            stream=False,
        )
        raw_payload = _strip_code_fences(response.message.content)
        return SynthesisArtifact(
            backend_name="ollama",
            model_name=self.model,
            schema_name="ItemDatasheet",
            raw_payload=raw_payload,
            accepted=False,
            attempt_count=1,
            last_error=None,
        )


@dataclass
class RemoteDatasheetSynthesisBackend:
    """Stub for future remote/frontier datasheet synthesis."""

    model: str = "gpt-5.4-mini"

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> SynthesisArtifact:
        raise SynthesisError(
            "remote synthesis backend not implemented; use local Ollama synthesis for now"
        )


def synthesize_item_with_artifact(
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
    backend: SynthesisBackend,
) -> tuple[ItemDatasheet, SynthesisArtifact]:
    """Generate and validate a structured datasheet plus provenance."""
    last_artifact: SynthesisArtifact | None = None

    for attempt in range(1, 3):
        try:
            artifact = _coerce_artifact(
                backend.generate(
                    observations=observations,
                    hits=hits,
                ),
                backend,
            )
        except Exception as exc:
            last_artifact = _artifact_from_backend_error(backend, attempt, exc)
            raise SynthesisFailure(last_artifact) from exc

        artifact = replace(artifact, attempt_count=attempt)
        try:
            datasheet = ItemDatasheet.from_json(artifact.raw_payload)
        except ValueError as exc:
            last_artifact = replace(
                artifact,
                accepted=False,
                last_error=str(exc),
                attempt_count=attempt,
            )
            continue

        return datasheet, replace(
            artifact,
            accepted=True,
            last_error=None,
            attempt_count=attempt,
        )

    if last_artifact is None:
        last_artifact = _artifact_from_backend_error(
            backend,
            1,
            SynthesisError("failed to synthesize datasheet"),
        )
    raise SynthesisFailure(last_artifact)


def synthesize_item(
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
    backend: SynthesisBackend,
) -> ItemDatasheet:
    """Generate and validate a structured datasheet."""
    datasheet, _artifact = synthesize_item_with_artifact(observations, hits, backend)
    return datasheet
