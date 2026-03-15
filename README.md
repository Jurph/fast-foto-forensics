# Fast Foto Forensics

Fast Foto Forensics is a project to [TODO].

The default workflow is intentionally opinionated:
- `uv` for environment and package management
- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` for gradual typing

The README still shows a `pip` fallback because that is part of being a good citizen in the wider Python community.

## What this template standardizes

- `src/` layout for import discipline
- `uv` as the default environment/package workflow
- `pytest` as the default test runner
- `ruff` for linting and formatting
- `mypy` for gradual typing
- one obvious place for project-specific notes
- one optional personal growth checklist that stays local by default

## Quick start

1. Create a new project from the template:

```bash
python deploy.py finnegan
```

2. Change into the new repo.
3. Follow the install instructions below.
4. Run the standard checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run fast-foto-forensics
```

## Template deployment

`deploy.py` is part of the template factory. It creates a sibling folder next to the template, copies the scaffold, renames the package, initializes git, and rewrites the most obvious placeholders. It does not get copied into the generated repo.

Examples:

```bash
python deploy.py finnegan
python deploy.py orbital-radio --dry-run
python deploy.py old-project --force
```

## Install

Dependencies for this project are defined in `pyproject.toml`.

If you are using `uv`:

```bash
uv sync --extra dev
```

If you are using `pip`:

First create a virtual environment:

```bash
python -m venv .venv
```

Then activate it:

```bash
# Linux/macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (cmd.exe)
.venv\Scripts\activate
```

Then install the project and development dependencies:

```bash
pip install -e .[dev]
```

<a href="https://hatch.pypa.io/1.13/config/metadata/">Hatch</a>,
<a href="https://pdm-project.org/en/latest/reference/pep621/">PDM</a>, and
<a href="https://python-poetry.org/docs/pyproject/">Poetry</a>
also support `pyproject.toml` natively.
If you prefer
<a href="https://docs.conda.io/projects/conda/en/25.5.x/user-guide/tasks/manage-environments.html">conda</a>,
you may need a few additional setup steps.

## Suggested first moves in a new repo

- Write down the project goal in `notes/project-brief.md`
- Define the first user-visible workflow before building helpers
- Decide what belongs in pure logic vs orchestration
- Add one smoke test before the first big feature
- Decide whether to commit `uv.lock` immediately or after the first real dependency lands

## Opinionated defaults

- Center `uv` in the README so the preferred workflow is obvious
- Keep packaging metadata in `pyproject.toml` so `uv` and `pip` both work cleanly
- Use `uv run ...` in examples so the happy path does not require manual activation
- Keep `pyproject.toml` as the single dependency source of truth
- Commit `uv.lock` once the project has real dependencies and you care about reproducibility
- Run normal CI checks on pushes and pull requests, and run dependency hygiene once per day on a schedule

## CI/CD hygiene

- `.github/workflows/ci.yml` runs tests, Ruff, and mypy on pushes and pull requests
- The same workflow runs `scripts/audit_dependencies.py` once per day to catch stale dependency declarations
- `scripts/audit_dependencies.py` is meant to be customized if a dependency's import name differs from its package name

## Standard commands

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run fast-foto-forensics
```
