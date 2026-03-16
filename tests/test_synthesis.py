"""Tests for schema-first synthesis."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import EvidenceObservation, SearchHit, SynthesisArtifact
from fast_foto_forensics.synthesis import (
    OllamaDatasheetSynthesisBackend,
    RemoteDatasheetSynthesisBackend,
    ReplaySynthesisBackend,
    synthesize_item,
)


def _make_fake_chat(responses: list[str]):
    """Return a fake Ollama call that yields *responses* in order."""
    call_count = [0]
    captured_kwargs: list[dict[str, object]] = []

    def fake_chat(**kwargs):
        idx = call_count[0]
        call_count[0] += 1
        captured_kwargs.append(kwargs)

        class FakeMessage:
            content = responses[idx] if idx < len(responses) else ""

        class FakeResponse:
            message = FakeMessage()

        return FakeResponse()

    fake_chat.call_count = call_count
    fake_chat.captured_kwargs = captured_kwargs
    return fake_chat


def test_json_synthesis_retries_when_first_payload_is_invalid() -> None:
    """Invalid model output should trigger one repair attempt."""
    backend = ReplaySynthesisBackend(
        responses=[
            "not-json-at-all",
            """
            {
              "probable_identity": "Linksys WRT54G",
              "object_class": "router",
              "likely_function": "Wireless router",
              "manufacturer": "Linksys",
              "model_identifiers": ["WRT54G"],
              "year_range": "2002-2005",
              "country_or_region": "United States",
              "security_findings": ["Legacy firmware may have known weaknesses"],
              "confidence": 0.88,
              "evidence_refs": ["img-1"],
              "search_hit_refs": ["hit-1"],
              "open_questions": ["Confirm hardware revision"]
            }
            """,
        ]
    )

    result = synthesize_item(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        backend=backend,
    )

    assert result.probable_identity == "Linksys WRT54G"
    assert backend.calls == 2


def test_json_synthesis_retries_when_required_fields_are_missing() -> None:
    """Boundary validation should reject incomplete schema-mode responses."""
    backend = ReplaySynthesisBackend(
        responses=[
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "model_identifiers": ["WRT54G"],
                }
            ),
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "manufacturer": "Linksys",
                    "model_identifiers": ["WRT54G"],
                    "year_range": "2002-2005",
                    "country_or_region": "United States",
                    "security_findings": [],
                    "confidence": 0.88,
                    "evidence_refs": ["img-1"],
                    "search_hit_refs": ["hit-1"],
                    "open_questions": [],
                }
            ),
        ]
    )

    result = synthesize_item(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        backend=backend,
    )

    assert result.manufacturer == "Linksys"
    assert backend.calls == 2


def test_ollama_backend_uses_schema_mode_and_preserves_raw_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama datasheet synthesis should request schema mode and return provenance."""
    backend = OllamaDatasheetSynthesisBackend(model="qwen3:8b")
    fake_chat = _make_fake_chat(
        [
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "manufacturer": "Linksys",
                    "model_identifiers": ["WRT54G"],
                    "year_range": "2002-2005",
                    "country_or_region": "United States",
                    "security_findings": [],
                    "confidence": 0.88,
                    "evidence_refs": ["img-1"],
                    "search_hit_refs": ["hit-1"],
                    "open_questions": [],
                }
            )
        ]
    )
    monkeypatch.setattr(backend, "_call_ollama", fake_chat)

    artifact = backend.generate(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
    )

    assert isinstance(artifact, SynthesisArtifact)
    assert artifact.backend_name == "ollama"
    assert artifact.model_name == "qwen3:8b"
    assert artifact.schema_name == "ItemDatasheet"
    assert artifact.raw_payload

    request = fake_chat.captured_kwargs[0]
    assert request["model"] == "qwen3:8b"
    assert request["stream"] is False
    assert isinstance(request["format"], dict)
    assert request["format"]["type"] == "object"
    assert "manufacturer" in request["format"]["required"]


def test_ollama_backend_gives_actionable_error_when_package_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional dependency should tell the operator how to install it."""
    backend = OllamaDatasheetSynthesisBackend(model="qwen3:8b")

    def fake_call_ollama(**kwargs):
        raise RuntimeError(
            "ollama package not installed. Install with: "
            "pip install fast-foto-forensics[vision_ollama]"
        )

    monkeypatch.setattr(backend, "_call_ollama", fake_call_ollama)

    with pytest.raises(RuntimeError, match="vision_ollama"):
        backend.generate(observations=[], hits=[])


def test_remote_backend_stub_fails_fast_with_actionable_error() -> None:
    """The remote synthesis backend should exist but fail clearly until configured."""
    backend = RemoteDatasheetSynthesisBackend(model="gpt-5.4-mini")

    with pytest.raises(RuntimeError, match="not implemented"):
        backend.generate(observations=[], hits=[])
