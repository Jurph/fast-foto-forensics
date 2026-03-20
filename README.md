# Fast Foto Forensics

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/Jurph/fast-foto-forensics/tree/main.svg?style=shield)](https://dl.circleci.com/status-badge/redirect/gh/Jurph/fast-foto-forensics/tree/main)
[![codecov](https://codecov.io/gh/Jurph/fast-foto-forensics/branch/main/graph/badge.svg)](https://codecov.io/gh/Jurph/fast-foto-forensics/branch/main)

Fast Foto Forensics ingests evidence images, extracts identifiers and labels,
searches for corroborating references, synthesizes per-item datasheets, and
writes Markdown reports plus JSON sidecars.

## Install

Dependencies for this project are defined in `pyproject.toml`.

If you are using `uv`, choose the setup that matches the path you want to run:

```bash
uv sync --extra dev
uv sync --extra dev --extra search_ddgs --extra vision_ollama
uv sync --extra dev --extra ci
```

On Windows, this repo includes a wrapper that keeps uv's cache and managed
Python inside the repository instead of relying on user-level AppData paths:

```bat
.\scripts\uvw.cmd sync --extra dev
.\scripts\uvw.cmd sync --extra dev --extra search_ddgs --extra vision_ollama
.\scripts\uvw.cmd sync --extra dev --extra ci
.\scripts\uvw.cmd run --extra dev pytest
```

The first `sync` may still need normal network access to download Python or
wheels. After that, the wrapper keeps the repo self-contained. For `run`, the
wrapper also injects `--locked` so verification commands fail fast if
`uv.lock` falls behind `pyproject.toml` instead of rewriting the lockfile
during a test or lint pass.

The wrapper intentionally does **not** override `TMP` or `TEMP`. On this
machine, Python's `tempfile.mkdtemp()` and `TemporaryDirectory()` can create
Windows directories that immediately reject child files and folders. If you
need repo-local scratch space, use a normal directory such as `.scratch/`
created with `Path.mkdir()` and a unique name, not the `tempfile` directory
APIs.

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

Then install the dependency set you need:

```bash
pip install -e .[dev]
pip install -e .[dev,search_ddgs,vision_ollama]
```

<a href="https://hatch.pypa.io/1.13/config/metadata/">Hatch</a>,
<a href="https://pdm-project.org/en/latest/reference/pep621/">PDM</a>, and
<a href="https://python-poetry.org/docs/pyproject/">Poetry</a>
also support `pyproject.toml` natively.
If you prefer
<a href="https://docs.conda.io/projects/conda/en/25.5.x/user-guide/tasks/manage-environments.html">conda</a>,
you may need a few additional setup steps.

## Current CLI

- `scan <input_path>`
  - Quick inventory from the selected vision backend.
  - The default `filename` backend derives labels and identifiers from
    filenames only.
- `run <input_path> --output <dir>`
  - Ingest, enrich, cluster, search, synthesize, and write a run report.
- `render <run_dir>`
  - Rebuild `reports/report.md` from stored run artifacts.
- `tag <run_dir>`
  - Regenerate `.fff-tags.json` sidecars from stored run artifacts.
- `compose <run_dir>... --output <path>`
  - Merge multiple runs into one Markdown summary.
- `worker <vision|search>`
  - Scaffold command that currently prints readiness only.

## Backend Defaults

- Vision defaults to `filename`.
  - Use `--vision-backend ollama` for model-backed extraction.
- Search defaults to `ddgs`.
  - Install the `search_ddgs` extra for the default live search path.
  - Use `--offline` to skip live search and run with an empty static provider.
- Synthesis defaults to `ollama`.
  - Install the `vision_ollama` extra for the default synthesis path.
  - Use `--synthesis-backend heuristic` for a model-free fallback.
  - Use `--synthesis-backend remote` with `--api-base` / `--api-key` or
    environment variables for an OpenAI-compatible endpoint.

## Current Outputs

Each `run` creates a run directory containing:

- `artifacts/`
  - cached vision results plus per-cluster query plans, hits, datasheets, and
    synthesis provenance
- `reports/report.md`
  - the main human-readable dossier output
- `run.sqlite3`
  - lightweight per-run queue and metadata storage
- `.fff-tags.json` sidecars beside the source images

The current product surface is Markdown plus JSON artifacts. The workspace
hopper, incremental sweep, and PDF product ideas live in the design docs and
issue tracker, but they are not part of the shipped CLI yet.

## CI/CD

- CircleCI is the active CI system for this repo.
- `.github/workflows/ci.yml.disabled` is kept as a disabled template, not an
  active workflow.
- Codecov uploads are driven from CircleCI when `CODECOV_TOKEN` is configured.

## Standard commands

```bash
uv sync --extra dev
uv sync --extra dev --extra search_ddgs --extra vision_ollama
uv sync --extra dev --extra ci
uv run --locked --extra dev pytest
uv run --locked --extra dev pytest --cov=src/fast_foto_forensics --cov-report=term
uv run --locked --extra dev ruff check --no-cache src tests
uv run --locked --extra dev ruff format --check src tests
uv run --locked --extra dev mypy src
uv run --locked --extra dev fast-foto-forensics scan path/to/images
uv run --locked --extra dev --extra search_ddgs --extra vision_ollama fast-foto-forensics run path/to/images --output runs
uv run --locked --extra dev fast-foto-forensics run path/to/images --output runs --offline --synthesis-backend heuristic
```
