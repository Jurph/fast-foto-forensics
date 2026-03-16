"""Single-image diagnostic runner contracts and helpers."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from fast_foto_forensics.models import EvidenceObservation, QueryPlan, SearchHit, VisionResult
from fast_foto_forensics.query_planner import build_query_plan
from fast_foto_forensics.reporting import render_item_dossier
from fast_foto_forensics.search import SearchProvider
from fast_foto_forensics.synthesis import SynthesisBackend, SynthesisFailure, synthesize_item_with_artifact
from fast_foto_forensics.vision import VisionBackend


@dataclass(slots=True)
class DiagnosticRequest:
    """Normalized input for one diagnostic web submission."""

    source_kind: str
    source_name: str
    image_bytes: bytes | None = None
    image_url: str | None = None

    @classmethod
    def from_upload_bytes(cls, filename: str, image_bytes: bytes) -> DiagnosticRequest:
        """Create a diagnostic request from uploaded image bytes."""
        return cls(
            source_kind="upload",
            source_name=filename,
            image_bytes=image_bytes,
        )

    @classmethod
    def from_image_url(cls, image_url: str) -> DiagnosticRequest:
        """Create a diagnostic request from a pasted image URL."""
        parsed = urlparse(image_url)
        segment = parsed.path.rsplit("/", 1)[-1] or "remote-image"
        return cls(
            source_kind="url",
            source_name=segment,
            image_url=image_url,
        )


@dataclass(slots=True)
class DiagnosticFailure:
    """One stage failure captured during a diagnostic run."""

    stage: str
    error: str


@dataclass(slots=True)
class DiagnosticResult:
    """JSON-friendly result object for the diagnostic web UI."""

    source_kind: str
    source_name: str
    source_preview_url: str
    log_messages: list[str] = field(default_factory=list)
    vision_json: dict[str, Any] | None = None
    vision_summary: str = ""
    query_plan: QueryPlan | None = None
    search_hits: list[SearchHit] = field(default_factory=list)
    datasheet_json: dict[str, Any] | None = None
    rendered_datasheet: str = ""
    failures: list[DiagnosticFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert the result into a JSON-friendly dictionary."""
        return {
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "source_preview_url": self.source_preview_url,
            "log_messages": list(self.log_messages),
            "vision_json": self.vision_json,
            "vision_summary": self.vision_summary,
            "query_plan": asdict(self.query_plan) if self.query_plan is not None else None,
            "search_hits": [asdict(hit) for hit in self.search_hits],
            "datasheet_json": self.datasheet_json,
            "rendered_datasheet": self.rendered_datasheet,
            "failures": [asdict(failure) for failure in self.failures],
        }


def summarize_vision_result(result: VisionResult) -> str:
    """Render a compact human-readable summary from a vision result."""
    bits: list[str] = []
    if result.vendor:
        bits.append(result.vendor)
    if result.object_class:
        bits.append(result.object_class)
    if result.candidate_identifiers:
        bits.append(", ".join(result.candidate_identifiers[:3]))
    if not bits and result.caption:
        bits.append(result.caption)
    return " | ".join(bits)


def _fetch_remote_image_bytes(image_url: str) -> bytes:
    """Fetch image bytes from a remote URL."""
    response = httpx.get(image_url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.content


def _materialize_request_image(
    request: DiagnosticRequest,
    work_root: Path,
    fetch_image_bytes,
) -> Path:
    """Write the diagnostic source image into the working directory."""
    work_root.mkdir(parents=True, exist_ok=True)
    image_path = work_root / request.source_name
    if request.image_bytes is not None:
        image_path.write_bytes(request.image_bytes)
        return image_path
    if request.image_url is not None:
        image_path.write_bytes(fetch_image_bytes(request.image_url))
        return image_path
    raise ValueError("diagnostic request is missing image content")


def run_diagnostic_request(
    request: DiagnosticRequest,
    *,
    work_root: Path,
    vision_backend: VisionBackend,
    search_provider: SearchProvider,
    synthesis_backend: SynthesisBackend,
    fetch_image_bytes=_fetch_remote_image_bytes,
) -> DiagnosticResult:
    """Execute a real single-image diagnostic run."""
    log_messages: list[str] = ["materializing image"]
    failures: list[DiagnosticFailure] = []
    image_path = _materialize_request_image(request, work_root, fetch_image_bytes)
    image_bytes = image_path.read_bytes()
    observation = EvidenceObservation(
        evidence_id="diagnostic-000",
        source_path=str(image_path),
        media_kind="image",
        sha256=hashlib.sha256(image_bytes).hexdigest(),
        order_index=0,
    )

    log_messages.append("running vision")
    vision_result = vision_backend.extract(observation)
    vision_json = vision_result.to_dict()
    observation.caption = vision_result.caption
    observation.ocr_text = vision_result.ocr_text
    observation.detected_labels = list(vision_result.detected_labels)
    observation.candidate_identifiers = list(vision_result.candidate_identifiers)
    observation.serial_numbers = list(vision_result.serial_numbers)
    observation.vendor = vision_result.vendor or ""
    observation.object_class = vision_result.object_class or ""

    log_messages.append("building query plan")
    query_plan = build_query_plan([observation], max_queries=5)

    log_messages.append("running search")
    search_hits: list[SearchHit] = []
    try:
        for candidate in query_plan.selected_queries:
            search_hits.extend(search_provider.search(candidate.text))
    except Exception as exc:
        failures.append(DiagnosticFailure(stage="search", error=str(exc)))

    log_messages.append("synthesizing datasheet")
    datasheet_json: dict[str, Any] | None = None
    rendered_datasheet = ""
    try:
        datasheet, _artifact = synthesize_item_with_artifact(
            [observation],
            search_hits,
            synthesis_backend,
        )
        datasheet_json = asdict(datasheet)
        log_messages.append("rendering result")
        rendered_datasheet = render_item_dossier(datasheet, search_hits, [observation])
    except SynthesisFailure as exc:
        failures.append(DiagnosticFailure(stage="synthesis", error=str(exc)))
    except Exception as exc:
        failures.append(DiagnosticFailure(stage="synthesis", error=str(exc)))

    return DiagnosticResult(
        source_kind=request.source_kind,
        source_name=request.source_name,
        source_preview_url=image_path.as_uri(),
        log_messages=log_messages,
        vision_json=vision_json,
        vision_summary=summarize_vision_result(vision_result),
        query_plan=query_plan,
        search_hits=search_hits,
        datasheet_json=datasheet_json,
        rendered_datasheet=rendered_datasheet,
        failures=failures,
    )
