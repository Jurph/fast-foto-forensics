"""Tests for sidecar tag persistence."""

from __future__ import annotations

import json
from pathlib import Path

from fast_foto_forensics.models import ImageTagSet
from fast_foto_forensics.tagging import write_tag_sidecar


def test_write_tag_sidecar_uses_json_and_does_not_touch_original() -> None:
    """Sidecar writes should preserve the original evidence file bytes."""
    image_path = Path(".tmp") / "tag-test.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"image-bytes")

    tag_set = ImageTagSet(
        tags=["gpu", "nvidia", "gtx 480"],
        caption="A dusty graphics card on a bench.",
        search_terms=["GTX 480 release date", "GTX 480 cve"],
    )

    sidecar_path = write_tag_sidecar(image_path, tag_set)

    assert sidecar_path.name.endswith(".fff-tags.json")
    assert image_path.read_bytes() == b"image-bytes"
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["tags"] == tag_set.tags
