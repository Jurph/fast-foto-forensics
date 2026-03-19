"""End-to-end pipeline tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fast_foto_forensics.models import EvidenceObservation, SearchHit
from fast_foto_forensics.pipeline import run_pipeline
from fast_foto_forensics.search import StaticSearchProvider
from fast_foto_forensics.synthesis import ReplaySynthesisBackend
from fast_foto_forensics.vision import FilenameVisionBackend


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
    assert "Confidence: 88%" in result.report_path.read_text(encoding="utf-8")
    assert "Synthesis attempts: 1" in result.report_path.read_text(encoding="utf-8")
    assert result.sidecar_paths[0].name.endswith(".fff-tags.json")

    # New summary fields
    assert result.observation_count == 1
    assert result.cluster_count == 1
    assert len(result.cluster_summaries) == 1
    assert result.cluster_summaries[0].identity == "Linksys WRT54G"
    assert result.cluster_summaries[0].confidence == 0.88
    assert result.failures == []

    cluster_dir = output_dir / "demo-run" / "artifacts" / "clusters" / "cluster-000"
    query_plan_path = cluster_dir / "query-plan.json"
    datasheet_path = cluster_dir / "datasheet.json"
    synthesis_path = cluster_dir / "synthesis.json"
    assert query_plan_path.exists()
    assert datasheet_path.exists()
    assert synthesis_path.exists()

    query_plan_payload = json.loads(query_plan_path.read_text(encoding="utf-8"))
    assert query_plan_payload["selected_queries"][0]["explanation"]

    synthesis_payload = json.loads(synthesis_path.read_text(encoding="utf-8"))
    assert synthesis_payload["accepted"] is True
    assert synthesis_payload["backend_name"] == "replay"
    assert synthesis_payload["model_name"] == "fixture"
    assert synthesis_payload["schema_name"] == "ItemDatasheet"
    assert "Analyze the evidence observations and search hits" in synthesis_payload["prompt_text"]
    assert "Linksys WRT54G" in synthesis_payload["raw_payload"]


def test_run_pipeline_records_synthesis_failure() -> None:
    """When synthesis fails, the pipeline should continue and record the failure."""
    input_dir = Path(".tmp") / "pipeline-fail-case"
    output_dir = Path(".tmp") / "pipeline-fail-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router-image")

    @dataclass(slots=True)
    class FailingSynthesisBackend:
        def generate(
            self,
            observations: list[EvidenceObservation],
            hits: list[SearchHit],
            previous_error: str | None = None,
        ) -> str:
            raise RuntimeError("LLM backend unavailable")

    result = run_pipeline(
        input_path=input_dir,
        output_root=output_dir,
        run_label="fail-demo",
        vision_backend=FilenameVisionBackend(),
        search_provider=StaticSearchProvider(fixtures={}),
        synthesis_backend=FailingSynthesisBackend(),
    )

    # Run still completes
    assert result.report_path.exists()
    assert result.observation_count == 1
    assert result.cluster_count == 1

    # Failure is recorded
    assert len(result.failures) == 1
    assert result.failures[0].stage == "synthesis"
    assert "LLM backend unavailable" in result.failures[0].error

    # Placeholder identity appears in summary and report
    assert result.cluster_summaries[0].identity == "Unidentified device"
    assert "Unidentified device" in result.report_path.read_text(encoding="utf-8")

    cluster_dir = output_dir / "fail-demo" / "artifacts" / "clusters" / "cluster-000"
    datasheet_path = cluster_dir / "datasheet.json"
    synthesis_path = cluster_dir / "synthesis.json"
    assert datasheet_path.exists()
    assert synthesis_path.exists()

    synthesis_payload = json.loads(synthesis_path.read_text(encoding="utf-8"))
    assert synthesis_payload["accepted"] is False
    assert synthesis_payload["last_error"] == "LLM backend unavailable"
    assert synthesis_payload["attempt_count"] == 1
