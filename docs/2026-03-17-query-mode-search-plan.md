# Query Mode Search Planner Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the deterministic query planner to switch between identity, mixed, and document-seeking query modes based on the strength of extracted vendor, identifier, and function signals.

**Architecture:** Keep the current planner deterministic and cheap. Add a small token-classification layer for `model_like`, `instance_like`, and `ambiguous` identifiers, then derive a query mode from those classes plus vendor/object-class presence. Query generation stays in `query_planner.py`; tests in `tests/test_query_planner.py` define the combinatorics.

**Tech Stack:** Python 3.11, pytest, existing dataclass-based query planner.

---

## Files and Responsibilities

- Modify: `src/fast_foto_forensics/query_planner.py`
  - classify identifier-like tokens
  - choose `identity`, `mixed`, or `document` query mode
  - add doc-intent query variants like `datasheet`, `manual`, and `specifications`
- Modify: `tests/test_query_planner.py`
  - encode the decision table in focused tests
- Optional doc touch: none for this slice unless behavior needs a short comment

## Chunk 1: Query Mode Decision Table

### Task 1: Add failing tests for query-mode selection

**Files:**
- Modify: `tests/test_query_planner.py`

- [ ] **Step 1: Write a failing test for strong document mode**

Add a case with `vendor + model-like identifier + object_class`, such as `Linksys + WRT54G + wireless router`, and assert that the selected queries include doc-intent variants like `datasheet` or `manual`.

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_query_planner.py -k document_mode`

Expected: FAIL because the current planner only emits cross-product queries and OCR fallback.

- [ ] **Step 3: Write a failing test for mixed mode**

Add a case with an ambiguous identifier and supporting context, such as `vendor + 8-char alphanumeric + object_class`, and assert the plan includes both a plain identity query and exactly one doc-intent query.

- [ ] **Step 4: Run the targeted test to verify it fails**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_query_planner.py -k mixed_mode`

Expected: FAIL for missing doc-intent behavior.

- [ ] **Step 5: Write a failing test for instance-like identifiers staying out of document mode**

Add a case where the token is clearly serial-like or MAC-like and assert the plan stays in identity mode without `datasheet` / `manual` salting.

- [ ] **Step 6: Run the targeted test to verify it fails**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_query_planner.py -k instance_like`

Expected: FAIL because current behavior treats all alphanumerics similarly.

## Chunk 2: Minimal Planner Implementation

### Task 2: Add token classification and mode selection

**Files:**
- Modify: `src/fast_foto_forensics/query_planner.py`
- Test: `tests/test_query_planner.py`

- [ ] **Step 1: Add helper(s) that classify identifier-like tokens**

Implement a small deterministic helper that returns `model_like`, `instance_like`, or `ambiguous` using:
- explicit serial/mac keywords when available
- MAC-address shape
- overly long high-entropy tokens as `instance_like`
- short-to-medium alphanumeric product-code shapes as `ambiguous` or `model_like`

- [ ] **Step 2: Add helper(s) that choose query mode**

Implement deterministic mode selection:
- `document` when a `model_like` token exists and at least one of vendor/object_class exists
- `mixed` when only `ambiguous` token(s) exist with supporting context
- `identity` otherwise

- [ ] **Step 3: Add doc-intent query generation**

For `document` mode, generate doc variants such as:
- `<anchor> datasheet`
- `<anchor> specifications`
- `<anchor> manual`

For `mixed` mode, keep at least one plain identity query and allow a smaller doc-intent set.

- [ ] **Step 4: Preserve existing safeguards**

Keep:
- vendor-anchored queries scoring highest
- OCR blob fallback as low score
- max query cap
- dedup/provenance merging

- [ ] **Step 5: Run the planner test file**

Run: `scripts/uvw.cmd run --extra dev pytest -q tests/test_query_planner.py`

Expected: PASS.

## Chunk 3: Verification and Cleanup

### Task 3: Verify that the planner still behaves well in the broader repo

**Files:**
- No new code expected unless verification exposes regressions

- [ ] **Step 1: Run the full test suite**

Run: `scripts/uvw.cmd run --extra dev --extra search_ddgs pytest -q`

- [ ] **Step 2: Run Ruff**

Run: `scripts/uvw.cmd run --extra dev ruff check --no-cache src tests`

- [ ] **Step 3: Run Ruff format check**

Run: `scripts/uvw.cmd run --extra dev ruff format --check src tests`

- [ ] **Step 4: Run mypy**

Run: `scripts/uvw.cmd run --extra dev mypy src`

- [ ] **Step 5: Commit**

```bash
git add docs/2026-03-17-query-mode-search-plan.md src/fast_foto_forensics/query_planner.py tests/test_query_planner.py
git commit -m "feat: add query-mode search planning"
```
