"""Evidence file discovery and normalization."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fast_foto_forensics.models import EvidenceObservation

SUPPORTED_SUFFIXES = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".avif": "image",
    ".pdf": "document",
}


def discover_supported_files(input_path: Path) -> list[Path]:
    """Return supported evidence files in deterministic sorted order."""
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in SUPPORTED_SUFFIXES else []
    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def build_observation(source_path: Path, order_index: int) -> EvidenceObservation:
    """Create a normalized observation with content hash and file metadata."""
    file_bytes = source_path.read_bytes()
    return EvidenceObservation(
        evidence_id=f"obs-{order_index:04d}",
        source_path=str(source_path),
        media_kind=SUPPORTED_SUFFIXES[source_path.suffix.lower()],
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        order_index=order_index,
    )


def ingest_path(input_path: Path) -> list[EvidenceObservation]:
    """Discover supported files and normalize them into observations."""
    return [
        build_observation(source_path=path, order_index=index)
        for index, path in enumerate(discover_supported_files(input_path))
    ]
