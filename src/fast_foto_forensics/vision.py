"""Pluggable vision backends for evidence image analysis."""

from __future__ import annotations

import base64
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fast_foto_forensics.models import EvidenceObservation, VisionResult

logger = logging.getLogger(__name__)

_VISION_PROMPT = """\
Examine this image carefully. Return ONLY a JSON object with these fields:
- "caption": a one-sentence description of what you see
- "ocr_text": all visible text, transcribed exactly as it appears
- "candidate_identifiers": list of serial numbers, model numbers, or part numbers found
- "vendor": manufacturer name if identifiable, otherwise ""
- "object_class": general category (e.g. "wireless router", "GPU", "circuit board")
- "detected_labels": list of all readable labels, markings, or stickers"""


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
            raise VisionExtractionError(f"no fixture for evidence_id={observation.evidence_id!r}")
        return result


class OllamaVisionBackend:
    """Send images to a local Ollama vision model and parse structured JSON."""

    def __init__(self, model: str = "qwen2.5vl:7b") -> None:
        self._model = model

    def _call_ollama(self, **kwargs):
        """Thin wrapper around ollama.chat() for monkeypatching in tests."""
        try:
            ollama_module: Any = importlib.import_module("ollama")
        except ImportError as exc:
            raise VisionExtractionError(
                "ollama package not installed. Install with: pip install fast-foto-forensics[vision_ollama]"
            ) from exc
        return ollama_module.chat(**kwargs)

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        image_path = Path(observation.source_path)
        if not image_path.is_file():
            raise VisionExtractionError(f"Image file not found: {observation.source_path}")

        image_bytes = image_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        last_error: Exception | None = None
        for attempt in range(2):
            response = self._call_ollama(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": _VISION_PROMPT,
                        "images": [image_b64],
                    }
                ],
            )
            raw = response.message.content
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning(
                    "Attempt %d: failed to parse JSON from Ollama response: %s",
                    attempt + 1,
                    exc,
                )
                continue

            return VisionResult(
                evidence_id=observation.evidence_id,
                source_path=observation.source_path,
                source_sha256=observation.sha256,
                backend_name="ollama",
                model_name=self._model,
                caption=data.get("caption", ""),
                ocr_text=data.get("ocr_text", ""),
                candidate_identifiers=data.get("candidate_identifiers", []),
                vendor=data.get("vendor", "") or None,
                object_class=data.get("object_class", "") or None,
                detected_labels=data.get("detected_labels", []),
            )

        raise VisionExtractionError(
            "Failed to parse valid JSON from Ollama after 2 attempts"
        ) from last_error


def extract_with_cache(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: Any,
) -> VisionResult:
    """Extract vision data, using the RunStore artifact cache when possible.

    Cache validity requires the stored sha256 to match the current observation.
    On a miss or mismatch the backend is called and the result is persisted.
    """
    cache_path = f"vision/{observation.evidence_id}.json"

    try:
        payload = store.read_json_artifact(cache_path)
        cached = VisionResult.from_dict(payload)
        if cached.source_sha256 == observation.sha256:
            logger.debug("Cache hit for %s", observation.evidence_id)
            return cached
        logger.debug("Cache stale for %s (sha256 mismatch)", observation.evidence_id)
    except (FileNotFoundError, ValueError, KeyError):
        logger.debug("Cache miss for %s", observation.evidence_id)

    result = backend.extract(observation)
    store.write_json_artifact(cache_path, result.to_dict())
    return result
