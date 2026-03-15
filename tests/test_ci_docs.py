"""Tests for repository CI and coverage documentation/configuration."""

from __future__ import annotations

from pathlib import Path


def test_readme_mentions_circleci_and_codecov() -> None:
    """The README should advertise the active CI and coverage dashboard."""
    text = Path("README.md").read_text(encoding="utf-8")
    assert "CircleCI" in text
    assert "codecov" in text.lower()


def test_disabled_github_actions_template_exists() -> None:
    """The GitHub Actions workflow should remain in the repo, but disabled."""
    assert Path(".github/workflows/ci.yml.disabled").exists()


def test_circleci_config_exists_and_runs_pytest_with_coverage() -> None:
    """CircleCI should own active CI and publish a coverage artifact."""
    text = Path(".circleci/config.yml").read_text(encoding="utf-8")
    assert "pytest" in text
    assert "coverage.xml" in text
    assert "codecov" in text.lower()


def test_codecov_config_exists() -> None:
    """The repo should declare Codecov behavior explicitly."""
    text = Path(".codecov.yml").read_text(encoding="utf-8")
    assert "coverage:" in text
    assert "comment:" in text
