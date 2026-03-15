"""Tests for Markdown dossier rendering."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation, ItemDatasheet, SearchHit
from fast_foto_forensics.reporting import render_item_dossier


def test_render_dossier_includes_identity_queries_and_sources() -> None:
    """Rendered dossiers should preserve key facts and citations."""
    datasheet = ItemDatasheet(
        probable_identity="Linksys WRT54G",
        object_class="router",
        likely_function="Wireless router",
        manufacturer="Linksys",
        model_identifiers=["WRT54G"],
        year_range="2002-2005",
        country_or_region="United States",
        security_findings=["Legacy firmware may have known weaknesses"],
        confidence=0.88,
        evidence_refs=["img-1"],
        search_hit_refs=["hit-1"],
        open_questions=["Confirm hardware revision"],
    )
    observations = [
        EvidenceObservation(
            evidence_id="img-1",
            source_path="rack-a/router.jpg",
            media_kind="image",
            sha256="abc",
            order_index=0,
            caption="A blue Linksys router.",
            ocr_text="WRT54G",
            candidate_identifiers=["WRT54G"],
        )
    ]
    hits = [
        SearchHit(
            hit_id="hit-1",
            provider="duckduckgo",
            query="WRT54G release date",
            title="Linksys WRT54G",
            snippet="The Linksys WRT54G is a wireless router series.",
            url="https://example.com/wrt54g",
        )
    ]

    markdown = render_item_dossier(datasheet, hits, observations)

    assert "## Probable Identity" in markdown
    assert "Linksys WRT54G" in markdown
    assert "WRT54G release date" in markdown
    assert "https://example.com/wrt54g" in markdown
