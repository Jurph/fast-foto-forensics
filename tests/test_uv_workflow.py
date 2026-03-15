"""Tests for uv lockfile and wrapper workflow hygiene."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


def test_uv_lock_tracks_all_optional_dependency_groups() -> None:
    """Committed uv.lock should cover every optional dependency group in pyproject."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lockfile = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))

    expected_extras = sorted(
        extra_name.replace("_", "-") for extra_name in pyproject["project"]["optional-dependencies"]
    )
    root_package = next(
        package for package in lockfile["package"] if package["name"] == "fast-foto-forensics"
    )

    assert sorted(root_package["metadata"]["provides-extras"]) == expected_extras


def test_uvw_wrappers_lock_run_commands() -> None:
    """Local uv wrappers should force locked runs instead of mutating uv.lock."""
    batch_wrapper = Path("scripts/uvw.cmd").read_text(encoding="utf-8")
    powershell_wrapper = Path("scripts/uvw.ps1").read_text(encoding="utf-8")

    assert "--locked" in batch_wrapper
    assert "--locked" in powershell_wrapper


def test_readme_uses_locked_uv_run_for_verification_commands() -> None:
    """The README should teach locked verification runs, not mutating ones."""
    text = Path("README.md").read_text(encoding="utf-8")

    assert "uv run --locked --extra dev pytest" in text
    assert "uv run --locked --extra dev ruff check --no-cache src tests" in text
    assert "uv run --locked --extra dev mypy src" in text


@pytest.mark.skipif(sys.platform != "win32", reason="wrapper behavior test is Windows-specific")
def test_batch_wrapper_injects_locked_without_repeating_run(tmp_path: Path) -> None:
    """The cmd wrapper should forward `run` commands with `--locked` exactly once."""
    capture_path = tmp_path / "uv-args.txt"
    fake_uv = tmp_path / "uv.cmd"
    fake_uv.write_text(
        '@echo off\r\n>"%UVW_CAPTURE%" echo %*\r\nexit /b 0\r\n',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path};{env['PATH']}"
    env["UVW_CAPTURE"] = str(capture_path)

    result = subprocess.run(
        ["cmd", "/c", "scripts\\uvw.cmd", "run", "--extra", "dev", "pytest"],
        check=False,
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert capture_path.read_text(encoding="utf-8").strip() == "run --locked --extra dev pytest"
