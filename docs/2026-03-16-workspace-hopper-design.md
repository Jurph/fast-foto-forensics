# Workspace Hopper Design

> Status: Drafted from approved design discussion
> Date: 2026-03-16
> Related: `docs/2026-03-14-fast-foto-forensics-phase1-implementation-plan.md`

## Goal

Support an investigator workflow where new evidence photos keep arriving while
older photos are still being processed, without turning reruns, duplicate
images, or partial failures into chaos.

The system should let an operator:

1. run vision against all intake images waiting in a hopper
2. run searches against all completed vision artifacts waiting in a hopper
3. build work products from completed search artifacts waiting in a hopper

The first work product target is a batch PDF that places the source image in
the upper-left of each page and renders a pseudo-datasheet beneath or beside
it.

## Architecture Decision

Use a **manifest-first workspace** with operator-friendly folders.

The folders are for humans. A local SQLite ledger is the canonical truth.

Why this approach:

- Moving files alone is not enough to model reruns, retries, or partial stage
  completion safely.
- Investigators may receive new batches while older batches are still being
  processed.
- The system needs to remember which expensive work is already done even when
  the original images stay where they are.
- We want both a `move files` and `don't move files` mode for field use and
  test use.

Alternatives considered:

- **Folder-state-only:** easy to explain, but brittle for reruns, dedupe, and
  partial failures.
- **Run-directory-only:** good for isolated experiments, but awkward for a
  continuously growing operational workspace.

## Workspace Layout

Each operator workspace should have:

```text
workspace/
  ingest_images/
  processed_images/
  vision_interim/
  search_interim/
  outputs/
  workspace.sqlite
  workspace.toml
```

Folder roles:

- `ingest_images/`
  - operator drop zone for new incoming evidence
- `processed_images/`
  - optional resting place for successfully handled source files when move mode
    is enabled
- `vision_interim/`
  - one JSON artifact per observation or cluster seed after vision completes
- `search_interim/`
  - one JSON artifact per observation, cluster, or subject after search completes
- `outputs/`
  - PDFs, Markdown, composed summaries, and future operator-facing deliverables

Canonical state:

- `workspace.sqlite`
  - tracks discovery, hashes, stage status, artifact paths, and grouping hints
- `workspace.toml`
  - stores operator-visible settings such as move policy, default backends, and
    output preferences

## State Model

The design distinguishes four levels of identity.

### Raw File

One physical file on disk.

Fields:

- `file_id`
- `current_path`
- `original_path`
- `sha256`
- `size_bytes`
- `mtime`
- `intake_batch`
- `disposition_state`

### Observation

One analyzable evidence unit.

For image folders today, this is usually one image file. Later, one PDF can
produce many observations.

Fields:

- `observation_id`
- `file_id`
- `media_kind`
- `source_sha256`
- `sequence_index`
- `vision_artifact_path`
- `search_artifact_path`
- `product_artifact_path`

### Subject

A likely real-world object inferred across multiple observations.

This is the boundary that eventually lets us collapse:

- the same router photographed from five angles
- the same power conditioner appearing in multiple rack shots
- many evidence images that likely refer to one object

Fields:

- `subject_id`
- `status`
- `manual_label`
- `grouping_basis`
- `candidate_identifiers`
- `vendor`
- `object_class`

### Stage Status

Each observation keeps independent status for:

- `vision_status`
- `search_status`
- `product_status`

Each stage status should also record:

- `backend_name`
- `model_name`
- `config_fingerprint`
- `attempt_count`
- `completed_at`
- `error_text`
- `artifact_path`

This keeps reruns deliberate and auditable.

## File Disposition Policy

The workspace should support both:

- `leave`
  - source files remain in `ingest_images/`
  - used for testing, repeated experimentation, and low-friction prototyping
- `move_to_processed`
  - source files move to `processed_images/` after a successful vision pass
  - used when operators want the hopper to visibly empty as work proceeds

This must be a workspace policy, not a hard-coded behavior.

The ledger should always remember both the original path and the current path.

## Proposed CLI Shape

Recommended commands:

```text
fff workspace init <workspace_root>
fff vision sweep <workspace_root>
fff search sweep <workspace_root>
fff product build <workspace_root> --format pdf
```

Optional convenience alias for the first PDF prototype:

```text
fff pdf-datasheet <workspace_root>
```

That alias should internally route to:

```text
fff product build <workspace_root> --format pdf
```

### `fff workspace init`

Creates the hopper folders, `workspace.toml`, and `workspace.sqlite`.

### `fff vision sweep`

Responsibilities:

- scan `ingest_images/`
- discover new files or changed files
- create or update raw-file and observation records
- run vision only where stale or missing
- write JSON artifacts to `vision_interim/`
- optionally move successfully processed files to `processed_images/`

### `fff search sweep`

Responsibilities:

- find observations whose vision stage is complete and whose search stage is stale
- build or refresh query plans
- run search providers
- write normalized JSON artifacts to `search_interim/`

### `fff product build`

Responsibilities:

- select search-complete observations or subjects
- build work products into `outputs/`
- leave a record of what output was built from which upstream artifacts

For the first PDF prototype, the product builder should emit a single PDF with
one evidence item per page.

## Rerun Semantics

Reruns should be stage-aware and idempotent.

Examples:

- if a file hash is unchanged and the vision backend config is unchanged, reuse
  the vision artifact
- if search provider or query-planning config changes, rerun search without
  rerunning vision
- if only the PDF layout changes, rebuild products from `search_interim/`
  without rerunning search or vision

This implies a `config_fingerprint` concept per stage.

Recommended rule:

- a stage reruns only when inputs, upstream artifact identity, or stage config
  fingerprint change

## Duplicate, Multi-Angle, and Multi-Object Handling

### Duplicate images

Exact duplicate files should be detected by `sha256`.

The system should avoid duplicate expensive processing, but it should still
record that multiple file paths existed if they did.

### Same object from many angles

The system should not aggressively merge observations into one subject in the
first implementation. Wrong merges are more damaging than duplicate pages.

Instead:

- create **subject hints**
- keep the grouping soft and revisable
- allow product build to remain one observation per page for the first pass

Signals for future subject grouping:

- shared candidate identifiers
- same vendor and object class
- temporal or filename adjacency
- folder locality
- later, manual analyst grouping

### Many objects in one image

The first implementation should acknowledge this limitation rather than pretend
to solve it.

Initial behavior:

- one image yields one observation
- the observation may describe multiple objects in its caption or open questions
- later work can add region-level or object-level splitting

## Late-Arriving Batches

This design assumes new evidence can appear while old evidence is still in
flight.

The sweeps should therefore:

- be safe to run repeatedly
- discover only new or changed files
- avoid resetting completed stage state for unrelated observations
- tolerate partial completion from prior runs

In practice, the operator experience should be:

- drop in more files
- rerun `fff vision sweep`
- only new or stale observations get work

## PDF Prototype

The first PDF work product should be intentionally simple.

Output:

- one PDF per build in `outputs/`
- one evidence item per page
- source image in the upper-left
- pseudo-datasheet fields laid out clearly beside or below the image

Suggested sections per page:

- probable identity
- object class
- likely function
- manufacturer
- candidate identifiers
- OCR text
- vision labels
- search-derived notes
- open questions

The first PDF builder should prefer correctness and repeatability over clever
deduplication.

## Suggested Backlog Changes

The current backlog already has good coverage for artifacts, reruns, and mixed
evidence, but it does not yet model the workspace itself as a first-class
capability.

Recommended issue adjustment:

- add a new feature under `Epic: Repeatable Local Runs`
  - `Feature: Workspace Hoppers and Incremental Stage Processing`

Recommended subtasks under that feature:

- bootstrap workspace folders and `workspace.toml`
- add `workspace.sqlite` with raw-file, observation, subject, and stage tables
- implement `leave` vs `move_to_processed` file disposition
- add `fff vision sweep`
- add `fff search sweep`
- add `fff product build`
- add initial PDF pseudo-datasheet output
- make sweeps idempotent for reruns and late-arriving batches
- seed subject-hint grouping without hard dedupe

## Design Summary

The important design choice is that folders are an operator interface, not the
state machine. The state machine lives in the ledger.

That gives us:

- safe reruns
- explicit move/no-move behavior
- room for continuous intake
- future subject grouping
- stage-specific work products such as PDFs without redoing upstream work
