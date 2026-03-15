"""Simple grouping for related evidence observations."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fast_foto_forensics.models import EvidenceCluster, EvidenceObservation


def cluster_observations(observations: list[EvidenceObservation]) -> list[EvidenceCluster]:
    """Group observations by folder and shared identifiers."""
    grouped: dict[tuple[str, tuple[str, ...]], list[EvidenceObservation]] = defaultdict(list)
    for observation in observations:
        folder = str(Path(observation.source_path).parent)
        identifiers = tuple(sorted(observation.candidate_identifiers))
        grouped[(folder, identifiers)].append(observation)

    clusters: list[EvidenceCluster] = []
    for index, ((folder, identifiers), members) in enumerate(grouped.items()):
        clusters.append(
            EvidenceCluster(
                cluster_id=f"cluster-{index:03d}",
                evidence_refs=[member.evidence_id for member in members],
                shared_identifiers=list(identifiers),
                source_roots=[folder],
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.cluster_id)
