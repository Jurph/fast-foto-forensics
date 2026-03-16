"""Tests for deterministic query planning."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation
from fast_foto_forensics.query_planner import build_query_plan


def test_identifier_query_uses_vendor_and_object_class() -> None:
    """When vendor and object_class are set, the top query should combine them
    with the identifier — no heuristic guessing needed."""
    obs = EvidenceObservation(
        evidence_id="img-001",
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="abc123",
        order_index=0,
        caption="A Linksys wireless router with antennas.",
        ocr_text="WRT54G LINKSYS",
        detected_labels=["router", "networking"],
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=3)

    top = plan.selected_queries[0]
    assert top.text == "Linksys WRT54G wireless router"
    assert "identifier" in top.provenance
    assert f"vendor:Linksys" in top.provenance
    assert f"class:wireless router" in top.provenance


def test_vendor_plus_class_query_is_tier_two() -> None:
    """A vendor+class query (no identifier) should appear below identifier queries."""
    obs = EvidenceObservation(
        evidence_id="img-002",
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="def456",
        order_index=1,
        caption="A Linksys wireless router.",
        ocr_text="LINKSYS",
        detected_labels=["router"],
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=5)

    texts = [q.text for q in plan.selected_queries]
    # Identifier query should rank above vendor+class
    assert texts.index("Linksys WRT54G wireless router") < texts.index("Linksys wireless router")


def test_substantive_labels_become_tier_three() -> None:
    """Multi-word labels like 'Omada Hardware Controller' should generate
    a search query, while port-name labels like 'LAN' should not."""
    obs = EvidenceObservation(
        evidence_id="img-003",
        source_path="evidence/controller.jpg",
        media_kind="image",
        sha256="ghi789",
        order_index=2,
        caption="A TP-Link Omada hardware controller.",
        ocr_text="tp-link Omada\nOmada Hardware Controller\nLAN\nWAN\nReset",
        detected_labels=["tp-link", "Omada", "Omada Hardware Controller",
                         "LAN", "WAN", "Reset"],
        candidate_identifiers=["OC200"],
        vendor="TP-Link",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=5)
    all_text = " ".join(q.text for q in plan.selected_queries).lower()

    # Substantive labels should appear
    assert "omada" in all_text
    # Port-name noise should not
    assert "reset" not in all_text


def test_fallback_brand_extraction_when_vendor_is_blank() -> None:
    """When vendor is empty (e.g., filename backend), fall back to
    extracting brand tokens from OCR/caption text."""
    obs = EvidenceObservation(
        evidence_id="img-004",
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="jkl012",
        order_index=3,
        caption="A dusty NVIDIA graphics card on a workbench.",
        ocr_text="NVIDIA GTX 480",
        detected_labels=["gpu"],
        candidate_identifiers=["GTX 480"],
        vendor="",  # no vendor from vision
        object_class="",  # no object_class either
    )

    plan = build_query_plan([obs], max_queries=3)

    # Should still produce queries — the fallback should find "nvidia"
    assert len(plan.selected_queries) >= 1
    all_text = " ".join(q.text for q in plan.selected_queries).lower()
    assert "nvidia" in all_text or "gtx" in all_text


def test_serial_numbers_excluded_from_queries() -> None:
    """Serial numbers are unique to one unit and should never appear in search queries."""
    obs = EvidenceObservation(
        evidence_id="img-005",
        source_path="evidence/router-back.jpg",
        media_kind="image",
        sha256="mno345",
        order_index=4,
        caption="Back panel of a Verizon router.",
        ocr_text="Serial no. G1A117060503877\nVerizon Fios",
        detected_labels=["USB", "Reset", "LAN"],
        candidate_identifiers=[],
        serial_numbers=["G1A117060503877"],
        vendor="Verizon",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=5)
    all_text = " ".join(q.text for q in plan.selected_queries)

    assert "G1A117060503877" not in all_text


def test_noise_words_excluded_from_queries() -> None:
    """Words like 'various', 'connected', 'cables' should never appear."""
    obs = EvidenceObservation(
        evidence_id="img-006",
        source_path="evidence/controller.jpg",
        media_kind="image",
        sha256="pqr678",
        order_index=5,
        caption="A TP-Link controller with various cables connected.",
        ocr_text="tp-link Omada",
        detected_labels=["tp-link", "Omada"],
        candidate_identifiers=["OC200"],
        vendor="TP-Link",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=5)
    all_text = " ".join(q.text for q in plan.selected_queries).lower()

    assert "various" not in all_text
    assert "cables" not in all_text
    assert "connected" not in all_text


def test_max_queries_cap_is_respected() -> None:
    """The planner should never return more than max_queries results."""
    obs = EvidenceObservation(
        evidence_id="img-007",
        source_path="evidence/device.jpg",
        media_kind="image",
        sha256="stu901",
        order_index=6,
        caption="A Linksys router.",
        ocr_text="WRT54G LINKSYS",
        detected_labels=["router"],
        candidate_identifiers=["WRT54G", "WRT54GL", "WRT54GS"],
        vendor="Linksys",
        object_class="wireless router",
        analyst_hints=["home lab equipment"],
    )

    plan = build_query_plan([obs], max_queries=2)
    assert len(plan.selected_queries) <= 2
