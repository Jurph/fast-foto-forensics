"""Tests for deterministic query planning."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation
from fast_foto_forensics.query_planner import build_query_plan


def test_query_planner_prioritizes_identifiers_and_limits_results() -> None:
    """Identifier-rich queries should be ranked first and capped."""
    observation = EvidenceObservation(
        evidence_id="img-002",
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="def456",
        order_index=1,
        caption="A blue Linksys router with antennas.",
        ocr_text="WRT54G LINKSYS",
        detected_labels=["router", "networking"],
        candidate_identifiers=["WRT54G"],
        analyst_hints=["home lab"],
    )

    plan = build_query_plan([observation], max_queries=3)

    assert len(plan.selected_queries) == 3
    assert "WRT54G" in plan.selected_queries[0].text
    assert plan.selected_queries[0].provenance[0] == "candidate_identifier"
    assert all(candidate.text for candidate in plan.selected_queries)


def test_query_planner_compacts_brand_identifier_and_object_terms() -> None:
    """Identifier-led queries should include strong brand and object signals when present."""
    observation = EvidenceObservation(
        evidence_id="img-003",
        source_path="evidence/router-closeup.jpg",
        media_kind="image",
        sha256="ghi789",
        order_index=2,
        caption="A blue Linksys router with antennas on a shelf.",
        ocr_text="FCC ID Q87-WRT54G LINKSYS",
        detected_labels=["router", "networking"],
        candidate_identifiers=["WRT54G"],
        analyst_hints=[],
    )

    plan = build_query_plan([observation], max_queries=3)

    assert plan.selected_queries[0].text.lower() == "linksys wrt54g router"
    assert "brand:linksys" in plan.selected_queries[0].provenance
    assert "object:router" in plan.selected_queries[0].provenance


def test_query_planner_filters_low_value_ocr_noise() -> None:
    """Low-value OCR fragments should not outrank compact identifying terms."""
    observation = EvidenceObservation(
        evidence_id="img-004",
        source_path="evidence/gpu-card.jpg",
        media_kind="image",
        sha256="jkl012",
        order_index=3,
        caption="A dusty NVIDIA graphics card on a workbench.",
        ocr_text="FCC ID GPU-123 REV A NVIDIA GTX 480 SN 9988",
        detected_labels=["gpu", "graphics card"],
        candidate_identifiers=["GTX 480"],
        analyst_hints=[],
    )

    plan = build_query_plan([observation], max_queries=3)
    selected_text = " || ".join(candidate.text.lower() for candidate in plan.selected_queries)

    assert plan.selected_queries[0].text.lower() == "nvidia gtx 480 gpu"
    assert "fcc" not in selected_text
    assert " rev " not in f" {selected_text} "
    assert " sn " not in f" {selected_text} "
