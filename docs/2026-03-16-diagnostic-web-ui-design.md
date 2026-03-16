# Diagnostic Web UI Design

## Goal

Add a tiny local web front-end that wraps the real Fast Foto Forensics pipeline end to end for a single image. The page should accept either a drag-and-drop upload or a pasted image URL, run the actual vision, query-planning, search, and synthesis stages, and show the intermediate and final artifacts in a simple vertically stacked diagnostic view.

This is a prototype for a future user-facing UI, but it should be honest about present behavior. It must show real results, real latency, and real failures rather than mocked or accelerated placeholders.

## Product Shape

The page is intentionally simple:

- image input area at the top
- source image preview
- `<hr>` separators between sections
- live log/scroller while work is in progress
- raw `Vision JSON`
- human-readable `Vision summary`
- `Query plan`
- `Search hits`
- `Datasheet JSON`
- rendered datasheet card
- explicit `Export` button for retry fixtures

The UI is stateless by default. A submission does not create a saved run or workspace record. The only persistent action is `Export`, which copies the original image into a repo-owned retry corpus along with a small metadata sidecar.

## Architecture

The prototype should be built as a small Python web app with no Node/Vite/React stack.

Recommended units:

- `web_diagnostic.py`
  - HTTP app and routes
  - serves one HTML page plus lightweight JS/CSS assets
  - accepts upload and URL-based submissions
  - streams progress events and returns section payloads
- `diagnostic_runner.py`
  - orchestrates one real end-to-end diagnostic run
  - reuses existing ingestion, vision, query planning, search, and synthesis modules
  - produces a single structured response object for the UI
- `export_fixture.py`
  - handles `Export`
  - copies the source image into a retry corpus folder
  - writes metadata sidecar with notes and failure context

The current pipeline is batch/run-oriented, so the diagnostic runner should be a thin adapter rather than a full new pipeline. It can still use temp working directories internally, but those should be treated as disposable execution scratch space.

## Data Flow

For each submission:

1. Accept a local upload or fetch an image from a pasted URL.
2. Materialize the image as a local file in a disposable working area.
3. Build one normalized `EvidenceObservation`.
4. Run the real stages:
   - vision extraction
   - query planning
   - search retrieval
   - datasheet synthesis
5. Emit progress messages for the live log as each stage starts and completes.
6. Return a response containing:
   - previewable source image reference
   - `VisionResult` JSON
   - human-readable vision summary text
   - `QueryPlan`
   - normalized `SearchHit` list
   - `ItemDatasheet` JSON if synthesis succeeds
   - synthesis provenance if synthesis fails or degrades
   - rendered datasheet HTML/text
   - stage failure list

The UI should render whatever artifacts exist, even if later stages fail.

## Export Behavior

`Export` should be explicit and opt-in.

When clicked, the app should:

- copy the original source image into a repo retry corpus such as `artifacts/diagnostic_exports/`
- generate a stable-ish timestamped filename
- write a sidecar JSON file next to the image containing:
  - export timestamp
  - source type (`upload` or `url`)
  - original URL when applicable
  - optional analyst note
  - stage failures recorded during the run
  - model/backend names used for vision and synthesis

This creates a simple path from “this looked weird in the UI” to “we can retry this exact case later.”

## Error Handling

The web UI should not be all-or-nothing.

- URL fetch failure:
  - stop early
  - show clear error in log and result area
  - no later sections
- vision failure:
  - still show source image and failure details
  - allow export
- search failure:
  - still show source image, vision output, and query plan
  - record search failure in diagnostics
- synthesis failure:
  - still show source image, vision output, query plan, search hits
  - show datasheet section as unavailable
  - surface synthesis provenance/error details

## Testing Strategy

Add tests at three levels:

- unit tests for the diagnostic runner
  - upload path normalization
  - URL path normalization
  - partial failure handling
  - rendered response shape
- endpoint tests for the web app
  - GET page
  - POST upload
  - POST URL
  - POST export
- integration-style tests with replay/static backends
  - prove the UI wrapper is using the real module boundaries rather than private mock-only logic

## Non-Goals

This prototype should not try to be:

- a multi-user server
- a persistent case-management UI
- a folder/workspace browser
- a generalized front-end framework foundation
- a dedupe/repeat-photo analysis tool yet

The only goal is to provide an honest, repeatable single-image diagnostic wrapper around the real end-to-end system.
