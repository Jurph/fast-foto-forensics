# Synthesis MVP Design

## Summary

Finish the remaining MVP synthesis slice for `fast-foto-forensics` by replacing the heuristic datasheet step with a real Ollama-backed structured-output backend, adding a switchable remote-backend stub for later work, and preserving synthesis provenance in artifacts without complicating the operator-facing report.

This design intentionally keeps the active operator path local-first. `fff run` should continue to default to local/Ollama synthesis, while the remote backend exists only as a future extension point.

## Goals

- Replace `HeuristicSynthesisBackend` as the meaningful MVP path with a real local LLM-backed datasheet synthesizer.
- Use transport-level structured output where possible instead of prompt-only JSON coercion.
- Persist synthesis provenance and raw backend output for debugging and reruns.
- Keep the final human-facing datasheet clean while preserving messy interim state in artifacts.
- Avoid overlapping with the CLI-focused `#38` work already delegated elsewhere.

## Non-Goals

- Full frontier-model support in the MVP.
- Complex per-field scoring or Bayesian weighting between vision and search evidence.
- Large CLI redesign.
- Rich repair loops that repeatedly plead with the model to emit valid JSON.

## Current State

The pipeline already has:

- real vision backends in `src/fast_foto_forensics/vision.py`
- real search backends in `src/fast_foto_forensics/search.py`
- query-plan and hit artifacts persisted under per-cluster paths in `src/fast_foto_forensics/pipeline.py`
- a simple acceptance gate in `src/fast_foto_forensics/synthesis.py`

The main gap is that synthesis still runs through `HeuristicSynthesisBackend`, which does not perform model-backed reasoning over the evidence bundle.

## Design

### Backend Contract

Keep the existing `SynthesisBackend` protocol shape:

- input: `observations`, `hits`, `previous_error`
- output: raw payload string

Add two concrete backends:

- `OllamaDatasheetSynthesisBackend`
- `RemoteDatasheetSynthesisBackend`

The local Ollama backend is the real MVP path. The remote backend is a stub that satisfies the interface and fails fast with a clear "not implemented / not configured" message.

### Structured Output Strategy

Use structured-output mode at the model transport boundary instead of relying on prompt-only JSON requests. The design should mirror the pattern already used in `solar`:

- send a real JSON schema to the backend where supported
- keep a minimal system prompt describing the task and field expectations
- treat schema-conformant output as the primary control mechanism

For the Ollama path, this means calling Ollama's chat endpoint in schema mode rather than using a "pretty please emit JSON" loop.

### Validation Philosophy

Validation remains important, but it should be boundary validation, not an elaborate persuasion loop.

Acceptable guardrails:

- validate the model payload locally against `ItemDatasheet`
- reject malformed or incomplete payloads
- record the raw payload and error metadata in artifacts
- allow at most a minimal bounded retry path if the transport returns unusable content despite schema mode

Not acceptable for this MVP:

- repeated prompt-repair loops
- ad hoc text extraction heuristics that pretend plain text is valid structured output

### Artifact Model

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

This artifact is for provenance and diagnosis, not direct rendering.

### Prompt / Request Construction

Build the synthesis request from:

- normalized observations
- normalized search hits
- an explicit instruction to identify the most likely object/function from the combined evidence
- a strict schema-backed output requirement

The request builder should be a small dedicated helper, not inlined into the transport method.

### Remote Backend Stub

The remote backend should:

- satisfy `SynthesisBackend`
- be constructible/configurable
- raise a clear error such as "remote synthesis backend is not configured yet"

This keeps the switch point in place without forcing premature provider-specific work into the MVP.

## Data Flow

1. `fff run` builds the selected synthesis backend.
2. For each cluster, the pipeline passes observations and normalized search hits into `synthesize_item()`.
3. `synthesize_item()` calls the selected backend.
4. The backend returns raw output.
5. The acceptance gate validates the raw output into `ItemDatasheet`.
6. The pipeline writes:
   - `datasheet.json`
   - `synthesis.json`
7. Reporting and sidecar generation continue to consume the validated datasheet only.

## Error Handling

- If the backend transport fails, surface a clear synthesis error for that cluster.
- If schema-mode output is still invalid, reject it and record the raw payload plus error in `synthesis.json`.
- Keep retries bounded and minimal.
- Do not silently fall back from model-backed synthesis to the heuristic backend on MVP runs; failures should remain visible.

## Files Likely To Change

- `src/fast_foto_forensics/synthesis.py`
  - new concrete synthesis backends
  - structured-output request helper
  - provenance artifact support
- `src/fast_foto_forensics/pipeline.py`
  - write `synthesis.json`
  - select the new active synthesis backend
- `src/fast_foto_forensics/cli.py`
  - only minimal wiring if backend selection needs to change
- `tests/test_synthesis.py`
  - backend and validation tests
- `tests/test_pipeline.py`
  - artifact persistence tests
- optional new test module if synthesis tests become too large

## Testing Strategy

Required tests:

- Ollama synthesis backend returns valid datasheet JSON when transport returns structured data
- invalid structured payload is rejected cleanly
- missing required fields are rejected
- remote backend stub raises the expected actionable error
- pipeline persists `synthesis.json` beside `datasheet.json`

Prefer mocked transport tests over live model calls for the core TDD loop.

## Risks

- Ollama schema mode may still occasionally wrap output or return malformed content despite transport-level structure support
- current `uv.lock` appears stale relative to the latest `HEAD`, so the first implementation step should include restoring a green locked baseline before claiming success

## MVP Closure Impact

Once this lands, the remaining MVP epic should be limited to:

- the synthesis feature actually using a real local model
- any final CLI/reporting polish still needed after `#38`

This keeps the MVP honest: real vision, real search, real structured synthesis, one-command run.
