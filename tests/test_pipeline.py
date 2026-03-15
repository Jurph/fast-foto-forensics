"""End-to-end pipeline tests."""

from __future__ import annotations

from pathlib import Path

from fast_foto_forensics.pipeline import FilenameVisionBackend, run_pipeline
from fast_foto_forensics.search import StaticSearchProvider
from fast_foto_forensics.synthesis import ReplaySynthesisBackend


def test_run_pipeline_creates_artifacts_report_and_sidecars() -> None:
    """A local run should persist the expected report and sidecars."""
    input_dir = Path(".tmp") / "pipeline-case"
    output_dir = Path(".tmp") / "pipeline-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = input_dir / "001-wrt54g-router.jpg"
    image_path.write_bytes(b"router-image")

    search_provider = StaticSearchProvider(
        fixtures={
            "WRT54G router": [
                {
                    "title": "Linksys WRT54G product history",
                    "snippet": "The WRT54G is a well-known wireless router series.",
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
              "object_class": "router",
              "likely_function": "Wireless router",
              "manufacturer": "Linksys",
              "model_identifiers": ["WRT54G"],
              "year_range": "2002-2005",
              "country_or_region": "United States",
              "security_findings": ["Legacy firmware may have known weaknesses"],
              "confidence": 0.88,
              "evidence_refs": ["obs-0000"],
              "search_hit_refs": ["static-000"],
              "open_questions": ["Confirm hardware revision"]
            }
            """
        ]
    )

    result = run_pipeline(
        input_path=input_dir,
        output_root=output_dir,
        run_label="demo-run",
        vision_backend=FilenameVisionBackend(),
        search_provider=search_provider,
        synthesis_backend=synthesis_backend,
    )

    assert result.report_path.exists()
    assert result.sidecar_paths
    assert "Linksys WRT54G" in result.report_path.read_text(encoding="utf-8")
    assert result.sidecar_paths[0].name.endswith(".fff-tags.json")
