# Windows Tempfile Guardrail

## Root Cause

On this machine, Python's `tempfile.mkdtemp()` and `TemporaryDirectory()` create directories via
`os.mkdir(path, 0o700)`. In practice, those directories can report as readable and writable while
still rejecting `listdir`, file creation, and child directory creation with `PermissionError`.

This reproduces both:

- under the repo with `tempfile.mkdtemp(dir=Path(".tmp"))`
- under the default user temp directory with plain `tempfile.mkdtemp()`

That makes the problem a Windows/Python tempfile-directory behavior on this setup, not a problem
with the repo path itself.

## Project Rule

- Do not point `TMP` or `TEMP` at repo-local directories in wrapper scripts.
- Do not use `tempfile.mkdtemp()` or `TemporaryDirectory()` for repo-local scratch state.
- Prefer manual scratch directories such as `.scratch/<unique-id>` created with `Path.mkdir()`.
- Run Ruff against `src` and `tests`, not the whole repo root, so stale scratch directories do not
  pollute verification.

## Practical Pattern

```python
from pathlib import Path
from uuid import uuid4

scratch_root = Path(".scratch")
scratch_root.mkdir(exist_ok=True)
work_dir = scratch_root / uuid4().hex
work_dir.mkdir()
```
