"""Tests for the single-image diagnostic runner."""

from __future__ import annotations

from fast_foto_forensics.models import QueryCandidate, QueryPlan, SearchHit, VisionResult
from fast_foto_forensics.diagnostic_runner import (
    DiagnosticFailure,
    DiagnosticRequest,
    DiagnosticResult,
    summarize_vision_result,
)


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
