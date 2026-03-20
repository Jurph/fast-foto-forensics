# Vision Module Design: Image-In, Text-Out via Ollama + Qwen2.5-VL

> **Status:** Implemented. This document describes the current `vision.py`
> module.
> **Date:** 2026-03-15
> **Related:** `docs/2026-03-14-fast-foto-forensics-phase1-implementation-plan.md`

## Summary

`src/fast_foto_forensics/vision.py` contains the vision backend protocol, the
concrete backends used by the repo, and the helpers that map `VisionResult`
data back onto `EvidenceObservation`.

The current code supports:

- `FilenameVisionBackend`
  - default CLI vision backend
  - derives labels and candidate identifiers from filename tokens only
- `OllamaVisionBackend`
  - local model-backed extraction via `ollama.chat()`
- `StaticVisionBackend`
  - deterministic fixture backend for tests
- `extract_with_cache()`
  - reads and writes per-observation `vision/<evidence_id>.json` artifacts
- `enrich_single()` / `enrich_observations()`
  - copy structured `VisionResult` fields back onto observations in place

The module is intentionally small and matches the protocol-driven shape already
used by `search.py` and `synthesis.py`.

## Model Choice

**Primary:** Qwen2.5-VL 7B via Ollama (`qwen2.5vl:7b`)
- Instruction-tuned, returns structured JSON from a single prompt
- Pulled via `ollama pull qwen2.5vl:7b`
- Accessed via `import ollama` / `ollama.chat()`

**Reference alternative:** Florence-2-base
- Weights on `X:\models\fast-foto-forensics\florence-2-base\`
- Would require a separate `Florence2VisionBackend` class and post-processing
  heuristics to produce structured fields from raw OCR output
- The tracked CLI does not use this backend today

## Current Module Structure

### `src/fast_foto_forensics/vision.py`

**Protocol:**

```python
class VisionBackend(Protocol):
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

**Model-backed backend:**

```python
class OllamaVisionBackend:
    def __init__(self, model: str = "qwen2.5vl:7b") -> None: ...
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

- Reads the image file and sends it to Ollama as base64 image content
- Uses a shared prompt constant in `vision.py`
- Parses the response into a `VisionResult`
- Retries once on JSON parse failure
- Raises `VisionExtractionError` if the image is missing, the `ollama` package
  is missing, or the model returns invalid JSON twice

**Filename fallback backend:**

```python
class FilenameVisionBackend:
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

- Splits filename stems on `_` and `-`
- Treats alphanumeric tokens as candidate identifiers
- Treats alphabetic tokens as labels and caption text
- Leaves `vendor` and `object_class` empty

**Test backend:**

```python
class StaticVisionBackend:
    def __init__(self, fixtures: dict[str, VisionResult]) -> None: ...
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...
```

Returns canned `VisionResult` objects keyed by `observation.evidence_id` for
deterministic testing. This avoids basename collisions across folders.

**Top-level helpers:**

```python
def extract_with_cache(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: RunStore,
) -> VisionResult: ...

def enrich_observations(
    observations: list[EvidenceObservation],
    backend: VisionBackend,
    store: RunStore | None = None,
) -> list[EvidenceObservation]: ...

def enrich_single(
    observation: EvidenceObservation,
    result: VisionResult,
) -> EvidenceObservation: ...
```

`extract_with_cache()` owns the per-observation cache. `enrich_observations()`
iterates over observations, calls `extract_with_cache()` or `backend.extract()`
for each, and maps `VisionResult` fields onto existing `EvidenceObservation`
objects. `enrich_single()` is the field-mapping helper.

### `src/fast_foto_forensics/models.py`

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
    serial_numbers: list[str]
    vendor: str | None
    object_class: str | None
    detected_labels: list[str]
```

This is the raw output of one vision extraction. The enrichment helpers map it
onto `EvidenceObservation` fields as follows:

| VisionResult field    | EvidenceObservation field  |
|-----------------------|----------------------------|
| caption               | caption                    |
| ocr_text              | ocr_text                   |
| candidate_identifiers | candidate_identifiers      |
| serial_numbers        | serial_numbers             |
| vendor                | vendor                     |
| object_class          | object_class               |
| detected_labels       | detected_labels            |

The structured fields remain on both the persisted `VisionResult` artifact and
the enriched `EvidenceObservation`.

## Prompt Shape

`vision.py` stores a prompt constant that asks for a JSON object with:

```text
Examine this image carefully. Return ONLY a JSON object with these fields:
- "caption": a one-sentence description of what you see
- "ocr_text": all visible text, transcribed exactly as it appears
- "candidate_identifiers": list of model numbers or part numbers
- "serial_numbers": list of serial numbers, MAC addresses, or unique IDs
- "vendor": manufacturer name if identifiable, otherwise ""
- "object_class": general category
- "detected_labels": list of readable labels, markings, or stickers
```

## Results Caching

Vision inference is expensive. Results are cached as per-observation artifacts
rather than in a single mutable batch file.

**Artifact path:** `store.artifact_path(f"vision/{observation.evidence_id}.json")`

**Cache behavior:**
- Before extracting, check whether the per-observation artifact exists
- If it exists, load it via `VisionResult.from_dict()`
- Reuse it only if `source_sha256` still matches the current observation
- If it does not exist, or the checksum differs, run extraction and
  write the fresh result via `VisionResult.to_dict()`

## Error Handling

- **Ollama unavailable:** `OllamaVisionBackend.extract()` raises
  `VisionExtractionError`.
- **Bad JSON from model:** Retry once. If the second attempt also fails to
  parse, raise `VisionExtractionError`.
- **Batch orchestration:** `enrich_observations()` catches per-observation
  failures, logs a warning, and leaves the failing observation unenriched so the
  rest of the batch can continue.
- **CLI scan path:** `scan` catches extraction failures per file, warns, and
  skips those rows. If every image fails extraction, the command ends with
  `No supported images found.`

## Pipeline Integration

The vision module sits between ingestion and query planning:

```text
ingest_path()  ->  enrich_observations()  ->  build_query_plan()
   (files)          (vision)                  (scoring/ranking)
```

- In the `fff run` pipeline, `enrich_observations()` is called after ingestion
  and before query planning. The pipeline passes the backend instance and the
  current `RunStore`.
- `scan` calls the selected backend directly so it can show raw `VisionResult`
  fields such as `vendor`, `object_class`, and `serial_numbers`.
- There is no standalone `fff enrich` command today.

## Dependencies

- `ollama>=0.4.0` as an optional extra such as `vision_ollama`, not a required
  base dependency
- Ollama service running locally with `qwen2.5vl:7b` pulled
- No GPU required, but a GPU will significantly speed up inference

## Test Strategy

- Unit tests use `StaticVisionBackend` with canned fixtures
- Slow integration coverage exercises Ollama against real test images
- Cache behavior is tested with temporary run stores
- Batch enrichment tests cover the warning-and-continue failure mode

## Current Limitations

- The default CLI vision backend is still filename-based for low-friction local
  runs.
- The model-backed path depends on the optional `vision_ollama` extra and a
  running local Ollama service.
- The current module does not perform region-level OCR or object detection.
