# Vision Module Design: Image-In, Text-Out via Ollama + Qwen2.5-VL

> **Status:** Approved design, revised after architecture review
> **Date:** 2026-03-15
> **Related:** `docs/2026-03-14-fast-foto-forensics-phase1-implementation-plan.md`

## Goal

Add a pluggable vision module that extracts structured text and metadata from
evidence images. Given a photo of a piece of equipment, the module returns a
caption, raw OCR text, candidate identifiers, vendor, object class, and
detected labels as structured JSON fields that feed downstream into query
planning and web search.

## Architecture Decision

**Approach A: Thin wrapper** - a single `vision.py` module with a `VisionBackend`
protocol and one concrete `OllamaVisionBackend` implementation. This mirrors the
small-protocol pattern already used by `search.py` and `synthesis.py`, while
preserving the repo's schema-first philosophy by persisting raw `VisionResult`
artifacts per observation.

Alternatives considered:
- **Split package (`vision/`):** Premature - we are still experimenting with
  prompts and do not yet know where the complexity will land.
- **Extend `ingest.py`:** Breaks modularity. The vision module must be callable
  both as a pipeline stage and standalone.
- **Mutate observations directly inside the backend:** Too much coupling. The
  backend should return a structured result; enrichment and persistence belong
  in `vision.py` orchestration helpers.

## Model Choice

**Primary:** Qwen2.5-VL 7B via Ollama (`qwen2.5vl:7b`)
- Instruction-tuned, returns structured JSON from a single prompt
- Pulled via `ollama pull qwen2.5vl:7b`
- Accessed via `import ollama` / `ollama.chat()`

**Fallback (if Qwen underperforms):** Florence-2-base
- Weights on `X:\models\fast-foto-forensics\florence-2-base\`
- Would require a separate `Florence2VisionBackend` class and post-processing
  heuristics to produce structured fields from raw OCR output
- Not being built now; the protocol makes it easy to add later

## Module Structure

### New file: `src/fast_foto_forensics/vision.py`

**Protocol:**

```python
class VisionBackend(Protocol):
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

This keeps the backend aligned with the repo's normalized evidence model rather
than pushing the interface back down to bare filesystem paths.

**Concrete backend:**

```python
class OllamaVisionBackend:
    def __init__(self, model: str = "qwen2.5vl:7b") -> None: ...
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

- Converts `observation.source_path` to `Path`, reads the image file, and sends
  it to Ollama via `ollama.chat()`
- Uses a named prompt constant or small prompt-builder helper in `vision.py`
- Parses the response into a `VisionResult`
- On JSON parse failure, retries once
- On second failure, raises `VisionExtractionError` (defined in `vision.py`,
  inherits from `RuntimeError`)

**Existing lightweight backend retained:**

```python
class FilenameVisionBackend:
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

The current filename heuristic backend should move from `pipeline.py` into
`vision.py` and implement the same protocol. That keeps tests and low-friction
local runs fast while aligning all vision backends behind one contract.

**Test backend:**

```python
class StaticVisionBackend:
    def __init__(self, fixtures: dict[str, VisionResult]) -> None: ...
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

Returns canned `VisionResult` objects keyed by `observation.evidence_id` for
deterministic testing. This avoids basename collisions across folders.

**Top-level functions:**

```python
def extract_with_cache(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> VisionResult: ...

def enrich_observations(
    observations: list[EvidenceObservation],
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> tuple[list[EvidenceObservation], list[VisionResult]]: ...

def enrich_single(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> tuple[EvidenceObservation, VisionResult]: ...
```

`extract_with_cache()` is the cache boundary and cache owner.
`enrich_observations()` iterates over observations, calls
`extract_with_cache()` for each, and maps `VisionResult` fields onto existing
`EvidenceObservation` fields. `enrich_single()` is the standalone entry point
for ad-hoc use.

### New dataclass in `src/fast_foto_forensics/models.py`

```python
@dataclass(slots=True)
class VisionResult:
    evidence_id: str
    source_path: str
    source_sha256: str
    backend_name: str
    model_name: str
    caption: str
    ocr_text: str
    candidate_identifiers: list[str]
    vendor: str | None
    object_class: str | None
    detected_labels: list[str]

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionResult": ...
```

`to_dict()` and `from_dict()` support JSON artifact round-tripping, matching the
pattern used by every other dataclass in `models.py`. `evidence_id` is the
primary per-run identity, and `source_sha256` protects against stale cache
reuse.

This is the raw output of one vision extraction. The `enrich_*` functions map it
onto `EvidenceObservation` fields:

| VisionResult field    | EvidenceObservation field  |
|-----------------------|----------------------------|
| caption               | caption                    |
| ocr_text              | ocr_text                   |
| candidate_identifiers | candidate_identifiers      |
| vendor                | detected_labels (appended) |
| object_class          | detected_labels (appended) |
| detected_labels       | detected_labels (merged)   |

**Note on structured preservation:** `vendor` and `object_class` are appended
into `detected_labels` only as a compatibility layer for today's downstream
consumers. The authoritative structured values remain in the persisted
`VisionResult` artifact. That keeps the current `EvidenceObservation` contract
stable without discarding semantics too early.

## Prompt Template

Stored in `vision.py` as a named constant or small prompt-builder helper. The
exact wording will be refined through experimentation before deployment.
Initial shape:

```text
Examine this image carefully. Return ONLY a JSON object with these fields:
- "caption": a one-sentence description of what you see
- "ocr_text": all visible text, transcribed exactly as it appears
- "candidate_identifiers": list of serial numbers, model numbers, or part numbers found
- "vendor": manufacturer name if identifiable, otherwise ""
- "object_class": general category (e.g. "wireless router", "GPU", "circuit board")
- "detected_labels": list of all readable labels, markings, or stickers
```

## Results Caching

Vision inference is expensive. Results should be cached as per-observation
artifacts rather than in a single mutable batch file.

**Artifact path:** `store.artifact_path(f"vision/{observation.evidence_id}.json")`

**Cache ownership:** `extract_with_cache()` manages cache reads and writes. The
backend knows nothing about caching.

**Cache behavior:**
- Before extracting, check whether the per-observation artifact exists
- If it exists, load it via `VisionResult.from_dict()`
- Reuse it only if `source_sha256`, `backend_name`, and `model_name` still match
  the current observation/backend configuration
- If it does not exist, or the metadata no longer matches, run extraction and
  write the fresh result via `VisionResult.to_dict()`
- A `--force-vision` flag (or similar) bypasses artifact reuse

This matches the repo's existing `RunStore` artifact model and keeps future
multi-worker vision queues from contending on one shared JSON file.

## Error Handling

- **Ollama unavailable:** Hard fail with a clear error message ("Ollama is not
  running or qwen2.5vl:7b is not installed"). Vision was explicitly requested;
  silently skipping it would produce misleading results.
- **Bad JSON from model:** Retry once. If the second attempt also fails to
  parse, raise `VisionExtractionError` with the raw response for debugging.
- **Image file unreadable:** Skip that image with a warning and continue
  processing remaining images.

## Pipeline Integration

The vision module sits between ingestion and query planning:

```text
ingest_path()  ->  enrich_observations()  ->  build_query_plan()
   (files)          (vision/Ollama)           (scoring/ranking)
```

- In the `fff run` pipeline: `enrich_observations()` is called as a free
  function after ingestion and before query planning. The pipeline passes the
  backend instance and the current `RunStore`.
- The pipeline should stop depending on a backend-specific `.enrich()` method in
  `pipeline.py`. Instead, all backends implement `VisionBackend.extract(...)`
  and `vision.py` owns the mapping step.
- Standalone: `enrich_single()` can be called directly, or a future `fff enrich`
  subcommand can expose it.

**Note on `source_path` types:** `EvidenceObservation.source_path` is `str`.
`vision.py` converts it to `Path` inside the module before reading the image.

## Dependencies

- `ollama>=0.4.0` as an optional extra such as `vision_ollama`, not a required
  base dependency
- Ollama service running locally with `qwen2.5vl:7b` pulled
- No GPU required (Ollama handles hardware detection and image preprocessing
  including resizing), but a GPU will significantly speed up inference

## Test Strategy

- Unit tests use `StaticVisionBackend` with canned fixtures - no Ollama required
- One integration test (marked `@pytest.mark.slow` or similar) that actually
  calls Ollama with a small test image, verifying the round-trip works
- Test the retry-on-bad-JSON path with a backend that returns garbage on first call
- Test the cache hit/miss logic with a temporary `RunStore` artifact path
- Test basename collision safety explicitly with two different source paths
  sharing the same filename

## Files Changed or Created

| File | Action |
|------|--------|
| `src/fast_foto_forensics/vision.py` | Create |
| `src/fast_foto_forensics/models.py` | Add `VisionResult` dataclass |
| `src/fast_foto_forensics/pipeline.py` | Replace direct filename heuristics with `vision.py` orchestration |
| `tests/test_vision.py` | Create |
| `tests/test_pipeline.py` | Update to cover vision-backend integration |
| `pyproject.toml` | Add optional Ollama extra |
| `models/MODEL_SOURCES.md` | Update to reflect Ollama as primary delivery mechanism |
