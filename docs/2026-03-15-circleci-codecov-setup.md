# CircleCI and Codecov Setup

## After the GitHub repo exists

1. Push `main` to `origin`.
2. In CircleCI, add the GitHub project `Jurph/fast-foto-forensics`.
3. In Codecov, activate the repository `Jurph/fast-foto-forensics`.

## CircleCI environment variable

Add this project-level environment variable in CircleCI:

- `CODECOV_TOKEN`

Easy click path:

1. Open `https://app.circleci.com/`
2. Open the `fast-foto-forensics` project
3. Click `Project Settings`
4. Click `Environment Variables`
5. Click `Add Variable`
6. Name: `CODECOV_TOKEN`
7. Value: the repository token from Codecov
8. Save, then push one more commit to trigger an upload

Without that token, the CircleCI job will still run tests and generate `coverage.xml`, but it will
skip the Codecov upload step.

## Expected badge URLs

- CircleCI:
  `https://dl.circleci.com/status-badge/img/gh/Jurph/fast-foto-forensics/tree/main.svg?style=shield`
- Codecov:
  `https://codecov.io/gh/Jurph/fast-foto-forensics/branch/main/graph/badge.svg`

## Expected CI behavior

- CircleCI runs on pushes to GitHub.
- The job installs `.[dev,ci]`, runs `pytest` with coverage, and stores `coverage.xml`.
- Codecov receives the uploaded coverage report once `CODECOV_TOKEN` is configured.
