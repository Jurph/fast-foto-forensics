"""Persistent run storage for artifacts and queue state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunStore:
    """A filesystem-backed run directory with a lightweight SQLite database."""

    run_dir: Path
    database_path: Path
    artifacts_dir: Path
    sidecars_dir: Path
    reports_dir: Path

    @classmethod
    def create(cls, output_root: Path, run_label: str) -> RunStore:
        run_dir = output_root / run_label
        return cls.from_run_dir(run_dir)

    @classmethod
    def from_run_dir(cls, run_dir: Path) -> RunStore:
        """Open or initialize a run store rooted at an explicit run directory."""
        artifacts_dir = run_dir / "artifacts"
        sidecars_dir = run_dir / "sidecars"
        reports_dir = run_dir / "reports"
        database_path = run_dir / "run.sqlite3"

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        sidecars_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        store = cls(
            run_dir=run_dir,
            database_path=database_path,
            artifacts_dir=artifacts_dir,
            sidecars_dir=sidecars_dir,
            reports_dir=reports_dir,
        )
        store._initialize_database()
        return store

    def artifact_path(self, relative_path: str) -> Path:
        """Resolve a path within the artifacts directory."""
        return self.artifacts_dir / relative_path

    def _initialize_database(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id INTEGER PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def write_json_artifact(self, relative_path: str, payload: dict[str, Any]) -> Path:
        artifact_path = self.artifacts_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return artifact_path

    def read_json_artifact(self, relative_path: str) -> dict[str, Any]:
        artifact_path = self.artifacts_dir / relative_path
        return json.loads(artifact_path.read_text(encoding="utf-8"))
