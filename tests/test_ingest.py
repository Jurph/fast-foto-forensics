"""Tests for evidence ingestion and hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fast_foto_forensics.ingest import ingest_path


def test_ingest_directory_creates_ordered_observations() -> None:
    """Supported files should be discovered, sorted, and hashed."""
    input_dir = Path(".tmp") / "ingest-case"
    input_dir.mkdir(parents=True, exist_ok=True)
    router_path = input_dir / "001-router.jpg"
    gpu_path = input_dir / "002-gpu.jpg"
    notes_path = input_dir / "003-notes.txt"

    router_path.write_bytes(b"router")
    gpu_path.write_bytes(b"gpu")
    notes_path.write_text("ignore me", encoding="utf-8")

    observations = ingest_path(input_dir)

    assert [Path(item.source_path).name for item in observations] == [
        "001-router.jpg",
        "002-gpu.jpg",
    ]
    assert observations[0].order_index == 0
    assert observations[1].order_index == 1
    assert observations[0].sha256 == hashlib.sha256(b"router").hexdigest()
    assert observations[1].sha256 == hashlib.sha256(b"gpu").hexdigest()
    assert all(item.media_kind == "image" for item in observations)
