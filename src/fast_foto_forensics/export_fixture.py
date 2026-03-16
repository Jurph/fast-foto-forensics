"""Helpers for exporting diagnostic cases into a retry corpus."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from fast_foto_forensics.diagnostic_runner import DiagnosticRequest, DiagnosticResult


@dataclass(slots=True)
class ExportedFixture:
    """Paths created by exporting one diagnostic case."""

    image_path: Path
    metadata_path: Path


def export_diagnostic_fixture(
    request: DiagnosticRequest,
    result: DiagnosticResult,
    *,
    export_root: Path,
    analyst_note: str = "",
) -> ExportedFixture:
    """Persist a diagnostic source image plus metadata for later retry."""
    if not result.source_image_bytes:
        raise ValueError("diagnostic result is missing source image bytes")

    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_name = Path(request.source_name).name or "diagnostic-image"
    image_path = export_root / f"{timestamp}-{source_name}"
    metadata_path = image_path.with_suffix(f"{image_path.suffix}.json")

    image_path.write_bytes(result.source_image_bytes)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_kind": request.source_kind,
        "source_name": request.source_name,
        "source_url": request.image_url,
        "analyst_note": analyst_note,
        "vision_backend_name": (result.vision_json or {}).get("backend_name"),
        "vision_model_name": (result.vision_json or {}).get("model_name"),
        "synthesis_backend_name": (result.synthesis_artifact or {}).get("backend_name"),
        "synthesis_model_name": (result.synthesis_artifact or {}).get("model_name"),
        "failures": [asdict(failure) for failure in result.failures],
    }
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return ExportedFixture(image_path=image_path, metadata_path=metadata_path)
