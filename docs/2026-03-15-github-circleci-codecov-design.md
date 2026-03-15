# GitHub, CircleCI, and Codecov Design

## Goal

Publish `fast-foto-forensics` to GitHub under `Jurph/fast-foto-forensics`, make `main` the
default tracked branch, and use CircleCI plus Codecov as the active CI and coverage surface.

## Design Decisions

- Use the `solar` repo as the primary pattern, not `harmonictook`.
- Keep GitHub Actions in the repository as a template artifact, but disable it so CircleCI is the
  only active CI system for this repo.
- Show coverage publicly in Codecov, but do not fail CI on a hard coverage threshold yet.
- Add CircleCI and Codecov badges near the top of the README.
- Keep the repo's Python workflow aligned with current local practice:
  - `pytest`
  - `ruff`
  - `mypy`
  - `uv` for local setup
  - `pip`/venv in CircleCI for predictable Linux CI bootstrapping

## Remote Bootstrap

- Create a GitHub repository named `fast-foto-forensics` under the `Jurph` account.
- Add `origin` pointing to that repository.
- Push local `main` and set upstream tracking.
- Let GitHub keep `main` as the default branch.

Because `gh` is not installed on this machine, remote creation should be done via the GitHub REST
API if we have a suitable personal access token. If not, the repo can be created manually in the
browser and then connected locally with `git remote add origin`.

## CircleCI Design

- Add `.circleci/config.yml`.
- Use one `test` job for now:
  - `cimg/python:3.11`
  - cache a repo-local virtual environment keyed by `pyproject.toml`
  - install with `pip install -e ".[dev,ci]"`
  - run `pytest` with coverage for `src/fast_foto_forensics`
  - emit `coverage.xml`
  - upload coverage to Codecov
- Store `coverage.xml` and JUnit XML as CircleCI artifacts/test results.

This repo is still small, so unlike `solar`, it does not need CircleCI test splitting or a
separate “notify Codecov to merge parallel uploads” job yet.

## Codecov Design

- Add `.codecov.yml`.
- Add a `ci` optional dependency group containing `codecov-cli`.
- Add `pytest-cov` to development dependencies.
- Upload coverage from CircleCI using `CODECOV_TOKEN`.
- Configure Codecov to:
  - wait for CI
  - report project and patch coverage
  - avoid blocking on an aggressive target initially
  - ignore tests and other non-source files

## GitHub Actions Template Preservation

- Keep the current `.github/workflows/ci.yml` content in the repo, but rename it so GitHub does not
  execute it.
- Add a short comment at the top of the disabled template noting that CircleCI is the active CI for
  this repo.

## README Changes

- Add:
  - CircleCI badge
  - Codecov badge
- Place both immediately below the `# Fast Foto Forensics` heading.
- Add a short CI note describing CircleCI as the active CI and Codecov as the coverage dashboard.

## Risks and Constraints

- GitHub repo creation cannot be fully automated without authentication.
- CircleCI and Codecov both require project-side setup outside the repo:
  - CircleCI project activation
  - Codecov project activation
  - `CODECOV_TOKEN` in CircleCI project environment variables
- Badge URLs only become meaningful after the GitHub remote exists and the services are connected.

## Acceptance Criteria

- A public GitHub repo exists at `Jurph/fast-foto-forensics`.
- Local `main` pushes to `origin/main`.
- CircleCI runs the pytest suite on each push.
- Codecov receives coverage uploads from CircleCI.
- README shows working CircleCI and Codecov badges.
- GitHub Actions workflow remains in the repo as a disabled template.
