"""Tests for the vision module (issues #4, #5, #6)."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.vision import (
    FilenameVisionBackend,
    OllamaVisionBackend,
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


# ---------------------------------------------------------------------------
# OllamaVisionBackend tests (issue #6)
# ---------------------------------------------------------------------------

_VALID_OLLAMA_RESPONSE = {
    "caption": "A blue wireless router with two antennas.",
    "ocr_text": "WRT54G LINKSYS",
    "candidate_identifiers": ["WRT54G"],
    "vendor": "Linksys",
    "object_class": "wireless router",
    "detected_labels": ["router", "networking"],
}


def _make_fake_chat(responses: list[str]):
    """Return a fake _call_ollama that yields *responses* in order."""
    call_count = [0]

    def fake_chat(**kwargs):
        idx = call_count[0]
        call_count[0] += 1

        class FakeMessage:
            content = responses[idx] if idx < len(responses) else ""

        class FakeResponse:
            message = FakeMessage()

        return FakeResponse()

    fake_chat.call_count = call_count  # expose for assertions
    return fake_chat


class TestOllamaVisionBackend:
    def _observation_with_real_file(self, tmp_path) -> EvidenceObservation:
        """Create a tiny PNG file and return an observation pointing at it."""
        img = tmp_path / "test.png"
        # Minimal valid 1x1 white PNG
        img.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return EvidenceObservation(
            evidence_id="img-010",
            source_path=str(img),
            media_kind="image",
            sha256="aabbcc",
            order_index=0,
        )

    def test_parses_valid_json_response(self, tmp_path, monkeypatch) -> None:
        backend = OllamaVisionBackend()
        obs = self._observation_with_real_file(tmp_path)
        fake = _make_fake_chat([json.dumps(_VALID_OLLAMA_RESPONSE)])
        monkeypatch.setattr(backend, "_call_ollama", fake)

        result = backend.extract(obs)

        assert result.evidence_id == "img-010"
        assert result.caption == "A blue wireless router with two antennas."
        assert result.ocr_text == "WRT54G LINKSYS"
        assert result.candidate_identifiers == ["WRT54G"]
        assert result.vendor == "Linksys"
        assert result.object_class == "wireless router"
        assert result.detected_labels == ["router", "networking"]
        assert result.backend_name == "ollama"
        assert result.model_name == "qwen2.5vl:7b"
        assert fake.call_count[0] == 1

    def test_retries_once_on_bad_json(self, tmp_path, monkeypatch) -> None:
        backend = OllamaVisionBackend()
        obs = self._observation_with_real_file(tmp_path)
        fake = _make_fake_chat([
            "this is not json at all",
            json.dumps(_VALID_OLLAMA_RESPONSE),
        ])
        monkeypatch.setattr(backend, "_call_ollama", fake)

        result = backend.extract(obs)

        assert fake.call_count[0] == 2
        assert result.caption == "A blue wireless router with two antennas."

    def test_raises_after_two_failures(self, tmp_path, monkeypatch) -> None:
        backend = OllamaVisionBackend()
        obs = self._observation_with_real_file(tmp_path)
        fake = _make_fake_chat(["not json", "still not json"])
        monkeypatch.setattr(backend, "_call_ollama", fake)

        with pytest.raises(VisionExtractionError, match="Failed to parse"):
            backend.extract(obs)

        assert fake.call_count[0] == 2

    def test_raises_for_missing_image(self, monkeypatch) -> None:
        backend = OllamaVisionBackend()
        obs = EvidenceObservation(
            evidence_id="img-missing",
            source_path="/nonexistent/image.png",
            media_kind="image",
            sha256="000",
            order_index=0,
        )

        with pytest.raises(VisionExtractionError, match="not found"):
            backend.extract(obs)

    def test_satisfies_vision_backend_protocol(self) -> None:
        assert isinstance(OllamaVisionBackend(), VisionBackend)

    def test_empty_vendor_becomes_none(self, tmp_path, monkeypatch) -> None:
        backend = OllamaVisionBackend()
        obs = self._observation_with_real_file(tmp_path)
        response = dict(_VALID_OLLAMA_RESPONSE, vendor="", object_class="")
        fake = _make_fake_chat([json.dumps(response)])
        monkeypatch.setattr(backend, "_call_ollama", fake)

        result = backend.extract(obs)

        assert result.vendor is None
        assert result.object_class is None
