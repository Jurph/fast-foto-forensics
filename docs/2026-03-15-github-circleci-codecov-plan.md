# GitHub, CircleCI, and Codecov Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the repo to GitHub, activate CircleCI as the primary CI, upload coverage to Codecov, and expose both services in the README.

**Architecture:** Follow the `solar` repo pattern with a single CircleCI job for this smaller codebase. Keep the GitHub Actions workflow in the tree as a disabled template, while CircleCI handles testing and Codecov handles coverage visibility.

**Tech Stack:** Git, GitHub REST API, CircleCI config, Codecov CLI, Python 3.11, `pytest`, `pytest-cov`, `ruff`, `mypy`.

---

## File Map

- Create: `.circleci/config.yml` for active CI
- Create: `.codecov.yml` for coverage reporting behavior
- Modify: `pyproject.toml` to add CI/coverage dependencies
- Modify: `README.md` to add badges and CI notes
- Modify: `.gitignore` only if CI-related generated files need ignoring
- Move: `.github/workflows/ci.yml` to a disabled template filename
- Create or modify: optional helper docs under `docs/` if setup notes are needed

## Chunk 1: Repo CI Configuration

### Task 1: Add failing coverage-oriented tests and dependency expectations

**Files:**
- Modify: `tests/test_smoke.py`
- Create: `tests/test_ci_docs.py`
- Test: `tests/test_ci_docs.py`

- [ ] **Step 1: Write failing tests for CI-facing docs/config expectations**

```python
def test_readme_mentions_circleci_and_codecov() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "CircleCI" in text
    assert "codecov" in text.lower()
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `& '.\\.venv\\Scripts\\python.exe' -m pytest tests\\test_ci_docs.py -q`
Expected: FAIL because the README/config has not been updated yet.

- [ ] **Step 3: Add minimal tests for disabled GitHub Actions template presence**

```python
def test_disabled_github_actions_template_exists() -> None:
    assert Path(".github/workflows/ci.yml.disabled").exists()
```

- [ ] **Step 4: Re-run the focused tests**

Run: `& '.\\.venv\\Scripts\\python.exe' -m pytest tests\\test_ci_docs.py -q`
Expected: FAIL until implementation lands.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ci_docs.py tests/test_smoke.py
git commit -m "test: add CI documentation expectations"
```

### Task 2: Add CircleCI and Codecov configuration

**Files:**
- Create: `.circleci/config.yml`
- Create: `.codecov.yml`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Move: `.github/workflows/ci.yml` -> `.github/workflows/ci.yml.disabled`

- [ ] **Step 1: Implement the CircleCI config**

```yaml
version: 2.1
jobs:
  test:
    docker:
      - image: cimg/python:3.11
```

- [ ] **Step 2: Add `pytest-cov` and `codecov-cli` dependencies**

```toml
[project.optional-dependencies]
dev = [
  "pytest-cov>=7.0.0",
]
ci = [
  "codecov-cli",
]
```

- [ ] **Step 3: Add README badges and CI note**

```md
[![CircleCI](...)](...)
[![codecov](...)](...)
```

- [ ] **Step 4: Disable GitHub Actions while preserving the template**

Rename:
` .github/workflows/ci.yml -> .github/workflows/ci.yml.disabled `

- [ ] **Step 5: Run focused tests**

Run: `& '.\\.venv\\Scripts\\python.exe' -m pytest tests\\test_ci_docs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .circleci/config.yml .codecov.yml .github/workflows/ci.yml.disabled README.md pyproject.toml tests/test_ci_docs.py
git commit -m "feat: add CircleCI and Codecov configuration"
```

## Chunk 2: Local Verification and Remote Bootstrap

### Task 3: Verify CI-facing local commands

**Files:**
- Modify: none unless verification exposes an issue

- [ ] **Step 1: Run the full local suite**

Run: `& '.\\.venv\\Scripts\\python.exe' -m pytest -q`
Expected: PASS.

- [ ] **Step 2: Run Ruff**

Run: `& '.\\.venv\\Scripts\\ruff.exe' check --no-cache src tests`
Expected: PASS.

- [ ] **Step 3: Run formatting check**

Run: `& '.\\.venv\\Scripts\\ruff.exe' format --check src tests`
Expected: PASS.

- [ ] **Step 4: Run mypy**

Run: `& '.\\.venv\\Scripts\\mypy.exe' src`
Expected: PASS.

- [ ] **Step 5: Smoke-test local coverage output**

Run: `& '.\\.venv\\Scripts\\python.exe' -m pytest --cov=src/fast_foto_forensics --cov-report=xml:coverage.xml --cov-report=term -q`
Expected: PASS and produce `coverage.xml`.

### Task 4: Create GitHub remote and push `main`

**Files:**
- Modify: local git config only

- [ ] **Step 1: Check whether GitHub CLI is available**

Run: `gh --version`
Expected: command not found or version output.

- [ ] **Step 2: If `gh` is unavailable, create the repo with GitHub REST API**

```powershell
Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" ...
```

- [ ] **Step 3: Add `origin`**

Run: `git remote add origin https://github.com/Jurph/fast-foto-forensics.git`
Expected: remote added.

- [ ] **Step 4: Push `main` and set upstream**

Run: `git push -u origin main`
Expected: local `main` tracks `origin/main`.

- [ ] **Step 5: Note external setup still required**

Record that CircleCI and Codecov project activation plus `CODECOV_TOKEN` are still needed unless
already connected on the account side.

## Chunk 3: Service Activation Notes

### Task 5: Document manual service-side setup

**Files:**
- Modify: `README.md` or create `docs/2026-03-15-circleci-codecov-setup.md`

- [ ] **Step 1: Document CircleCI activation**

- [ ] **Step 2: Document Codecov activation and token placement**

- [ ] **Step 3: Document expected badge URLs**

- [ ] **Step 4: Commit**

```bash
git add README.md docs/2026-03-15-circleci-codecov-setup.md
git commit -m "docs: add CircleCI and Codecov setup notes"
```
