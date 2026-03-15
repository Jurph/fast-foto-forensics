#!/usr/bin/env python3
"""Audit declared Python dependencies against imports in the repo.

This starter script is intentionally conservative. It uses simple heuristics for
mapping package names to import roots, and provides override lists for projects
whose import names differ from their published package names.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
SCAN_DIRS = ("src", "tests", "scripts")

# Add entries here when the import root differs from the published package name.
CUSTOM_IMPORT_ROOTS: dict[str, set[str]] = {}

# Add build/test/CI tools here if they should be exempt from import matching.
TOOLING_DEPS = {
    "mypy",
    "pytest",
    "ruff",
    "tomli",
}


def _normalize_dependency_name(spec: str) -> str:
    match = re.match(r"[A-Za-z0-9_.-]+", spec.strip())
    if not match:
        raise ValueError(f"Could not parse dependency spec: {spec!r}")
    return match.group(0)


def _candidate_import_roots(dependency: str) -> set[str]:
    if dependency in CUSTOM_IMPORT_ROOTS:
        return CUSTOM_IMPORT_ROOTS[dependency]

    normalized = dependency.lower().replace("-", "_").replace(".", "_")
    candidates = {normalized}

    if normalized.startswith("py") and len(normalized) > 2:
        candidates.add(normalized[2:])

    return candidates


def _load_declared_dependencies() -> set[str]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = data.get("project", {})
    optional = project.get("optional-dependencies", {})

    declared = set()
    for spec in project.get("dependencies", []):
        declared.add(_normalize_dependency_name(spec))
    for group_specs in optional.values():
        for spec in group_specs:
            declared.add(_normalize_dependency_name(spec))
    return declared


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        root = REPO_ROOT / directory
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    return files


def _collect_import_roots() -> set[str]:
    roots: set[str] = set()

    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])

    return roots


def main() -> int:
    declared = _load_declared_dependencies()
    observed_import_roots = _collect_import_roots()

    unused = sorted(
        dependency
        for dependency in declared
        if dependency not in TOOLING_DEPS
        and not (_candidate_import_roots(dependency) & observed_import_roots)
    )

    missing = sorted(
        root
        for root in observed_import_roots
        if root not in {"__future__"} and root not in {".git", "src", "tests"}
    )

    project_roots = {
        path.name
        for path in (REPO_ROOT / "src").iterdir()
        if path.is_dir()
    } if (REPO_ROOT / "src").exists() else set()

    standard_exclusions = project_roots | {
        "pathlib",
        "typing",
        "re",
        "ast",
        "tomllib",
        "tomli",
    }

    missing = sorted(
        root
        for root in missing
        if root not in standard_exclusions
        and root
        not in {
            candidate
            for dependency in declared
            for candidate in _candidate_import_roots(dependency)
        }
    )

    if not unused and not missing:
        print("Dependency audit passed: declared dependencies match observed imports.")
        return 0

    if unused:
        print("Possibly unused top-level dependencies:")
        for dependency in unused:
            print(f"  - {dependency}")

    if missing:
        print("Possibly missing top-level dependencies for these import roots:")
        for root in missing:
            print(f"  - {root}")
        print("If any package name differs from its import name, add it to CUSTOM_IMPORT_ROOTS.")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
