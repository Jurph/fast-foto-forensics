# Vision Module Design: Image-In, Text-Out via Ollama + Qwen2.5-VL

> **Status:** Approved design, pending implementation plan
> **Date:** 2026-03-15
> **Related:** `docs/2026-03-14-fast-foto-forensics-phase1-implementation-plan.md`

## Goal

Add a pluggable vision module that extracts structured text and metadata from
evidence images. Given a photo of a piece of equipment, the module returns a
caption, raw OCR text, serial/model numbers, vendor, object class, and detected
labels — all as structured JSON fields that feed downstream into query planning
and web search.

## Architecture Decision

**Approach A: Thin wrapper** — a single `vision.py` module with a `VisionBackend`
protocol and one concrete `OllamaVisionBackend` implementation. This mirrors the
`SearchProvider` protocol pattern already planned for `search.py`.

Alternatives considered:
- **Split package (`vision/`):** Premature — we are still experimenting with prompts
  and don't know where the complexity will land.
- **Extend `ingest.py`:** Breaks modularity. The vision module must be callable both
  as a pipeline stage and standalone.

## Model Choice

**Primary:** Qwen2.5-VL 7B via Ollama (`qwen2.5vl:7b`)
- Instruction-tuned, returns structured JSON from a single prompt
- Pulled via `ollama pull qwen2.5vl:7b` (6.0 GB in Ollama's storage)
- Accessed via `import ollama` / `ollama.chat()`

**Fallback (if Qwen underperforms):** Florence-2-base (Microsoft, 0.23B)
- Weights on `X:\models\fast-foto-forensics\florence-2-base\`
- Would require a separate `Florence2VisionBackend` class and post-processing
  heuristics to produce structured fields from raw OCR output
- Not being built now; the protocol makes it easy to add later

## Module Structure

### New file: `src/fast_foto_forensics/vision.py`

**Protocol:**

```python
class VisionBackend(Protocol):
    def extract(self, image_path: Path) -> VisionResult: ...
```

**Concrete backend:**

```python
class OllamaVisionBackend:
    def __init__(self, model: str = "qwen2.5vl:7b") -> None: ...
    def extract(self, image_path: Path) -> VisionResult: ...
```

- Reads the image file, sends it to Ollama via `ollama.chat()` with a hardcoded
  prompt template requesting JSON output.
- Parses the response into a `VisionResult`.
- On JSON parse failure, retries once. On second failure, raises `VisionExtractionError`
  (defined in `vision.py`, inherits from `RuntimeError`).

**Test backend:**

```python
class StaticVisionBackend:
    def __init__(self, fixtures: dict[str, VisionResult]) -> None: ...
    def extract(self, image_path: Path) -> VisionResult: ...
```

Returns canned `VisionResult` objects keyed by `Path.name` (basename) for
deterministic testing.

**Top-level functions:**

```python
def enrich_observations(
    observations: list[EvidenceObservation],
    backend: VisionBackend,
) -> list[EvidenceObservation]: ...

def enrich_single(
    observation: EvidenceObservation,
    backend: VisionBackend,
) -> EvidenceObservation: ...
```

`enrich_observations()` iterates over observations, calls `backend.extract()` for
each, and maps `VisionResult` fields onto existing `EvidenceObservation` fields.
`enrich_single()` is the standalone entry point for ad-hoc use.

### New dataclass in `src/fast_foto_forensics/models.py`

```python
@dataclass(slots=True)
class VisionResult:
    source_filename: str       # Path.name of the input image
    caption: str
    ocr_text: str
    serial_numbers: list[str]
    vendor: str
    object_class: str
    detected_labels: list[str]

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionResult": ...
```

`source_filename` is always `Path.name` (basename only, e.g. `"001-router.jpg"`).
`to_dict()` and `from_dict()` support JSON cache round-tripping, matching the
pattern used by every other dataclass in `models.py`.

This is the raw output of one vision extraction. The `enrich_*` functions map it
onto `EvidenceObservation` fields:

| VisionResult field   | EvidenceObservation field  |
|----------------------|----------------------------|
| caption              | caption                    |
| ocr_text             | ocr_text                   |
| serial_numbers       | candidate_identifiers      |
| vendor               | detected_labels (appended) |
| object_class         | detected_labels (appended) |
| detected_labels      | detected_labels (merged)   |

**Note on vendor flattening:** `vendor` is intentionally merged into
`detected_labels` rather than given its own field on `EvidenceObservation`. This
means downstream consumers (query planner, tagging) treat vendor the same as any
other label. If a future consumer needs to distinguish vendor from other labels,
`EvidenceObservation` can gain a `vendor` field at that point. For now, flattening
keeps the existing contract unchanged.

## Prompt Template

Hardcoded in `vision.py`. The exact wording will be refined through experimentation
before deployment. Initial shape:

```
Examine this image carefully. Return ONLY a JSON object with these fields:
- "caption": a one-sentence description of what you see
- "ocr_text": all visible text, transcribed exactly as it appears
- "serial_numbers": list of serial numbers, model numbers, or part numbers found
- "vendor": manufacturer name if identifiable, otherwise ""
- "object_class": general category (e.g. "wireless router", "GPU", "circuit board")
- "detected_labels": list of all readable labels, markings, or stickers
```

## Results Caching

Vision inference is expensive (~seconds per image). Results are cached in a single
JSON file per batch rather than per-image sidecars.

**Cache file:** Named `vision_cache.json`, stored in the run's output directory.
When `RunStore` (Phase 1 Task 2) is available, the cache lives under
`store.artifacts_dir`. Before `RunStore` exists, callers pass a cache path
explicitly (or `None` to disable caching).

The cache file contains a JSON object with `source_filename` as keys and
serialized `VisionResult` dicts as values.

**Cache ownership:** The `enrich_observations()` function manages cache reads and
writes. The backend knows nothing about caching.

**Cache behavior:**
- Before extracting, check the cache for an entry matching `Path.name`.
- If found, skip extraction and return the cached result via `VisionResult.from_dict()`.
- If not found, run extraction and write the result to cache via `VisionResult.to_dict()`.
- A `--force-vision` flag (or similar) bypasses the cache. This flag will be wired
  into the CLI when Task 10 of the Phase 1 plan is implemented.

## Error Handling

- **Ollama unavailable:** Hard fail with a clear error message ("Ollama is not
  running or qwen2.5vl:7b is not installed"). Vision was explicitly requested;
  silently skipping it would produce misleading results.
- **Bad JSON from model:** Retry once. If the second attempt also fails to parse,
  raise `VisionExtractionError` with the raw response for debugging.
- **Image file unreadable:** Skip that image with a warning, continue processing
  remaining images.

## Pipeline Integration

The vision module sits between ingestion and query planning:

```
ingest_path()  →  enrich_observations()  →  build_query_plan()
   (files)          (vision/Ollama)           (scoring/ranking)
```

- In the `fff run` pipeline: `enrich_observations()` is called as a free function
  after ingestion, before query planning. The pipeline passes the backend instance
  and optional cache path. This is the canonical calling convention — `pipeline.py`
  calls `enrich_observations(observations, backend)`, not a method on the backend.
- Standalone: `enrich_single()` can be called directly, or a future `fff enrich`
  subcommand can expose it.

**Note on `source_path` types:** `EvidenceObservation.source_path` is `str`.
The `enrich_*` functions convert it to `Path` before calling `backend.extract()`.
This conversion happens inside `vision.py`, not in the caller.

## Dependencies

- `ollama>=0.4.0` (add to `pyproject.toml` dependencies)
- Ollama service running locally with `qwen2.5vl:7b` pulled
- No GPU required (Ollama handles hardware detection and image preprocessing
  including resizing — the module does not need to resize images before sending),
  but a GPU will significantly speed up inference

## Test Strategy

- Unit tests use `StaticVisionBackend` with canned fixtures — no Ollama required.
- One integration test (marked `@pytest.mark.slow` or similar) that actually calls
  Ollama with a small test image, verifying the round-trip works.
- Test the retry-on-bad-JSON path with a backend that returns garbage on first call.
- Test the cache hit/miss logic with a temporary JSON file.

## Files Changed or Created

| File | Action |
|------|--------|
| `src/fast_foto_forensics/vision.py` | Create |
| `src/fast_foto_forensics/models.py` | Add `VisionResult` dataclass |
| `tests/test_vision.py` | Create |
| `pyproject.toml` | Add `ollama` to dependencies |
| `models/MODEL_SOURCES.md` | Update to reflect Ollama as primary delivery mechanism |
