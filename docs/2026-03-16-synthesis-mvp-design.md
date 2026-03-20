# Synthesis MVP Design

> **Status:** Implemented. This document describes the current synthesis module
> and artifact flow.

## Summary

`src/fast_foto_forensics/synthesis.py` contains three concrete backends and the
validation/provenance flow used by the pipeline:

- `HeuristicSynthesisBackend`
  - explicit low-confidence fallback for no-model runs
- `OllamaDatasheetSynthesisBackend`
  - local structured-output backend via `ollama.chat(..., format=schema)`
- `RemoteDatasheetSynthesisBackend`
  - OpenAI-compatible remote backend using chat completions plus JSON schema

`fff run` defaults to the Ollama synthesis backend. The heuristic backend is
still available as an explicit fallback, and the remote backend is an active
implementation rather than a stub.

## Current State

The current pipeline already has:

- real vision backends in `src/fast_foto_forensics/vision.py`
- real search backends in `src/fast_foto_forensics/search.py`
- per-cluster query plans and hits under `artifacts/clusters/<cluster_id>/`
- validated datasheet persistence plus `synthesis.json` provenance artifacts
- CLI wiring for `ollama`, `remote`, and `heuristic` synthesis backends

The remaining user-facing gaps are around environment setup and output quality,
not missing synthesis plumbing.

## Backend Contract

The `SynthesisBackend` protocol accepts:

- `observations`
- `hits`
- `previous_error`

and returns either a `SynthesisArtifact` or a raw payload string for legacy
callers. The pipeline normalizes both forms into a `SynthesisArtifact`.

## Current Backends

### `HeuristicSynthesisBackend`

- Builds a low-confidence datasheet from extracted labels, identifiers, and the
  first few search snippets
- Useful for offline or no-model runs
- Intentionally conservative and explicitly tells the reader to switch to an
  LLM-backed path for better results

### `OllamaDatasheetSynthesisBackend`

- Calls `ollama.chat()` with the `ItemDatasheet` JSON schema as the transport
  `format`
- Raises a clear error if the `ollama` package is not installed
- Persists the raw payload and prompt text in the resulting `SynthesisArtifact`

### `RemoteDatasheetSynthesisBackend`

- Calls an OpenAI-compatible `/chat/completions` endpoint
- Uses `response_format={"type": "json_schema", ...}`
- Resolves configuration from explicit args first, then environment variables
- Fails clearly if no API key is configured

## Request and Validation Flow

Each cluster follows this path:

1. Build a synthesis request from normalized observations and search hits.
2. Ask the selected backend for a datasheet payload.
3. Normalize the backend response into a `SynthesisArtifact`.
4. Repair common JSON issues:
   - Markdown code fences
   - trailing commas
   - single-quoted strings
   - truncated closing braces and brackets
5. Parse JSON and backfill missing `evidence_refs` / `search_hit_refs`.
6. Clamp `confidence` into the `[0.0, 1.0]` range.
7. Validate the payload as `ItemDatasheet`.

The synthesis module makes at most two attempts before raising
`SynthesisFailure`.

## Artifact Model

For each cluster, persist two distinct synthesis outputs:

- `datasheet.json`
  - accepted, validated `ItemDatasheet`
- `synthesis.json`
  - synthesis metadata and raw backend output for debugging and reproducibility

Suggested `synthesis.json` shape:

```json
{
  "backend_name": "ollama",
  "model_name": "qwen2.5vl:7b",
  "schema_name": "ItemDatasheet",
  "raw_payload": "{...}",
  "accepted": true,
  "attempt_count": 1,
  "last_error": null
}
```

`datasheet.json` drives reporting and sidecar generation. `synthesis.json`
captures provenance and failure context for debugging.

## Data Flow

1. `fff run` builds the selected synthesis backend.
2. For each cluster, the pipeline passes observations and normalized search hits
   into `synthesize_item_with_artifact()`.
3. The synthesis module calls the selected backend.
4. The backend returns a raw payload or a `SynthesisArtifact`.
5. The acceptance gate repairs and validates the payload into `ItemDatasheet`.
6. The pipeline writes:
   - `datasheet.json`
   - `synthesis.json`
7. Reporting and sidecar generation continue to consume the validated
   datasheet only.

## Error Handling

- If the backend transport fails, surface a clear synthesis error for that
  cluster.
- If schema-mode output is invalid, reject it and record the raw payload plus
  error in `synthesis.json`.
- Keep retries bounded and minimal.
- Do not silently fall back from model-backed synthesis to the heuristic
  backend; failures remain visible as partial runs.
- When synthesis fails, `pipeline.py` still writes a placeholder datasheet so
  the report renders and the failure remains inspectable.

## Current User-Visible Behavior

- `fff run` defaults to Ollama synthesis.
- `fff run --synthesis-backend heuristic` gives a model-free fallback.
- `fff run --synthesis-backend remote` talks to an OpenAI-compatible endpoint.
- Missing packages or backend failures do not crash the whole run; they produce
  partial output plus a recorded failure in the run summary and artifacts.

## Test Strategy

- Ollama synthesis backend returns valid datasheet JSON when transport returns
  structured data
- invalid structured payload is rejected cleanly
- missing required fields are rejected
- remote backend configuration and transport behavior are covered
- pipeline persists `synthesis.json` beside `datasheet.json`

The core tests mock transport boundaries. Slow integration coverage lives in
`tests/test_integration.py`.

## Risks

- Ollama schema mode may still occasionally wrap output or return malformed
  content despite transport-level structure support
- the default `run` path still depends on optional extras and external services
- the heuristic backend remains useful for resilience, but its outputs are much
  lower confidence than the model-backed paths
