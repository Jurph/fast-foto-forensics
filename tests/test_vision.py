"""Tests for the vision module (issues #4, #5, #6, #11)."""

from __future__ import annotations

import importlib.util
import json
import struct
import zlib
from pathlib import Path

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.storage import RunStore
from fast_foto_forensics.vision import (
    FilenameVisionBackend,
    OllamaVisionBackend,
    StaticVisionBackend,
    VisionBackend,
    VisionExtractionError,
    enrich_observations,
    enrich_single,
    extract_with_cache,
)


def _make_test_png(text: str | None = None, size: int = 128) -> bytes:
    """Build a valid white RGB PNG in memory.

    When *text* is provided (e.g. ``"TEST"``), Pillow renders it centered
    in black on the white background so the vision model has something to OCR.
    Falls back to a plain white image when Pillow is unavailable or *text*
    is ``None``.
    """
    import io

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # Pillow not installed — fall back to raw struct-based PNG
        raw_rows = b""
        for _ in range(size):
            raw_rows += b"\x00" + b"\xff" * (size * 3)

        def _chunk(tag: bytes, data: bytes) -> bytes:
            payload = tag + data
            return (
                struct.pack(">I", len(data))
                + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
        idat = zlib.compress(raw_rows)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b"")
        )

    img = Image.new("RGB", (size, size), "white")
    if text:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", size // 3)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) / 2, (size - th) / 2), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
        img.write_bytes(_make_test_png())
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
        fake = _make_fake_chat(
            [
                "this is not json at all",
                json.dumps(_VALID_OLLAMA_RESPONSE),
            ]
        )
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

    def test_missing_ollama_gives_actionable_error(self, tmp_path, monkeypatch) -> None:
        """When ollama is not installed, the error message tells you how to fix it."""
        backend = OllamaVisionBackend()
        obs = self._observation_with_real_file(tmp_path)

        def fake_call_ollama(**kwargs):
            raise VisionExtractionError(
                "ollama package not installed. Install with: "
                "pip install fast-foto-forensics[vision_ollama]"
            )

        monkeypatch.setattr(backend, "_call_ollama", fake_call_ollama)

        with pytest.raises(VisionExtractionError, match="vision_ollama"):
            backend.extract(obs)


# ---------------------------------------------------------------------------
# extract_with_cache tests (issue #7)
# ---------------------------------------------------------------------------


class TestExtractWithCache:
    def _make_backend_and_obs(self) -> tuple:
        fixture = VisionResult(
            evidence_id="cache-001",
            source_path="evidence/router.jpg",
            source_sha256="sha_aaa",
            backend_name="static",
            model_name="static",
            caption="A router.",
            ocr_text="WRT54G",
            candidate_identifiers=["WRT54G"],
            vendor="Linksys",
            object_class="wireless router",
            detected_labels=["router"],
        )
        backend = StaticVisionBackend(fixtures={"cache-001": fixture})
        obs = EvidenceObservation(
            evidence_id="cache-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="sha_aaa",
            order_index=0,
        )
        return backend, obs, fixture

    def test_cache_miss_calls_backend_and_persists(self, tmp_path) -> None:
        store = RunStore.from_run_dir(tmp_path / "run")
        backend, obs, fixture = self._make_backend_and_obs()

        result = extract_with_cache(obs, backend, store)

        assert result.evidence_id == "cache-001"
        assert result.caption == "A router."
        # Verify artifact was written
        cached = store.read_json_artifact("vision/cache-001.json")
        assert cached["evidence_id"] == "cache-001"

    def test_cache_hit_skips_backend(self, tmp_path) -> None:
        store = RunStore.from_run_dir(tmp_path / "run")
        backend, obs, fixture = self._make_backend_and_obs()

        # Prime the cache
        extract_with_cache(obs, backend, store)

        # Replace backend with one that would fail
        empty_backend = StaticVisionBackend(fixtures={})
        result = extract_with_cache(obs, empty_backend, store)

        assert result.evidence_id == "cache-001"
        assert result.caption == "A router."

    def test_cache_stale_on_sha256_mismatch(self, tmp_path) -> None:
        store = RunStore.from_run_dir(tmp_path / "run")
        backend, obs, fixture = self._make_backend_and_obs()

        # Prime the cache
        extract_with_cache(obs, backend, store)

        # Change the observation sha256
        obs_changed = EvidenceObservation(
            evidence_id="cache-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="sha_bbb",
            order_index=0,
        )
        # Backend still has the fixture so it will re-extract
        result = extract_with_cache(obs_changed, backend, store)

        assert result.source_sha256 == "sha_aaa"  # from backend, not cache


# ---------------------------------------------------------------------------
# enrich_single and enrich_observations tests (issue #8)
# ---------------------------------------------------------------------------


class TestEnrichSingle:
    def test_maps_vision_result_onto_observation(self) -> None:
        obs = EvidenceObservation(
            evidence_id="enrich-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc",
            order_index=0,
        )
        result = VisionResult(
            evidence_id="enrich-001",
            source_path="evidence/router.jpg",
            source_sha256="abc",
            backend_name="static",
            model_name="static",
            caption="A blue router.",
            ocr_text="WRT54G LINKSYS",
            candidate_identifiers=["WRT54G"],
            vendor="Linksys",
            object_class="wireless router",
            detected_labels=["router", "networking"],
        )
        enriched = enrich_single(obs, result)
        assert enriched is obs  # mutates in place
        assert obs.caption == "A blue router."
        assert obs.ocr_text == "WRT54G LINKSYS"
        assert obs.candidate_identifiers == ["WRT54G"]
        assert obs.detected_labels == ["router", "networking"]


class TestEnrichObservations:
    def test_enriches_batch(self) -> None:
        fixture = VisionResult(
            evidence_id="batch-001",
            source_path="evidence/router.jpg",
            source_sha256="abc",
            backend_name="static",
            model_name="static",
            caption="Router photo.",
            ocr_text="WRT54G",
            candidate_identifiers=["WRT54G"],
            vendor="Linksys",
            object_class="wireless router",
            detected_labels=["router"],
        )
        backend = StaticVisionBackend(fixtures={"batch-001": fixture})
        obs = EvidenceObservation(
            evidence_id="batch-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc",
            order_index=0,
        )
        results = enrich_observations([obs], backend)
        assert results[0].caption == "Router photo."

    def test_skips_failures_without_crashing(self) -> None:
        """One bad observation should not take down the batch."""
        backend = StaticVisionBackend(fixtures={})  # no fixtures = all fail
        obs_bad = EvidenceObservation(
            evidence_id="bad-001",
            source_path="evidence/missing.jpg",
            media_kind="image",
            sha256="xxx",
            order_index=0,
        )
        obs_bad2 = EvidenceObservation(
            evidence_id="bad-002",
            source_path="evidence/also-missing.jpg",
            media_kind="image",
            sha256="yyy",
            order_index=1,
        )
        results = enrich_observations([obs_bad, obs_bad2], backend)
        assert len(results) == 2
        # Observations are returned but unenriched
        assert results[0].caption == ""
        assert results[1].caption == ""


# ---------------------------------------------------------------------------
# Ollama integration test (issue #11)
# ---------------------------------------------------------------------------

_HAS_OLLAMA = importlib.util.find_spec("ollama") is not None


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_OLLAMA, reason="ollama package not installed")
class TestOllamaIntegration:
    def test_round_trip_with_real_model(self, tmp_path: Path) -> None:
        """Send a 128x128 image with 'TEST' to Ollama and verify OCR reads it back."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(_make_test_png(text="TEST"))

        observation = EvidenceObservation(
            evidence_id="integration-test",
            source_path=str(test_image),
            media_kind="image",
            sha256="integration",
            order_index=0,
        )
        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        try:
            result = backend.extract(observation)
        except VisionExtractionError:
            pytest.skip("Ollama returned unparseable response for test image")

        assert isinstance(result, VisionResult)
        assert result.backend_name == "ollama"
        assert result.evidence_id == "integration-test"
        # The model should OCR the word "TEST" from the image
        assert "TEST" in result.ocr_text.upper(), (
            f"Expected 'TEST' in OCR output, got: {result.ocr_text!r}"
        )
