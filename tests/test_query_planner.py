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
    assert plan.selected_queries[0].text.startswith("WRT54G")
    assert plan.selected_queries[0].provenance[0] == "candidate_identifier"
    assert all(candidate.text for candidate in plan.selected_queries)
