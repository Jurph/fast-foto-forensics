"""Single-image diagnostic runner contracts and helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from fast_foto_forensics.models import QueryPlan, SearchHit, VisionResult


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
