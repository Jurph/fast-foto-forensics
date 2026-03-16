# Diagnostic Web UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tiny local web front-end that runs the real end-to-end pipeline for one image and exposes intermediate artifacts plus an explicit export path for retry fixtures.

**Architecture:** Build a lightweight FastAPI app that wraps a new single-image diagnostic runner. Keep the UI stateless by default, stream progress from backend stages, and persist data only when the operator clicks `Export`.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, httpx, existing vision/search/synthesis modules, pytest, Ruff, mypy, uv

---

## Chunk 1: Dependencies and Diagnostic Contracts

### Task 1: Add web dependencies and runner contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/fast_foto_forensics/diagnostic_runner.py`
- Test: `tests/test_diagnostic_runner.py`

- [ ] **Step 1: Write failing tests for a single-image diagnostic result contract**

Add tests in `tests/test_diagnostic_runner.py` for:
- upload-backed diagnostic requests
- URL-backed diagnostic requests
- a structured result object carrying image preview info, live log messages, vision JSON, summary text, query plan, search hits, datasheet JSON, rendered datasheet, and failures

- [ ] **Step 2: Run the targeted runner tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: fail because the diagnostic runner module and contract do not exist yet.

- [ ] **Step 3: Add minimal dependencies**

Update `pyproject.toml` to add:
- `fastapi`
- `uvicorn`

Then refresh `uv.lock` with:

```bash
uv lock
```

- [ ] **Step 4: Implement the minimal runner dataclasses and request normalization**

In `src/fast_foto_forensics/diagnostic_runner.py`, add:
- one request model for `upload` or `url` image sources
- one result model for the vertically stacked diagnostic view
- one small helper to derive a summary string from `VisionResult`

Keep it small; do not wire real pipeline behavior yet.

- [ ] **Step 5: Re-run the targeted runner tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/fast_foto_forensics/diagnostic_runner.py tests/test_diagnostic_runner.py
git commit -m "feat: add diagnostic runner contracts"
```

## Chunk 2: Real Single-Image Diagnostic Execution

### Task 2: Drive the real vision, query, search, and synthesis stages

**Files:**
- Modify: `src/fast_foto_forensics/diagnostic_runner.py`
- Modify: `tests/test_diagnostic_runner.py`
- Reference: `src/fast_foto_forensics/vision.py`
- Reference: `src/fast_foto_forensics/query_planner.py`
- Reference: `src/fast_foto_forensics/search.py`
- Reference: `src/fast_foto_forensics/synthesis.py`

- [ ] **Step 1: Write failing runner tests for the real stage flow**

Add tests covering:
- successful single-image execution using replay/static backends
- search failure still preserving vision/query artifacts
- synthesis failure still preserving earlier artifacts and failure notes
- live log messages emitted in stage order

- [ ] **Step 2: Run the targeted runner tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: fail because the runner does not yet execute the pipeline stages.

- [ ] **Step 3: Implement the minimal real stage runner**

In `src/fast_foto_forensics/diagnostic_runner.py`:
- normalize one image into one `EvidenceObservation`
- call the real vision backend
- build the real `QueryPlan`
- call the chosen search provider
- call structured datasheet synthesis
- capture raw artifacts plus stage failures
- append human-readable log messages as each stage runs

Do not persist anything permanently in this task.

- [ ] **Step 4: Re-run the targeted runner tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/diagnostic_runner.py tests/test_diagnostic_runner.py
git commit -m "feat: add single-image diagnostic runner"
```

## Chunk 3: Exportable Retry Fixtures

### Task 3: Add explicit export support for retry cases

**Files:**
- Create: `src/fast_foto_forensics/export_fixture.py`
- Modify: `src/fast_foto_forensics/diagnostic_runner.py`
- Modify: `tests/test_diagnostic_runner.py`

- [ ] **Step 1: Write failing tests for export behavior**

Add tests covering:
- exported image copy path creation
- sidecar JSON metadata content
- preservation of source type, original URL, backend/model names, and recorded failures

- [ ] **Step 2: Run the targeted tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: fail because export support does not exist yet.

- [ ] **Step 3: Implement minimal export helpers**

In `src/fast_foto_forensics/export_fixture.py`:
- add helper to choose an export filename
- copy the source image into `artifacts/diagnostic_exports/`
- write adjacent metadata JSON

Wire `src/fast_foto_forensics/diagnostic_runner.py` to call that helper when requested.

- [ ] **Step 4: Re-run the targeted tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_diagnostic_runner.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/export_fixture.py src/fast_foto_forensics/diagnostic_runner.py tests/test_diagnostic_runner.py
git commit -m "feat: add diagnostic export fixtures"
```

## Chunk 4: Web App Surface

### Task 4: Serve the diagnostic page and endpoints

**Files:**
- Create: `src/fast_foto_forensics/web_diagnostic.py`
- Modify: `src/fast_foto_forensics/main.py`
- Modify: `tests/test_web_diagnostic.py`

- [ ] **Step 1: Write failing endpoint tests**

Add tests in `tests/test_web_diagnostic.py` for:
- GET `/` returns the diagnostic page
- POST upload runs a diagnostic and returns structured result JSON
- POST URL runs a diagnostic and returns structured result JSON
- POST export writes a fixture and returns metadata

Use backend mocking or replay/static backends so the tests stay deterministic.

- [ ] **Step 2: Run the targeted endpoint tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_web_diagnostic.py`
Expected: fail because the web app does not exist yet.

- [ ] **Step 3: Implement the minimal FastAPI app**

In `src/fast_foto_forensics/web_diagnostic.py`:
- build one FastAPI app
- serve a plain HTML page with drag-and-drop, URL input, log pane, result sections, and export controls
- add upload, URL, and export endpoints
- keep the frontend as simple inline HTML/CSS/JS unless a separate file becomes clearly necessary

In `src/fast_foto_forensics/main.py`:
- add a launch path such as `fff web-diagnostic`
- start Uvicorn for the app

- [ ] **Step 4: Re-run the targeted endpoint tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_web_diagnostic.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/web_diagnostic.py src/fast_foto_forensics/main.py tests/test_web_diagnostic.py
git commit -m "feat: add diagnostic web UI"
```

## Chunk 5: Integration, Verification, and Operator Docs

### Task 5: Verify the prototype and document how to run it

**Files:**
- Modify: `README.md`
- Modify: `docs/2026-03-16-diagnostic-web-ui-design.md` if implementation details changed
- Verify: full repo test/lint/typecheck suite

- [ ] **Step 1: Add a short README section**

Document:
- how to launch the web prototype
- that it runs the real pipeline
- that `Export` writes retry fixtures into the repo

- [ ] **Step 2: Run the full verification suite**

Run:
- `scripts/uvw.cmd run --extra dev --extra search_ddgs pytest -q`
- `scripts/uvw.cmd run --extra dev ruff check --no-cache src tests`
- `scripts/uvw.cmd run --extra dev ruff format --check src tests`
- `scripts/uvw.cmd run --extra dev mypy src`

Expected: all commands pass.

- [ ] **Step 3: Inspect the prototype output manually**

Launch the app locally and confirm:
- upload works
- URL input works
- stage logs appear in order
- result sections render even on partial failures
- export writes the expected image and sidecar files

- [ ] **Step 4: Commit**

```bash
git add README.md docs/2026-03-16-diagnostic-web-ui-design.md
git commit -m "docs: add diagnostic web ui usage"
```
