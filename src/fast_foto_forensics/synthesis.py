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


def _repair_json(raw: str) -> str:
    """Best-effort repair of common LLM JSON mistakes.

    Handles:
    - Markdown code fences (delegated to _strip_code_fences)
    - Trailing commas before } or ]
    - Single-quoted strings (only when standard parse fails)
    - Truncated JSON (unclosed braces/brackets)
    """
    import re

    cleaned = _strip_code_fences(raw)

    # Try parsing as-is first
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # Remove spurious/trailing commas: ,} ,] and repeated commas like ],  ,
    cleaned = re.sub(r",(\s*,)+", ",", cleaned)  # collapse comma runs
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)  # strip trailing comma
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # Try replacing single quotes with double quotes
    single_quoted = cleaned.replace("'", '"')
    try:
        json.loads(single_quoted)
        return single_quoted
    except json.JSONDecodeError:
        pass

    # Try closing truncated JSON by appending missing braces/brackets
    opens = cleaned.count("{") - cleaned.count("}")
    closes = cleaned.count("[") - cleaned.count("]")
    if opens > 0 or closes > 0:
        patched = cleaned + ("]" * closes) + ("}" * opens)
        try:
            json.loads(patched)
            return patched
        except json.JSONDecodeError:
            pass

    # Give up — return the best we got so the caller gets a clear error
    return cleaned


def _backfill_citations(
    data: dict[str, Any],
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
) -> dict[str, Any]:
    """Ensure evidence_refs and search_hit_refs are populated.

    LLMs sometimes drop citation fields even when the evidence was in the
    prompt.  Backfilling from the actual inputs is safe — the model saw
    exactly these items.
    """
    if not data.get("evidence_refs"):
        data["evidence_refs"] = [obs.evidence_id for obs in observations]
    if not data.get("search_hit_refs"):
        data["search_hit_refs"] = [hit.hit_id for hit in hits]

    # Clamp confidence to [0.0, 1.0]
    conf = data.get("confidence")
    if isinstance(conf, (int, float)):
        data["confidence"] = max(0.0, min(1.0, float(conf)))

    return data


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
    """Generate ItemDatasheet payloads via an OpenAI-compatible chat API.

    Works with any endpoint that speaks the OpenAI ``/v1/chat/completions``
    protocol, including OpenAI, Azure OpenAI, vLLM, and Ollama's
    OpenAI-compatible mode.

    Configuration is resolved in order:
      1. Explicit ``api_key`` / ``api_base`` constructor arguments
      2. ``FAST_FOTO_API_KEY`` / ``FAST_FOTO_API_BASE`` environment variables
      3. ``OPENAI_API_KEY`` fallback for the key
    """

    model: str = "gpt-4o-mini"
    api_base: str | None = None
    api_key: str | None = None
    timeout: float = 30.0

    def _resolve_config(self) -> tuple[str, str]:
        """Resolve API base URL and key from fields or environment."""
        import os

        base = (
            self.api_base
            or os.environ.get("FAST_FOTO_API_BASE")
            or "https://api.openai.com/v1"
        )
        key = (
            self.api_key
            or os.environ.get("FAST_FOTO_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        if not key:
            raise SynthesisError(
                "No API key configured. Set FAST_FOTO_API_KEY or "
                "OPENAI_API_KEY, or pass api_key= to the backend."
            )
        return base.rstrip("/"), key

    def _call_remote(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, object],
    ) -> dict[str, object]:
        """POST to the chat completions endpoint.

        Thin wrapper for monkeypatching in tests.
        """
        import httpx

        base, key = self._resolve_config()
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": self.model,
                "messages": messages,
                "response_format": response_format,
                "temperature": 0.2,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    def generate(
        self,
        observations: list[EvidenceObservation],
        hits: list[SearchHit],
        previous_error: str | None = None,
    ) -> SynthesisArtifact:
        messages = [
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
        ]
        response_format: dict[str, object] = {
            "type": "json_schema",
            "json_schema": {
                "name": "ItemDatasheet",
                "schema": _ITEM_DATASHEET_SCHEMA,
            },
        }
        payload = self._call_remote(messages, response_format)
        choices = payload.get("choices", [])  # type: ignore[union-attr]
        if not choices:
            raise SynthesisError("remote API returned no choices")
        raw_payload = _strip_code_fences(choices[0]["message"]["content"])  # type: ignore[index]
        return SynthesisArtifact(
            backend_name="remote",
            model_name=self.model,
            schema_name="ItemDatasheet",
            raw_payload=raw_payload,
            accepted=False,
            attempt_count=1,
            last_error=None,
        )


def synthesize_item_with_artifact(
    observations: list[EvidenceObservation],
    hits: list[SearchHit],
    backend: SynthesisBackend,
) -> tuple[ItemDatasheet, SynthesisArtifact]:
    """Generate and validate a structured datasheet plus provenance.

    On each attempt the raw payload goes through JSON repair (trailing
    commas, code fences, truncation) and citation backfill before
    schema validation.  Two attempts are made before giving up.
    """
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

        # Repair common LLM output issues before validation
        repaired = _repair_json(artifact.raw_payload)
        if repaired != artifact.raw_payload:
            artifact = replace(artifact, raw_payload=repaired)

        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as exc:
            last_artifact = replace(
                artifact,
                accepted=False,
                last_error=f"invalid JSON: {exc}",
                attempt_count=attempt,
            )
            continue

        # Backfill citations and clamp confidence
        data = _backfill_citations(data, observations, hits)

        try:
            datasheet = ItemDatasheet.from_dict(data)
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
