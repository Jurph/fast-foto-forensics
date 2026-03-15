"""Tests for evidence clustering."""

from __future__ import annotations

from fast_foto_forensics.clustering import cluster_observations
from fast_foto_forensics.models import EvidenceObservation


def test_cluster_observations_groups_adjacent_shared_identifier_images() -> None:
    """Adjacent items with the same identifier should share a cluster."""
    observations = [
        EvidenceObservation(
            evidence_id="img-1",
            source_path="rack-a/001-gpu.jpg",
            media_kind="image",
            sha256="aaa",
            order_index=0,
            candidate_identifiers=["GTX 480"],
            detected_labels=["gpu"],
        ),
        EvidenceObservation(
            evidence_id="img-2",
            source_path="rack-a/002-gpu-closeup.jpg",
            media_kind="image",
            sha256="bbb",
            order_index=1,
            candidate_identifiers=["GTX 480"],
            detected_labels=["gpu"],
        ),
        EvidenceObservation(
            evidence_id="img-3",
            source_path="rack-b/003-router.jpg",
            media_kind="image",
            sha256="ccc",
            order_index=2,
            candidate_identifiers=["WRT54G"],
            detected_labels=["router"],
        ),
    ]

    clusters = cluster_observations(observations)

    assert len(clusters) == 2
    assert clusters[0].evidence_refs == ["img-1", "img-2"]
    assert clusters[0].shared_identifiers == ["GTX 480"]
    assert clusters[1].evidence_refs == ["img-3"]
