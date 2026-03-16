# Synthesis MVP Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace heuristic datasheet synthesis with a real Ollama-backed structured-output backend, add a remote-backend stub, and persist synthesis provenance artifacts without colliding with ongoing CLI work.

**Architecture:** Keep `ItemDatasheet` as the accepted final contract, add backend/provenance handling in `synthesis.py`, and persist a separate `synthesis.json` artifact beside the clean datasheet. Use Ollama schema mode as the primary structure enforcement mechanism and keep retries bounded to guardrail-level validation only.

**Tech Stack:** Python 3.11, `ollama` optional dependency, existing `RunStore` JSON artifacts, `pytest`, `ruff`, `mypy`, `uv`

---

## Chunk 1: Baseline and Data Contracts

### Task 1: Restore a green locked baseline in the synthesis worktree

**Files:**
- Modify: `uv.lock`
- Verify: `scripts/uvw.cmd`, existing test suite

- [ ] **Step 1: Confirm the current lockfile failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q`
Expected: failure complaining that `uv.lock` needs update while `--locked` is provided.

- [ ] **Step 2: Refresh the lockfile**

Run: `uv lock`
Expected: `uv.lock` updates cleanly in the worktree.

- [ ] **Step 3: Verify the baseline test suite**

Run: `scripts/uvw.cmd run --extra dev pytest -q`
Expected: baseline tests pass in the worktree after the lock refresh.

- [ ] **Step 4: Commit the lockfile-only baseline fix**

```bash
git add uv.lock
git commit -m "build: refresh lockfile for synthesis worktree"
```

### Task 2: Add synthesis provenance model tests first

**Files:**
- Modify: `tests/test_models.py`
- Modify: `src/fast_foto_forensics/models.py`

- [ ] **Step 1: Write failing tests for a synthesis provenance record**

Add tests covering a JSON-friendly synthesis artifact record with:
- backend/model/schema names
- raw payload
- accepted flag
- attempt count
- last error

- [ ] **Step 2: Run the targeted model tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_models.py`
Expected: failure because the new synthesis provenance type does not exist yet.

- [ ] **Step 3: Implement the minimal provenance dataclass**

Add a compact dataclass in `src/fast_foto_forensics/models.py` with `to_dict()` / `from_dict()` support.

- [ ] **Step 4: Re-run the targeted model tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_models.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/models.py tests/test_models.py
git commit -m "feat: add synthesis artifact model"
```

## Chunk 2: Structured Synthesis Backends

### Task 3: Add Ollama structured-output synthesis tests

**Files:**
- Modify: `tests/test_synthesis.py`
- Reference: `src/fast_foto_forensics/synthesis.py`

- [ ] **Step 1: Write failing tests for Ollama datasheet synthesis**

Add tests covering:
- schema-mode request construction
- valid structured response returns a valid `ItemDatasheet`
- invalid/missing-field response is rejected
- raw payload and metadata can be captured for provenance

- [ ] **Step 2: Run the targeted synthesis tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_synthesis.py`
Expected: failure because the Ollama datasheet backend does not exist yet.

- [ ] **Step 3: Implement minimal Ollama structured-output backend**

In `src/fast_foto_forensics/synthesis.py`:
- add a small prompt/request builder
- add `OllamaDatasheetSynthesisBackend`
- call Ollama schema mode directly
- keep validation at the boundary via `ItemDatasheet.from_json()`

- [ ] **Step 4: Re-run the targeted synthesis tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_synthesis.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/synthesis.py tests/test_synthesis.py
git commit -m "feat: add ollama datasheet synthesis backend"
```

### Task 4: Add the remote synthesis stub behind the same interface

**Files:**
- Modify: `tests/test_synthesis.py`
- Modify: `src/fast_foto_forensics/synthesis.py`

- [ ] **Step 1: Write a failing test for the remote backend stub**

Test that the remote backend is constructible and raises a clear actionable error when used.

- [ ] **Step 2: Run the targeted synthesis test**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_synthesis.py -k remote`
Expected: failure because the stub does not exist yet.

- [ ] **Step 3: Implement the remote backend stub**

Add `RemoteDatasheetSynthesisBackend` that satisfies `SynthesisBackend` and fails fast with a not-yet-configured error.

- [ ] **Step 4: Re-run the targeted synthesis tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_synthesis.py -k remote`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/synthesis.py tests/test_synthesis.py
git commit -m "feat: add remote synthesis backend stub"
```

## Chunk 3: Pipeline Persistence and Wiring

### Task 5: Persist `synthesis.json` artifacts from the pipeline

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `src/fast_foto_forensics/pipeline.py`
- Modify: `src/fast_foto_forensics/synthesis.py`

- [ ] **Step 1: Write failing pipeline tests for synthesis provenance artifacts**

Add tests asserting that a run writes:
- `clusters/<cluster_id>/datasheet.json`
- `clusters/<cluster_id>/synthesis.json`

and that `synthesis.json` includes backend/model/raw-payload metadata.

- [ ] **Step 2: Run the targeted pipeline tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_pipeline.py`
Expected: failure because `synthesis.json` is not written yet.

- [ ] **Step 3: Implement minimal pipeline persistence**

Update the synthesis flow so the acceptance gate returns both:
- validated `ItemDatasheet`
- provenance artifact metadata

Persist both artifacts from `pipeline.py`.

- [ ] **Step 4: Re-run the targeted pipeline tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_pipeline.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/pipeline.py src/fast_foto_forensics/synthesis.py tests/test_pipeline.py
git commit -m "feat: persist synthesis provenance artifacts"
```

### Task 6: Make the active run path use local Ollama synthesis

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/fast_foto_forensics/cli.py`
- Modify: `src/fast_foto_forensics/synthesis.py`

- [ ] **Step 1: Write failing CLI tests for the local synthesis path**

Add tests that `fff run` selects the real local synthesis backend by default, using transport mocking so no live Ollama service is required.

- [ ] **Step 2: Run the targeted CLI tests to verify failure**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_cli.py`
Expected: failure because the CLI still wires `HeuristicSynthesisBackend`.

- [ ] **Step 3: Implement the minimal CLI wiring**

Replace the heuristic backend in the run path with the local Ollama synthesis backend, keeping the wiring small and avoiding overlap with unrelated CLI output work.

- [ ] **Step 4: Re-run the targeted CLI tests**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_cli.py`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/cli.py src/fast_foto_forensics/synthesis.py tests/test_cli.py
git commit -m "feat: wire local synthesis backend into fff run"
```

## Chunk 4: Full Verification and Ticket Alignment

### Task 7: Verify the whole synthesis slice and update issue scope

**Files:**
- Modify: GitHub issues `#13`, `#34`, `#35` as needed after implementation
- Verify: full repo test/lint/typecheck suite

- [ ] **Step 1: Run the full verification suite**

Run:
- `scripts/uvw.cmd run --extra dev pytest -q`
- `scripts/uvw.cmd run --extra dev ruff check --no-cache src tests`
- `scripts/uvw.cmd run --extra dev ruff format --check src tests`
- `scripts/uvw.cmd run --extra dev mypy src`

Expected: all commands pass.

- [ ] **Step 2: Inspect the diff and artifact behavior**

Verify that no unrelated files were touched and that the synthesis artifacts reflect the approved design.

- [ ] **Step 3: Update GitHub issue bodies/states**

Align:
- `#34` with completed Ollama structured-output work
- `#35` with the implemented remote stub scope
- `#13` if its checklist or definition of done needs to reflect the local-first MVP

- [ ] **Step 4: Commit any final ticket-alignment or polish changes**

```bash
git add <files-if-any>
git commit -m "chore: finalize synthesis mvp wiring"
```
