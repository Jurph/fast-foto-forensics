"""Tests for run storage and queue state."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from fast_foto_forensics.storage import RunStore


def make_repo_temp_dir() -> Path:
    """Create a repo-local scratch directory without tempfile's Windows ACL behavior."""
    temp_root = Path(".scratch")
    temp_root.mkdir(exist_ok=True)
    target = temp_root / f"storage-{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def test_run_store_initializes_sqlite_and_artifact_paths() -> None:
    """Creating a run should create its directory structure and database."""
    temp_dir = make_repo_temp_dir()
    store = RunStore.create(temp_dir, run_label="demo-run")

    assert store.run_dir == temp_dir / "demo-run"
    assert store.database_path.exists()
    assert store.artifacts_dir.exists()
    assert store.sidecars_dir.exists()
    assert store.reports_dir.exists()

    with sqlite3.connect(store.database_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

    assert [row[0] for row in rows] == ["jobs", "run_metadata"]


def test_run_store_writes_and_reads_json_artifacts() -> None:
    """Artifacts should round-trip cleanly through the run store."""
    temp_dir = make_repo_temp_dir()
    store = RunStore.create(temp_dir, run_label="json-run")
    payload = {"probable_identity": "Linksys WRT54G", "confidence": 0.91}

    artifact_path = store.write_json_artifact("datasheets/router.json", payload)

    assert artifact_path.exists()
    assert store.read_json_artifact("datasheets/router.json") == payload
