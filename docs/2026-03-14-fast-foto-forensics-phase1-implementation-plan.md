# Fast Foto Forensics Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first evidence-analysis CLI that can ingest images and scanned documents, derive reusable tags and ranked web queries, synthesize structured JSON datasheets, and render a human-readable dossier.

**Architecture:** Keep the Phase 1 implementation file-based and testable. Use dataclass-based contracts, a small SQLite-backed run store for queue state, pluggable backends for vision/search/synthesis, and deterministic query planning plus clustering before any LLM synthesis step.

**Tech Stack:** Python 3.11, `uv`, `pytest`, `ruff`, `mypy`, stdlib `sqlite3`, stdlib `argparse`, stdlib `json`, `httpx[socks]` if/when live search is wired, repo-local `scripts/uvw.cmd` for Windows-safe uv workflows.

---

## File Map

- Existing foundation:
  - `src/fast_foto_forensics/models.py` for shared contracts
  - `src/fast_foto_forensics/query_planner.py` for deterministic ranked query generation
  - `src/fast_foto_forensics/tagging.py` for sidecar tag synthesis
  - `src/fast_foto_forensics/main.py` for CLI entrypoint
- Planned additions:
  - `src/fast_foto_forensics/storage.py` for run directories, JSON artifacts, and SQLite queue access
  - `src/fast_foto_forensics/ingest.py` for file discovery, hashing, and normalized observations
  - `src/fast_foto_forensics/clustering.py` for folder/order/token grouping
  - `src/fast_foto_forensics/search.py` for provider interfaces and normalized hits
  - `src/fast_foto_forensics/synthesis.py` for JSON-only datasheet generation and validation/retry
  - `src/fast_foto_forensics/reporting.py` for Markdown dossier rendering
  - `src/fast_foto_forensics/pipeline.py` for end-to-end orchestration
  - `src/fast_foto_forensics/cli.py` for subcommand parsing and handler dispatch
- Planned tests:
  - `tests/test_ingest.py`
  - `tests/test_clustering.py`
  - `tests/test_search.py`
  - `tests/test_synthesis.py`
  - `tests/test_reporting.py`
  - `tests/test_pipeline.py`
  - `tests/test_cli.py`

## Chunk 1: Contracts and Storage

### Task 1: Finalize core contracts

**Files:**
- Modify: `src/fast_foto_forensics/models.py`
- Test: `tests/test_models.py`

- [x] **Step 1: Write failing contract tests**

```python
def test_item_datasheet_from_json_requires_core_fields() -> None:
    with pytest.raises(ValueError, match="probable_identity"):
        ItemDatasheet.from_json('{"object_class": "gpu"}')
```

- [x] **Step 2: Run tests to verify the module is missing or incomplete**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_models.py tests\test_query_planner.py`
Expected: FAIL with `ModuleNotFoundError` or validation errors.

- [x] **Step 3: Implement minimal contracts**

```python
@dataclass(slots=True)
class ItemDatasheet:
    probable_identity: str
    object_class: str
    likely_function: str
    manufacturer: str
    model_identifiers: list[str]

    @classmethod
    def from_json(cls, raw_payload: str) -> "ItemDatasheet":
        data = json.loads(raw_payload)
        ...
```

- [x] **Step 4: Re-run the focused tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_models.py tests\test_query_planner.py`
Expected: PASS for the current contract/query tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_models.py tests/test_query_planner.py src/fast_foto_forensics/models.py src/fast_foto_forensics/query_planner.py src/fast_foto_forensics/tagging.py
git commit -m "feat: add core evidence models and query planning"
```

### Task 2: Add run storage and queue state

**Files:**
- Create: `src/fast_foto_forensics/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

```python
def test_run_store_initializes_sqlite_and_artifact_paths(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, run_label="demo")
    assert store.database_path.exists()
    assert store.artifacts_dir.exists()
```

- [ ] **Step 2: Run the focused storage test**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_storage.py`
Expected: FAIL with `ModuleNotFoundError: fast_foto_forensics.storage`.

- [ ] **Step 3: Implement `RunStore`**

```python
class RunStore:
    @classmethod
    def create(cls, output_root: Path, run_label: str) -> "RunStore":
        run_dir = output_root / run_label
        ...
```

- [ ] **Step 4: Re-run storage tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_storage.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_storage.py src/fast_foto_forensics/storage.py
git commit -m "feat: add run storage and queue state"
```

## Chunk 2: Ingest, Tagging, and Queryable Evidence

### Task 3: Build ingestion and hashing

**Files:**
- Create: `src/fast_foto_forensics/ingest.py`
- Modify: `src/fast_foto_forensics/models.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Write failing ingest tests**

```python
def test_ingest_directory_creates_ordered_observations(tmp_path: Path) -> None:
    ...
    observations = ingest_path(input_dir)
    assert [item.source_path.name for item in observations] == ["001-router.jpg", "002-gpu.jpg"]
```

- [ ] **Step 2: Run ingest tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_ingest.py`
Expected: FAIL because `ingest_path` does not exist.

- [ ] **Step 3: Implement ingestion**

```python
def ingest_path(input_path: Path) -> list[EvidenceObservation]:
    paths = sorted(discover_supported_files(input_path))
    return [build_observation(path, order_index=i) for i, path in enumerate(paths)]
```

- [ ] **Step 4: Re-run ingest tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_ingest.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ingest.py src/fast_foto_forensics/ingest.py src/fast_foto_forensics/models.py
git commit -m "feat: add evidence ingestion and hashing"
```

### Task 4: Persist sidecar tags for later reuse

**Files:**
- Modify: `src/fast_foto_forensics/tagging.py`
- Create: `tests/test_tagging_sidecars.py`

- [ ] **Step 1: Write failing sidecar tests**

```python
def test_write_tag_sidecar_uses_json_and_does_not_touch_original(tmp_path: Path) -> None:
    sidecar_path = write_tag_sidecar(image_path, tag_set)
    assert sidecar_path.name.endswith(".fff-tags.json")
    assert image_path.read_bytes() == b"image-bytes"
```

- [ ] **Step 2: Run the sidecar test**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_tagging_sidecars.py`
Expected: FAIL because `write_tag_sidecar` does not exist.

- [ ] **Step 3: Implement sidecar writing**

```python
def write_tag_sidecar(source_path: Path, tag_set: ImageTagSet) -> Path:
    sidecar_path = source_path.with_suffix(source_path.suffix + ".fff-tags.json")
    ...
```

- [ ] **Step 4: Re-run the sidecar test**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_tagging_sidecars.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tagging_sidecars.py src/fast_foto_forensics/tagging.py
git commit -m "feat: add reusable image sidecar tags"
```

### Task 5: Cluster related evidence before search and synthesis

**Files:**
- Create: `src/fast_foto_forensics/clustering.py`
- Test: `tests/test_clustering.py`

- [ ] **Step 1: Write failing clustering tests**

```python
def test_cluster_observations_groups_adjacent_shared_identifier_images() -> None:
    clusters = cluster_observations(observations)
    assert len(clusters) == 1
    assert clusters[0].evidence_refs == ["img-1", "img-2"]
```

- [ ] **Step 2: Run clustering tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_clustering.py`
Expected: FAIL because `cluster_observations` does not exist.

- [ ] **Step 3: Implement simple grouping**

```python
def cluster_observations(observations: list[EvidenceObservation]) -> list[EvidenceCluster]:
    # Group by parent folder first, then merge adjacent items sharing identifiers or labels.
    ...
```

- [ ] **Step 4: Re-run clustering tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_clustering.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_clustering.py src/fast_foto_forensics/clustering.py
git commit -m "feat: add simple evidence clustering"
```

## Chunk 3: Search, Synthesis, and Reporting

### Task 6: Add normalized search provider support

**Files:**
- Create: `src/fast_foto_forensics/search.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Write failing search tests**

```python
def test_static_search_provider_normalizes_hits() -> None:
    provider = StaticSearchProvider(fixtures={...})
    hits = provider.search("WRT54G release date")
    assert hits[0].provider == "static"
```

- [ ] **Step 2: Run search tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_search.py`
Expected: FAIL because search provider code does not exist.

- [ ] **Step 3: Implement provider interfaces**

```python
class SearchProvider(Protocol):
    def search(self, query: str) -> list[SearchHit]:
        ...
```

- [ ] **Step 4: Add live provider plumbing only after static tests pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_search.py`
Expected: PASS for static/provider-shape tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_search.py src/fast_foto_forensics/search.py
git commit -m "feat: add normalized search provider interface"
```

### Task 7: Implement schema-first synthesis with validation and retry

**Files:**
- Create: `src/fast_foto_forensics/synthesis.py`
- Create: `tests/test_synthesis.py`

- [ ] **Step 1: Write failing synthesis tests**

```python
def test_json_synthesis_retries_when_first_payload_is_invalid() -> None:
    backend = ReplaySynthesisBackend(["not json", valid_json])
    result = synthesize_item(bundle, backend)
    assert result.probable_identity == "Linksys WRT54G"
```

- [ ] **Step 2: Run synthesis tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_synthesis.py`
Expected: FAIL because synthesis code does not exist.

- [ ] **Step 3: Implement synthesis orchestration**

```python
def synthesize_item(bundle: SearchEvidenceBundle, backend: SynthesisBackend) -> ItemDatasheet:
    raw = backend.generate_datasheet(bundle)
    try:
        return ItemDatasheet.from_json(raw)
    except ValueError:
        repaired = backend.repair_datasheet(raw, bundle)
        return ItemDatasheet.from_json(repaired)
```

- [ ] **Step 4: Re-run synthesis tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_synthesis.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_synthesis.py src/fast_foto_forensics/synthesis.py
git commit -m "feat: add schema-first synthesis"
```

### Task 8: Render Markdown dossiers and compose summaries

**Files:**
- Create: `src/fast_foto_forensics/reporting.py`
- Create: `tests/test_reporting.py`

- [ ] **Step 1: Write failing reporting tests**

```python
def test_render_dossier_includes_identity_queries_and_sources() -> None:
    markdown = render_item_dossier(datasheet, hits, observations)
    assert "## Probable Identity" in markdown
    assert "WRT54G" in markdown
    assert "https://example.com" in markdown
```

- [ ] **Step 2: Run reporting tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_reporting.py`
Expected: FAIL because rendering code does not exist.

- [ ] **Step 3: Implement report rendering**

```python
def render_item_dossier(...) -> str:
    return "\\n".join([...])
```

- [ ] **Step 4: Re-run reporting tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_reporting.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_reporting.py src/fast_foto_forensics/reporting.py
git commit -m "feat: add markdown dossier rendering"
```

## Chunk 4: Pipeline and CLI

### Task 9: Wire the pipeline end to end

**Files:**
- Create: `src/fast_foto_forensics/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

```python
def test_run_pipeline_creates_artifacts_report_and_sidecars(tmp_path: Path) -> None:
    run_result = run_pipeline(...)
    assert run_result.report_path.exists()
    assert run_result.sidecar_paths
```

- [ ] **Step 2: Run pipeline tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_pipeline.py`
Expected: FAIL because pipeline code does not exist.

- [ ] **Step 3: Implement orchestration**

```python
def run_pipeline(...) -> RunResult:
    observations = ingest_path(input_path)
    clusters = cluster_observations(observations)
    query_plan = build_query_plan(observations)
    ...
```

- [ ] **Step 4: Re-run pipeline tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_pipeline.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline.py src/fast_foto_forensics/pipeline.py
git commit -m "feat: add end-to-end evidence pipeline"
```

### Task 10: Expose the operator CLI as `fff`

**Files:**
- Create: `src/fast_foto_forensics/cli.py`
- Modify: `src/fast_foto_forensics/main.py`
- Modify: `pyproject.toml`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_run_command_creates_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exit_code = main(["run", str(input_dir), "--output", str(tmp_path)])
    assert exit_code == 0
```

- [ ] **Step 2: Run CLI tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_cli.py`
Expected: FAIL because subcommands do not exist.

- [ ] **Step 3: Implement argparse-based CLI**

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fff")
    ...
```

- [ ] **Step 4: Re-run CLI tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_cli.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py src/fast_foto_forensics/cli.py src/fast_foto_forensics/main.py pyproject.toml
git commit -m "feat: add fff command-line interface"
```

## Final Verification

- [ ] **Step 1: Run the focused feature suites**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_models.py tests\test_query_planner.py tests\test_ingest.py tests\test_clustering.py tests\test_search.py tests\test_synthesis.py tests\test_reporting.py tests\test_pipeline.py tests\test_cli.py
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run Ruff**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev ruff check --no-cache .
```

Expected: PASS.

- [ ] **Step 3: Run mypy**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev mypy src
```

Expected: PASS.

- [ ] **Step 4: Update user-facing docs**

Files:
- Modify: `README.md`
- Modify: `notes/project-brief.md`

Document:
- `fff` commands
- sidecar tag behavior
- offline vs live search/synthesis modes
- the current placeholder/default backend story for local development

- [ ] **Step 5: Commit final documentation pass**

```bash
git add README.md notes/project-brief.md docs/2026-03-14-fast-foto-forensics-phase1-implementation-plan.md
git commit -m "docs: add phase 1 implementation plan and usage notes"
```
