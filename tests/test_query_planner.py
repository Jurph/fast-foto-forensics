"""Tests for deterministic query planning."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation
from fast_foto_forensics.query_planner import build_query_plan, is_alphanumeric

# --- is_alphanumeric tests ---


def test_alphanumeric_model_number() -> None:
    assert is_alphanumeric("OC200") is True


def test_alphanumeric_serial() -> None:
    assert is_alphanumeric("G1A117060503877") is True


def test_alphanumeric_mac_address() -> None:
    assert is_alphanumeric("20.C0.47.2F.F9.0F") is True


def test_pure_alpha_not_alphanumeric() -> None:
    assert is_alphanumeric("Verizon") is False


def test_pure_digit_not_alphanumeric() -> None:
    assert is_alphanumeric("12345") is False


# --- Cross-product query building ---


def test_vendor_anchored_query_scores_highest() -> None:
    """When vendor is set, vendor × alphanumeric queries should score 5.0."""
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

    plan = build_query_plan([obs], max_queries=5)

    top = plan.selected_queries[0]
    # Vendor-anchored query should be at the top with score 5.0
    assert "linksys" in top.text.lower()
    assert "wrt54g" in top.text.lower()
    assert top.score == 5.0
    assert top.explanation
    assert "img-001" in top.explanation


def test_serial_numbers_paired_with_vendor() -> None:
    """Serial numbers are alphanumeric, so they get paired with context words."""
    obs = EvidenceObservation(
        evidence_id="img-002",
        source_path="evidence/router-back.jpg",
        media_kind="image",
        sha256="def456",
        order_index=1,
        caption="Back panel of a Verizon router.",
        ocr_text="Serial no. G1A117060503877",
        detected_labels=["USB", "Reset", "LAN"],
        candidate_identifiers=[],
        serial_numbers=["G1A117060503877"],
        vendor="Verizon",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=5)

    # The serial should appear paired with vendor
    assert len(plan.selected_queries) >= 1
    top = plan.selected_queries[0]
    assert "G1A117060503877" in top.text
    assert "Verizon" in top.text


def test_ocr_blob_is_last_resort() -> None:
    """The raw OCR text should appear as a low-scoring fallback query."""
    obs = EvidenceObservation(
        evidence_id="img-003",
        source_path="evidence/controller.jpg",
        media_kind="image",
        sha256="ghi789",
        order_index=2,
        caption="A TP-Link Omada hardware controller.",
        ocr_text="tp-link Omada\nOmada Hardware Controller\nLAN\nWAN\nReset",
        detected_labels=["tp-link", "Omada", "Omada Hardware Controller", "LAN", "WAN", "Reset"],
        candidate_identifiers=["OC200"],
        vendor="TP-Link",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=30)

    # The OCR blob should exist and have score <= 1.0
    ocr_queries = [q for q in plan.selected_queries if "ocr_blob" in q.provenance]
    assert len(ocr_queries) == 1
    assert ocr_queries[0].score <= 1.0

    # The vendor-anchored cross-product query should rank above it
    top = plan.selected_queries[0]
    assert top.score > ocr_queries[0].score


def test_fallback_when_vendor_is_blank() -> None:
    """When vendor is empty, other context words still pair with alphanumerics."""
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
        vendor="",
        object_class="",
    )

    plan = build_query_plan([obs], max_queries=5)

    # Should still produce queries from context words × alphanumerics
    assert len(plan.selected_queries) >= 1
    all_text = " ".join(q.text for q in plan.selected_queries).lower()
    assert "nvidia" in all_text or "gtx" in all_text


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


def test_analyst_hints_included() -> None:
    """Analyst hints should appear as a query."""
    obs = EvidenceObservation(
        evidence_id="img-008",
        source_path="evidence/device.jpg",
        media_kind="image",
        sha256="vwx234",
        order_index=7,
        caption="A Linksys router.",
        ocr_text="WRT54G LINKSYS",
        detected_labels=["router"],
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
        analyst_hints=["home lab equipment"],
    )

    plan = build_query_plan([obs], max_queries=10)

    hint_queries = [q for q in plan.selected_queries if "analyst_hint" in q.provenance]
    assert len(hint_queries) == 1
    assert "analyst hint" in hint_queries[0].explanation.lower()


def test_cross_product_generates_multiple_queries() -> None:
    """Multiple context words × multiple alphanumerics = many queries."""
    obs = EvidenceObservation(
        evidence_id="img-009",
        source_path="evidence/controller.jpg",
        media_kind="image",
        sha256="yz0123",
        order_index=8,
        caption="An Omada controller.",
        ocr_text="tp-link OC200 ER605",
        detected_labels=["tp-link", "Omada"],
        candidate_identifiers=["OC200", "ER605"],
        vendor="TP-Link",
        object_class="controller",
    )

    plan = build_query_plan([obs], max_queries=20)

    # Should have at least vendor × 2 alphanumerics = 2 vendor queries
    texts = [q.text for q in plan.selected_queries]
    vendor_queries = [t for t in texts if "tp-link" in t.lower()]
    assert len(vendor_queries) >= 2


def test_dedup_prevents_duplicate_queries() -> None:
    """Same word+alphanum pair from different sources should merge, not duplicate."""
    obs = EvidenceObservation(
        evidence_id="img-010",
        source_path="evidence/device.jpg",
        media_kind="image",
        sha256="abc999",
        order_index=9,
        caption="Linksys WRT54G router.",
        ocr_text="LINKSYS WRT54G",
        detected_labels=["Linksys"],
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="router",
    )

    plan = build_query_plan([obs], max_queries=20)

    # "Linksys WRT54G" should appear only once despite multiple sources
    texts_lower = [q.text.casefold() for q in plan.selected_queries]
    assert texts_lower.count("linksys wrt54g") == 1


def test_vendor_identifier_and_function_enable_document_mode_queries() -> None:
    """Strong product anchors should add doc-intent queries."""
    obs = EvidenceObservation(
        evidence_id="img-011",
        source_path="evidence/router.jpg",
        media_kind="image",
        sha256="doc111",
        order_index=10,
        caption="A Linksys wireless router.",
        ocr_text="LINKSYS WRT54G",
        detected_labels=["router"],
        candidate_identifiers=["WRT54G"],
        vendor="Linksys",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=12)

    texts = [query.text.casefold() for query in plan.selected_queries]
    assert "linksys wrt54g" in texts
    assert "linksys wrt54g datasheet" in texts
    assert "linksys wrt54g manual" in texts


def test_ambiguous_identifier_with_context_uses_mixed_mode() -> None:
    """Weak-but-plausible identifiers should keep one foot in identity mode."""
    obs = EvidenceObservation(
        evidence_id="img-012",
        source_path="evidence/device.jpg",
        media_kind="image",
        sha256="mix222",
        order_index=11,
        caption="A small Acme network controller.",
        ocr_text="ACME AB12CD34",
        detected_labels=["controller"],
        candidate_identifiers=[],
        vendor="Acme",
        object_class="controller",
    )

    plan = build_query_plan([obs], max_queries=12)

    texts = [query.text.casefold() for query in plan.selected_queries]
    doc_queries = [
        text
        for text in texts
        if any(term in text for term in ("datasheet", "manual", "specifications"))
    ]
    assert "acme ab12cd34" in texts
    assert "acme ab12cd34 datasheet" in texts
    assert len(doc_queries) == 1


def test_serial_like_tokens_do_not_trigger_document_mode_queries() -> None:
    """Serial-number lookups should stay in identity mode, not jump to datasheets."""
    obs = EvidenceObservation(
        evidence_id="img-013",
        source_path="evidence/router-back.jpg",
        media_kind="image",
        sha256="ser333",
        order_index=12,
        caption="Back panel of a Verizon router.",
        ocr_text="Serial no. G1A117060503877",
        detected_labels=["router", "serial"],
        candidate_identifiers=[],
        serial_numbers=["G1A117060503877"],
        vendor="Verizon",
        object_class="wireless router",
    )

    plan = build_query_plan([obs], max_queries=12)

    texts = [query.text.casefold() for query in plan.selected_queries]
    assert "verizon g1a117060503877" in texts
    assert all(term not in " ".join(texts) for term in ("datasheet", "manual", "specifications"))
