# Fast Foto Forensics

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/Jurph/fast-foto-forensics/tree/main.svg?style=shield)](https://dl.circleci.com/status-badge/redirect/gh/Jurph/fast-foto-forensics/tree/main)
[![codecov](https://codecov.io/gh/Jurph/fast-foto-forensics/branch/main/graph/badge.svg)](https://codecov.io/gh/Jurph/fast-foto-forensics)

Fast Foto Forensics is a project to ingest images and accumulate first-party or best-guess datasheets for each electronic device in the images.

## Install

Dependencies for this project are defined in `pyproject.toml`.

If you are using `uv`:

```bash
uv sync --extra dev
uv sync --extra dev --extra ci
```

On Windows, this repo includes a wrapper that keeps uv's cache and managed Python inside the
repository instead of relying on user-level AppData paths:

```bat
.\scripts\uvw.cmd sync --extra dev
.\scripts\uvw.cmd sync --extra dev --extra ci
.\scripts\uvw.cmd run --extra dev pytest
```

The first `sync` may still need normal network access to download Python or wheels. After that,
the wrapper keeps the repo self-contained.

The wrapper intentionally does **not** override `TMP` or `TEMP`. On this machine, Python's
`tempfile.mkdtemp()` and `TemporaryDirectory()` can create Windows directories that immediately
reject child files and folders. If you need repo-local scratch space, use a normal directory such
as `.scratch/` created with `Path.mkdir()` and a unique name, not the `tempfile` directory APIs.

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
uv sync --extra dev --extra ci
uv run --extra dev pytest
uv run --extra dev pytest --cov=src/fast_foto_forensics --cov-report=term
uv run --extra dev ruff check --no-cache src tests
uv run --extra dev ruff format src tests
uv run --extra dev mypy src
uv run fast-foto-forensics
```
