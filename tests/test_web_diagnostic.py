"""Tests for the diagnostic web UI."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fast_foto_forensics.models import VisionResult
from fast_foto_forensics.search import StaticSearchProvider
from fast_foto_forensics.synthesis import ReplaySynthesisBackend
from fast_foto_forensics.vision import StaticVisionBackend
from fast_foto_forensics.web_diagnostic import create_diagnostic_app


def _make_client(tmp_path):
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
    app = create_diagnostic_app(
        work_root=tmp_path / "work",
        export_root=tmp_path / "exports",
        vision_backend=vision_backend,
        search_provider=search_provider,
        synthesis_backend=synthesis_backend,
        fetch_image_bytes=lambda image_url: b"remote-image",
    )
    return TestClient(app)


def test_get_root_serves_diagnostic_page(tmp_path) -> None:
    """The root page should render the diagnostic prototype UI."""
    client = _make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Fast Foto Forensics Diagnostic" in response.text
    assert "Export" in response.text


def test_upload_endpoint_returns_structured_result(tmp_path) -> None:
    """Uploading an image should run diagnostics and return section payloads."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/diagnose/upload",
        files={"image": ("router.jpg", b"fake-router-image", "image/jpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_name"] == "router.jpg"
    assert payload["source_preview_url"].startswith("data:image/jpeg;base64,")
    assert payload["vision_json"]["vendor"] == "Linksys"
    assert payload["datasheet_json"]["probable_identity"] == "Linksys WRT54G"
    assert payload["export_token"]


def test_url_endpoint_returns_structured_result(tmp_path) -> None:
    """Pasted image URLs should be fetched and diagnosed through the same pipeline."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/diagnose/url", json={"image_url": "https://example.com/router.jpg"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_kind"] == "url"
    assert payload["source_name"] == "router.jpg"
    assert payload["vision_summary"]


def test_url_endpoint_returns_json_error_payload_on_fetch_failure(tmp_path) -> None:
    """Endpoint failures should come back as JSON details for the browser UI."""
    app = create_diagnostic_app(
        work_root=tmp_path / "work",
        export_root=tmp_path / "exports",
        vision_backend=StaticVisionBackend(fixtures={}),
        search_provider=StaticSearchProvider(fixtures={}),
        synthesis_backend=ReplaySynthesisBackend(responses=[]),
        fetch_image_bytes=lambda image_url: (_ for _ in ()).throw(RuntimeError("fetch failed")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/diagnose/url", json={"image_url": "https://example.com/router.jpg"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "fetch failed"


def test_export_endpoint_writes_retry_fixture_from_cached_diagnostic(tmp_path) -> None:
    """Export should turn a prior diagnostic result into a retryable fixture."""
    client = _make_client(tmp_path)
    diagnose = client.post(
        "/api/diagnose/upload",
        files={"image": ("router.jpg", b"fake-router-image", "image/jpeg")},
    )
    token = diagnose.json()["export_token"]

    export_response = client.post(
        "/api/export",
        json={"export_token": token, "analyst_note": "save this as a flaky case"},
    )

    assert export_response.status_code == 200
    payload = export_response.json()
    assert payload["image_path"].endswith("router.jpg")
    assert payload["metadata_path"].endswith(".jpg.json")
