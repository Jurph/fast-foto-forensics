"""Tests for schema-first synthesis."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation, SearchHit
from fast_foto_forensics.synthesis import ReplaySynthesisBackend, synthesize_item


def test_json_synthesis_retries_when_first_payload_is_invalid() -> None:
    """Invalid model output should trigger one repair attempt."""
    backend = ReplaySynthesisBackend(
        responses=[
            "not-json-at-all",
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
              "evidence_refs": ["img-1"],
              "search_hit_refs": ["hit-1"],
              "open_questions": ["Confirm hardware revision"]
            }
            """,
        ]
    )

    result = synthesize_item(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        backend=backend,
    )

    assert result.probable_identity == "Linksys WRT54G"
    assert backend.calls == 2
