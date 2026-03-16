"""Tests for the single-image diagnostic runner."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fast_foto_forensics.diagnostic_runner import (
    DiagnosticFailure,
    DiagnosticRequest,
    DiagnosticResult,
    run_diagnostic_request,
    summarize_vision_result,
)
from fast_foto_forensics.export_fixture import export_diagnostic_fixture
from fast_foto_forensics.models import QueryCandidate, QueryPlan, SearchHit, VisionResult
from fast_foto_forensics.search import StaticSearchProvider
from fast_foto_forensics.synthesis import ReplaySynthesisBackend
from fast_foto_forensics.vision import StaticVisionBackend


def test_diagnostic_request_from_upload_bytes_preserves_filename_and_content() -> None:
    """Upload-backed requests should keep the original filename and bytes."""
    request = DiagnosticRequest.from_upload_bytes(
        filename="router.jpg",
        image_bytes=b"fake-image-bytes",
    )

    assert request.source_kind == "upload"
    assert request.source_name == "router.jpg"
    assert request.image_bytes == b"fake-image-bytes"
    assert request.image_url is None


def test_diagnostic_request_from_image_url_uses_terminal_segment_as_name() -> None:
    """URL-backed requests should infer a reasonable display name."""
    request = DiagnosticRequest.from_image_url(
        "https://example.com/evidence/router-photo.png?download=1"
    )

    assert request.source_kind == "url"
    assert request.source_name == "router-photo.png"
    assert request.image_url == "https://example.com/evidence/router-photo.png?download=1"
    assert request.image_bytes is None


def test_summarize_vision_result_includes_vendor_class_and_identifiers() -> None:
    """Vision summaries should be readable without losing core structured signal."""
    result = VisionResult(
        evidence_id="img-001",
        source_path="evidence/router.jpg",
        source_sha256="deadbeef",
        backend_name="ollama",
        model_name="qwen2.5vl:7b",
        caption="A blue wireless router with two antennas.",
        ocr_text="WRT54G LINKSYS",
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
        detected_labels=["router", "wireless"],
    )

    summary = summarize_vision_result(result)

    assert "Linksys" in summary
    assert "wireless router" in summary
    assert "WRT54G" in summary


def test_diagnostic_result_to_dict_is_json_friendly() -> None:
    """The diagnostic response object should serialize cleanly for the web UI."""
    result = DiagnosticResult(
        source_kind="upload",
        source_name="router.jpg",
        source_preview_url="/preview/router.jpg",
        log_messages=["running vision", "building query plan"],
        vision_json={"caption": "A router"},
        vision_summary="Router by Linksys",
        query_plan=QueryPlan(
            selected_queries=[
                QueryCandidate(text="Linksys WRT54G", provenance=["vision"], score=5.0)
            ]
        ),
        search_hits=[
            SearchHit(
                hit_id="hit-1",
                provider="ddgs",
                query="Linksys WRT54G",
                title="Linksys WRT54G",
                snippet="Wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        datasheet_json={"probable_identity": "Linksys WRT54G"},
        rendered_datasheet="Linksys WRT54G\n\nWireless router",
        failures=[DiagnosticFailure(stage="search", error="timeout")],
    )

    payload = result.to_dict()

    assert payload["source_kind"] == "upload"
    assert payload["source_name"] == "router.jpg"
    assert payload["vision_json"]["caption"] == "A router"
    assert payload["query_plan"]["selected_queries"][0]["text"] == "Linksys WRT54G"
    assert payload["search_hits"][0]["provider"] == "ddgs"
    assert payload["failures"][0]["stage"] == "search"


def test_run_diagnostic_request_executes_real_stage_order(tmp_path) -> None:
    """A successful diagnostic run should expose stage artifacts in order."""
    request = DiagnosticRequest.from_upload_bytes("router.jpg", b"fake-image-bytes")
    vision_backend = StaticVisionBackend(
        fixtures={
            "diagnostic-000": VisionResult(
                evidence_id="diagnostic-000",
                source_path=str(tmp_path / "router.jpg"),
                source_sha256="deadbeef",
                backend_name="static",
                model_name="fixture",
                caption="A blue wireless router.",
                ocr_text="WRT54G LINKSYS",
                candidate_identifiers=["WRT54G"],
                vendor="Linksys",
                object_class="wireless router",
                detected_labels=["router", "wireless"],
            )
        }
    )
    search_provider = StaticSearchProvider(
        fixtures={
            "LINKSYS WRT54G": [
                {
                    "title": "Linksys WRT54G overview",
                    "snippet": "A wireless router series.",
                    "url": "https://example.com/wrt54g",
                }
            ]
        }
    )
    synthesis_backend = ReplaySynthesisBackend(
        responses=[
            """
            {
              "probable_identity": "Linksys WRT54G",
              "object_class": "wireless router",
              "likely_function": "Wireless router",
              "manufacturer": "Linksys",
              "model_identifiers": ["WRT54G"],
              "year_range": "2002-2005",
              "country_or_region": "United States",
              "security_findings": [],
              "confidence": 0.88,
              "evidence_refs": ["diagnostic-000"],
              "search_hit_refs": ["static-000"],
              "open_questions": []
            }
            """
        ]
    )

    result = run_diagnostic_request(
        request,
        work_root=tmp_path,
        vision_backend=vision_backend,
        search_provider=search_provider,
        synthesis_backend=synthesis_backend,
    )

    assert result.source_name == "router.jpg"
    assert result.vision_json is not None
    assert result.vision_json["vendor"] == "Linksys"
    assert result.query_plan is not None
    assert result.query_plan.selected_queries[0].text == "LINKSYS WRT54G"
    assert result.search_hits[0].provider == "static"
    assert result.datasheet_json is not None
    assert result.datasheet_json["probable_identity"] == "Linksys WRT54G"
    assert result.failures == []
    assert result.log_messages == [
        "materializing image",
        "running vision",
        "building query plan",
        "running search",
        "synthesizing datasheet",
        "rendering result",
    ]


def test_run_diagnostic_request_preserves_earlier_artifacts_when_search_fails(tmp_path) -> None:
    """Search failures should still leave the earlier stages inspectable."""

    @dataclass(slots=True)
    class FailingSearchProvider:
        def search(self, query: str) -> list[SearchHit]:
            raise RuntimeError("search timeout")

    request = DiagnosticRequest.from_upload_bytes("router.jpg", b"fake-image-bytes")
    vision_backend = StaticVisionBackend(
        fixtures={
            "diagnostic-000": VisionResult(
                evidence_id="diagnostic-000",
                source_path=str(tmp_path / "router.jpg"),
                source_sha256="deadbeef",
                backend_name="static",
                model_name="fixture",
                caption="A blue wireless router.",
                ocr_text="WRT54G LINKSYS",
                candidate_identifiers=["WRT54G"],
                vendor="Linksys",
                object_class="wireless router",
                detected_labels=["router", "wireless"],
            )
        }
    )
    synthesis_backend = ReplaySynthesisBackend(
        responses=[
            """
            {
              "probable_identity": "Linksys WRT54G",
              "object_class": "wireless router",
              "likely_function": "Wireless router",
              "manufacturer": "Linksys",
              "model_identifiers": ["WRT54G"],
              "year_range": "2002-2005",
              "country_or_region": "United States",
              "security_findings": [],
              "confidence": 0.88,
              "evidence_refs": ["diagnostic-000"],
              "search_hit_refs": [],
              "open_questions": []
            }
            """
        ]
    )

    result = run_diagnostic_request(
        request,
        work_root=tmp_path,
        vision_backend=vision_backend,
        search_provider=FailingSearchProvider(),
        synthesis_backend=synthesis_backend,
    )

    assert result.vision_json is not None
    assert result.query_plan is not None
    assert result.search_hits == []
    assert result.datasheet_json is not None
    assert result.failures == [DiagnosticFailure(stage="search", error="search timeout")]


def test_run_diagnostic_request_preserves_search_hits_when_synthesis_fails(tmp_path) -> None:
    """Synthesis failures should still show search evidence and failure details."""

    @dataclass(slots=True)
    class FailingSynthesisBackend:
        def generate(
            self,
            observations,
            hits,
            previous_error: str | None = None,
        ) -> str:
            raise RuntimeError("model crashed")

    request = DiagnosticRequest.from_upload_bytes("router.jpg", b"fake-image-bytes")
    vision_backend = StaticVisionBackend(
        fixtures={
            "diagnostic-000": VisionResult(
                evidence_id="diagnostic-000",
                source_path=str(tmp_path / "router.jpg"),
                source_sha256="deadbeef",
                backend_name="static",
                model_name="fixture",
                caption="A blue wireless router.",
                ocr_text="WRT54G LINKSYS",
                candidate_identifiers=["WRT54G"],
                vendor="Linksys",
                object_class="wireless router",
                detected_labels=["router", "wireless"],
            )
        }
    )
    search_provider = StaticSearchProvider(
        fixtures={
            "LINKSYS WRT54G": [
                {
                    "title": "Linksys WRT54G overview",
                    "snippet": "A wireless router series.",
                    "url": "https://example.com/wrt54g",
                }
            ]
        }
    )

    result = run_diagnostic_request(
        request,
        work_root=tmp_path,
        vision_backend=vision_backend,
        search_provider=search_provider,
        synthesis_backend=FailingSynthesisBackend(),
    )

    assert result.search_hits[0].provider == "static"
    assert result.datasheet_json is None
    assert result.rendered_datasheet == ""
    assert result.failures == [DiagnosticFailure(stage="synthesis", error="model crashed")]


def test_export_diagnostic_fixture_writes_image_and_metadata(tmp_path) -> None:
    """Export should create a retryable image fixture plus a metadata sidecar."""
    request = DiagnosticRequest.from_image_url("https://example.com/evidence/router.jpg")
    result = DiagnosticResult(
        source_kind="url",
        source_name="router.jpg",
        source_preview_url="file:///tmp/router.jpg",
        log_messages=["running vision", "running search"],
        vision_json={
            "backend_name": "ollama",
            "model_name": "qwen2.5vl:7b",
            "caption": "A blue wireless router.",
        },
        vision_summary="Linksys | wireless router | WRT54G",
        datasheet_json={"probable_identity": "Linksys WRT54G"},
        rendered_datasheet="Linksys WRT54G",
        failures=[DiagnosticFailure(stage="synthesis", error="model crashed")],
        synthesis_artifact={"backend_name": "ollama", "model_name": "qwen3:8b"},
        source_image_bytes=b"fake-router-image",
    )

    exported = export_diagnostic_fixture(
        request,
        result,
        export_root=tmp_path / "exports",
        analyst_note="bad synthesis on router sample",
    )

    assert exported.image_path.exists()
    assert exported.image_path.read_bytes() == b"fake-router-image"
    assert exported.metadata_path.exists()

    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "url"
    assert metadata["source_url"] == "https://example.com/evidence/router.jpg"
    assert metadata["analyst_note"] == "bad synthesis on router sample"
    assert metadata["vision_backend_name"] == "ollama"
    assert metadata["vision_model_name"] == "qwen2.5vl:7b"
    assert metadata["synthesis_backend_name"] == "ollama"
    assert metadata["synthesis_model_name"] == "qwen3:8b"
    assert metadata["failures"][0]["stage"] == "synthesis"
