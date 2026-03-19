"""End-to-end orchestration for a single local run."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fast_foto_forensics.clustering import cluster_observations
from fast_foto_forensics.ingest import ingest_path
from fast_foto_forensics.models import (
    EvidenceCluster,
    EvidenceObservation,
    ItemDatasheet,
    QueryPlan,
    SearchHit,
    SynthesisArtifact,
)
from fast_foto_forensics.query_planner import build_query_plan
from fast_foto_forensics.reporting import render_composed_summary, render_item_dossier
from fast_foto_forensics.search import SearchProvider
from fast_foto_forensics.storage import RunStore
from fast_foto_forensics.synthesis import (
    SynthesisBackend,
    SynthesisFailure,
    synthesize_item_with_artifact,
)
from fast_foto_forensics.tagging import build_tag_set, write_tag_sidecar
from fast_foto_forensics.vision import VisionBackend, enrich_observations

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClusterSummary:
    """Per-cluster outcome recorded during a pipeline run."""

    cluster_id: str
    identity: str
    evidence_count: int
    search_hits: int
    confidence: float


@dataclass(slots=True)
class ClusterFailure:
    """A cluster that failed during processing."""

    cluster_id: str
    stage: str  # "search", "synthesis", "tagging"
    error: str
    evidence_ids: list[str]


@dataclass(slots=True)
class RunResult:
    """High-level outputs from one pipeline run."""

    run_dir: Path
    report_path: Path
    sidecar_paths: list[Path]
    observation_count: int = 0
    cluster_count: int = 0
    cluster_summaries: list[ClusterSummary] = field(default_factory=list)
    failures: list[ClusterFailure] = field(default_factory=list)


def _load_observations(store: RunStore) -> dict[str, EvidenceObservation]:
    payload = store.read_json_artifact("observations.json")
    rows = payload.get("observations", [])
    return {
        observation.evidence_id: observation
        for observation in (
            EvidenceObservation.from_dict(item) for item in rows if isinstance(item, dict)
        )
    }


def _load_clusters(store: RunStore) -> list[EvidenceCluster]:
    payload = store.read_json_artifact("clusters.json")
    rows = payload.get("clusters", [])
    return [EvidenceCluster.from_dict(item) for item in rows if isinstance(item, dict)]


def _load_query_plan(store: RunStore, cluster_id: str) -> QueryPlan:
    payload = store.read_json_artifact(f"clusters/{cluster_id}/query-plan.json")
    return QueryPlan.from_dict(payload)


def _load_hits(store: RunStore, cluster_id: str) -> list[SearchHit]:
    payload = store.read_json_artifact(f"clusters/{cluster_id}/hits.json")
    rows = payload.get("hits", [])
    return [SearchHit.from_dict(item) for item in rows if isinstance(item, dict)]


def _load_datasheet(store: RunStore, cluster_id: str) -> ItemDatasheet:
    payload = store.read_json_artifact(f"clusters/{cluster_id}/datasheet.json")
    return ItemDatasheet.from_dict(payload)


def _load_synthesis_artifact(store: RunStore, cluster_id: str) -> SynthesisArtifact:
    payload = store.read_json_artifact(f"clusters/{cluster_id}/synthesis.json")
    return SynthesisArtifact.from_dict(payload)


def _write_cluster_artifacts(
    store: RunStore,
    cluster: EvidenceCluster,
    query_plan: QueryPlan,
    hits: list[SearchHit],
    datasheet: ItemDatasheet,
    synthesis_artifact: SynthesisArtifact,
) -> None:
    cluster_prefix = f"clusters/{cluster.cluster_id}"
    store.write_json_artifact(f"{cluster_prefix}/query-plan.json", asdict(query_plan))
    store.write_json_artifact(
        f"{cluster_prefix}/hits.json",
        {"hits": [asdict(hit) for hit in hits]},
    )
    store.write_json_artifact(f"{cluster_prefix}/datasheet.json", asdict(datasheet))
    store.write_json_artifact(f"{cluster_prefix}/synthesis.json", synthesis_artifact.to_dict())


def run_pipeline(
    input_path: Path,
    output_root: Path,
    run_label: str,
    vision_backend: VisionBackend,
    search_provider: SearchProvider,
    synthesis_backend: SynthesisBackend,
) -> RunResult:
    """Run the local evidence pipeline and persist its outputs."""
    store = RunStore.create(output_root, run_label)
    observations = enrich_observations(list(ingest_path(input_path)), vision_backend, store)
    store.write_json_artifact(
        "observations.json",
        {"observations": [asdict(item) for item in observations]},
    )

    clusters = cluster_observations(observations)
    store.write_json_artifact(
        "clusters.json",
        {"clusters": [asdict(cluster) for cluster in clusters]},
    )
    sidecar_paths: list[Path] = []
    report_sections: list[str] = []
    cluster_summaries: list[ClusterSummary] = []
    failures: list[ClusterFailure] = []

    for cluster in clusters:
        cluster_observations_list = [
            observation
            for observation in observations
            if observation.evidence_id in cluster.evidence_refs
        ]
        query_plan = build_query_plan(cluster_observations_list, max_queries=3)

        # Search — partial failure yields zero hits, not a crash
        hits: list[SearchHit] = []
        try:
            for candidate in query_plan.selected_queries:
                hits.extend(search_provider.search(candidate.text))
        except Exception as exc:
            logger.warning("Search failed for cluster %s: %s", cluster.cluster_id, exc)
            failures.append(
                ClusterFailure(
                    cluster_id=cluster.cluster_id,
                    stage="search",
                    error=str(exc),
                    evidence_ids=list(cluster.evidence_refs),
                )
            )

        # Synthesis — partial failure records a placeholder datasheet
        synthesis_artifact: SynthesisArtifact
        try:
            datasheet, synthesis_artifact = synthesize_item_with_artifact(
                cluster_observations_list,
                hits,
                synthesis_backend,
            )
        except SynthesisFailure as exc:
            logger.warning("Synthesis failed for cluster %s: %s", cluster.cluster_id, exc)
            failures.append(
                ClusterFailure(
                    cluster_id=cluster.cluster_id,
                    stage="synthesis",
                    error=str(exc),
                    evidence_ids=list(cluster.evidence_refs),
                )
            )
            synthesis_artifact = exc.artifact
            # Build a minimal placeholder so the report still renders
            datasheet = ItemDatasheet(
                probable_identity="Unidentified device",
                object_class="unknown",
                likely_function="unknown",
                manufacturer="Unknown",
                model_identifiers=[],
                evidence_refs=[obs.evidence_id for obs in cluster_observations_list],
                open_questions=[f"Synthesis failed: {exc}"],
            )
        except Exception as exc:
            logger.warning("Synthesis failed for cluster %s: %s", cluster.cluster_id, exc)
            failures.append(
                ClusterFailure(
                    cluster_id=cluster.cluster_id,
                    stage="synthesis",
                    error=str(exc),
                    evidence_ids=list(cluster.evidence_refs),
                )
            )
            backend_name = getattr(synthesis_backend, "__class__", type(synthesis_backend)).__name__
            synthesis_artifact = SynthesisArtifact(
                backend_name=backend_name,
                model_name=str(
                    getattr(
                        synthesis_backend,
                        "model",
                        backend_name,
                    )
                ),
                schema_name="ItemDatasheet",
                raw_payload="",
                accepted=False,
                attempt_count=1,
                last_error=str(exc),
            )
            datasheet = ItemDatasheet(
                probable_identity="Unidentified device",
                object_class="unknown",
                likely_function="unknown",
                manufacturer="Unknown",
                model_identifiers=[],
                evidence_refs=[obs.evidence_id for obs in cluster_observations_list],
                open_questions=[f"Synthesis failed: {exc}"],
            )

        _write_cluster_artifacts(
            store,
            cluster,
            query_plan,
            hits,
            datasheet,
            synthesis_artifact,
        )
        report_sections.append(
            render_item_dossier(
                datasheet,
                hits,
                cluster_observations_list,
                query_plan=query_plan,
                synthesis_artifact=synthesis_artifact,
            )
        )

        cluster_summaries.append(
            ClusterSummary(
                cluster_id=cluster.cluster_id,
                identity=datasheet.probable_identity,
                evidence_count=len(cluster_observations_list),
                search_hits=len(hits),
                confidence=datasheet.confidence,
            )
        )

        for observation in cluster_observations_list:
            tag_set = build_tag_set(observation, datasheet, hits)
            sidecar_paths.append(write_tag_sidecar(Path(observation.source_path), tag_set))

    report_path = store.reports_dir / "report.md"
    report_path.write_text("\n\n".join(report_sections), encoding="utf-8")
    return RunResult(
        run_dir=store.run_dir,
        report_path=report_path,
        sidecar_paths=sidecar_paths,
        observation_count=len(observations),
        cluster_count=len(clusters),
        cluster_summaries=cluster_summaries,
        failures=failures,
    )


def rerender_run(run_dir: Path) -> Path:
    """Rebuild the Markdown report from persisted structured artifacts."""
    store = RunStore.from_run_dir(run_dir)
    observations = _load_observations(store)
    report_sections: list[str] = []

    for cluster in _load_clusters(store):
        datasheet = _load_datasheet(store, cluster.cluster_id)
        query_plan = _load_query_plan(store, cluster.cluster_id)
        hits = _load_hits(store, cluster.cluster_id)
        synthesis_artifact = _load_synthesis_artifact(store, cluster.cluster_id)
        cluster_observations_list = [
            observations[evidence_id]
            for evidence_id in cluster.evidence_refs
            if evidence_id in observations
        ]
        report_sections.append(
            render_item_dossier(
                datasheet,
                hits,
                cluster_observations_list,
                query_plan=query_plan,
                synthesis_artifact=synthesis_artifact,
            )
        )

    report_path = store.reports_dir / "report.md"
    report_path.write_text("\n\n".join(report_sections), encoding="utf-8")
    return report_path


def rewrite_sidecars(run_dir: Path) -> list[Path]:
    """Rebuild image sidecars from persisted structured artifacts."""
    store = RunStore.from_run_dir(run_dir)
    observations = _load_observations(store)
    sidecar_paths: list[Path] = []

    for cluster in _load_clusters(store):
        datasheet = _load_datasheet(store, cluster.cluster_id)
        hits = _load_hits(store, cluster.cluster_id)
        for evidence_id in cluster.evidence_refs:
            observation = observations.get(evidence_id)
            if observation is None:
                continue
            tag_set = build_tag_set(observation, datasheet, hits)
            sidecar_paths.append(write_tag_sidecar(Path(observation.source_path), tag_set))
    return sidecar_paths


def compose_runs(run_dirs: list[Path], output_path: Path) -> Path:
    """Render a multi-run Markdown summary from persisted datasheets."""
    run_summaries: list[tuple[str, list[ItemDatasheet]]] = []
    for run_dir in run_dirs:
        store = RunStore.from_run_dir(run_dir)
        datasheets = [
            _load_datasheet(store, cluster.cluster_id) for cluster in _load_clusters(store)
        ]
        run_summaries.append((run_dir.name, datasheets))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_composed_summary(run_summaries), encoding="utf-8")
    return output_path
