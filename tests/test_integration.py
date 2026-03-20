"""End-to-end integration tests against real backends.

These tests are marked ``@pytest.mark.slow`` and require:
  - A running Ollama instance with the qwen2.5vl:7b model loaded
  - Network access for DDGS web search
  - The checked-in JPEG fixtures in tests/fixtures/small-jpegs/

Run with:  pytest -m slow tests/test_integration.py -v

They exist to catch *pipeline-level* regressions that unit tests can't:
  - Does Ollama still return parseable JSON for a real photo?
  - Does the DDGS provider still return English-language results?
  - Does the full pipeline stitch everything together into a useful report?
  - Are the structured artifacts (VisionResult, SearchHit, ItemDatasheet)
    populated with meaningful content, not empty placeholders?

Quality assertions are intentionally loose — we check for *invariant
properties* of good results (non-empty caption, OCR contains known text,
identifiers found, search returned hits) rather than exact strings, because
model output varies slightly between runs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.pipeline import run_pipeline
from fast_foto_forensics.search import DDGSSearchProvider
from fast_foto_forensics.synthesis import HeuristicSynthesisBackend
from fast_foto_forensics.vision import FilenameVisionBackend, OllamaVisionBackend

_HAS_OLLAMA = importlib.util.find_spec("ollama") is not None
_HAS_DDGS = importlib.util.find_spec("ddgs") is not None

# Path to checked-in test JPEGs.
# These are real photos of networking hardware, small enough to process
# in a few seconds on a GPU and stable enough for repeatable local runs.
_TEST_JPEGS_DIR = Path(__file__).resolve().parent / "fixtures" / "small-jpegs"
_TPLINK_JPEG = _TEST_JPEGS_DIR / "tp-link-OC200-and-Omada-ER605.jpg"
_VERIZON_JPEG = _TEST_JPEGS_DIR / "Verizon FIOS G1100.jpg"


# ---------------------------------------------------------------------------
# Vision extraction: does Ollama return usable structured JSON?
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_OLLAMA, reason="ollama package not installed")
@pytest.mark.skipif(not _TPLINK_JPEG.exists(), reason="test JPEG not found")
class TestOllamaRealPhoto:
    """Send a real hardware photo to Ollama and validate the VisionResult."""

    def test_tplink_returns_valid_vision_result(self) -> None:
        """The TP-Link image should produce a VisionResult with real content."""
        obs = EvidenceObservation(
            evidence_id="integ-tplink",
            source_path=str(_TPLINK_JPEG),
            media_kind="image",
            sha256="test",
            order_index=0,
        )
        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        result = backend.extract(obs)

        # Structural: it's a real VisionResult from the right backend
        assert isinstance(result, VisionResult)
        assert result.backend_name == "ollama"
        assert result.model_name == "qwen2.5vl:7b"
        assert result.evidence_id == "integ-tplink"

        # Caption: non-empty, describes something
        assert len(result.caption) > 10, f"Caption too short: {result.caption!r}"

        # OCR: the image has visible text — we should find some of it.
        # These strings are physically printed on the hardware and should
        # be reliably detected across model runs.
        ocr_lower = result.ocr_text.lower()
        assert "tp-link" in ocr_lower or "omada" in ocr_lower, (
            f"OCR should contain 'tp-link' or 'omada', got: {result.ocr_text[:200]!r}"
        )

        # Identifiers: the image shows model numbers on the devices
        assert len(result.candidate_identifiers) >= 1, (
            "Should find at least one model number / identifier"
        )

        # Labels: there are stickers and port markings on the hardware
        assert len(result.detected_labels) >= 3, (
            f"Expected 3+ labels, got {len(result.detected_labels)}: {result.detected_labels}"
        )

        # Round-trip: the result should survive serialization
        rebuilt = VisionResult.from_dict(result.to_dict())
        assert rebuilt.caption == result.caption
        assert rebuilt.candidate_identifiers == result.candidate_identifiers

    def test_tplink_result_serializes_to_valid_json(self) -> None:
        """The VisionResult.to_dict() output should be clean, parseable JSON."""
        obs = EvidenceObservation(
            evidence_id="integ-tplink-json",
            source_path=str(_TPLINK_JPEG),
            media_kind="image",
            sha256="test",
            order_index=0,
        )
        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        result = backend.extract(obs)

        # Serialize and re-parse — catches any non-serializable fields
        raw_json = json.dumps(result.to_dict(), indent=2)
        parsed = json.loads(raw_json)

        assert isinstance(parsed, dict)
        assert parsed["backend_name"] == "ollama"
        assert isinstance(parsed["candidate_identifiers"], list)
        assert isinstance(parsed["detected_labels"], list)
        assert isinstance(parsed["ocr_text"], str)


# ---------------------------------------------------------------------------
# DDGS web search: does it still return English-language results?
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_DDGS, reason="ddgs package not installed")
class TestDDGSLiveSearch:
    """Verify that DDGS returns usable web results for hardware queries."""

    def test_tplink_query_returns_relevant_hits(self) -> None:
        """A query for 'TP-Link OC200' should return real product pages."""
        provider = DDGSSearchProvider(max_results=5)
        hits = provider.search("TP-Link OC200 hardware controller specifications")

        assert len(hits) >= 2, f"Expected 2+ hits, got {len(hits)}"

        # All hits should have the right provider tag and non-empty fields
        for hit in hits:
            assert hit.provider == "ddgs"
            assert hit.url.startswith("http")
            assert len(hit.title) > 0
            assert len(hit.snippet) > 0

        # At least one hit should mention TP-Link or OC200 in its content
        all_text = " ".join(h.title + " " + h.snippet for h in hits).lower()
        assert "tp-link" in all_text or "oc200" in all_text, (
            "Search results should mention the queried product"
        )

    def test_verizon_query_returns_relevant_hits(self) -> None:
        """A query for 'Verizon G1100' should return router info."""
        provider = DDGSSearchProvider(max_results=5)
        hits = provider.search("Verizon Fios Quantum Gateway G1100 router")

        assert len(hits) >= 2
        all_text = " ".join(h.title + " " + h.snippet for h in hits).lower()
        assert "verizon" in all_text or "g1100" in all_text or "fios" in all_text


# ---------------------------------------------------------------------------
# Full pipeline: vision + search + synthesis + report
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_OLLAMA, reason="ollama package not installed")
@pytest.mark.skipif(not _TPLINK_JPEG.exists(), reason="test JPEG not found")
class TestFullPipeline:
    """Run the complete pipeline on a single real image and check outputs."""

    def test_pipeline_produces_meaningful_report(self, tmp_path: Path) -> None:
        """The pipeline should produce a report with real content, not stubs."""
        # Use a directory containing just the TP-Link image
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        # Symlink to avoid copying the image
        target = input_dir / _TPLINK_JPEG.name
        target.symlink_to(_TPLINK_JPEG.resolve())

        result = run_pipeline(
            input_path=input_dir,
            output_root=tmp_path / "output",
            run_label="integ-test",
            vision_backend=OllamaVisionBackend(model="qwen2.5vl:7b"),
            search_provider=DDGSSearchProvider(max_results=3),
            synthesis_backend=HeuristicSynthesisBackend(),
        )

        # Structural: the pipeline created all expected outputs
        assert result.run_dir.is_dir()
        assert result.report_path.is_file()
        assert len(result.sidecar_paths) >= 1

        # Report content: should contain real hardware information
        report_text = result.report_path.read_text(encoding="utf-8")
        assert len(report_text) > 100, "Report is suspiciously short"
        assert "## " in report_text, "Report should have markdown headings"

        # Sidecar JSON: should have tags and a caption
        sidecar = json.loads(result.sidecar_paths[0].read_text(encoding="utf-8"))
        assert isinstance(sidecar["tags"], list)
        assert len(sidecar["tags"]) >= 2, f"Sidecar should have 2+ tags, got: {sidecar['tags']}"
        assert len(sidecar["caption"]) > 10

        # Persisted artifacts: vision result should be cached
        vision_artifact = result.run_dir / "artifacts" / "vision" / "obs-0000.json"
        assert vision_artifact.is_file(), "Vision result should be cached as artifact"
        vision_data = json.loads(vision_artifact.read_text(encoding="utf-8"))
        assert vision_data["backend_name"] == "ollama"
        assert len(vision_data["ocr_text"]) > 0

    def test_pipeline_with_filename_backend_and_ddgs_search(self, tmp_path: Path) -> None:
        """Even the lightweight filename backend + live search should produce output."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        target = input_dir / _TPLINK_JPEG.name
        target.symlink_to(_TPLINK_JPEG.resolve())

        result = run_pipeline(
            input_path=input_dir,
            output_root=tmp_path / "output",
            run_label="integ-filename",
            vision_backend=FilenameVisionBackend(),
            search_provider=DDGSSearchProvider(max_results=3),
            synthesis_backend=HeuristicSynthesisBackend(),
        )

        assert result.report_path.is_file()
        report_text = result.report_path.read_text(encoding="utf-8")
        assert len(report_text) > 50

        # The filename backend extracts tokens from the filename — we should
        # see tp-link-related terms in the report
        report_lower = report_text.lower()
        assert "tp" in report_lower or "link" in report_lower or "oc200" in report_lower
