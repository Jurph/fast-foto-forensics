# Vision Module Implementation Plan

> **Status:** Historical implementation plan. `src/fast_foto_forensics/vision.py`
> and the related tests are implemented; use the design doc and source for
> current behavior.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pluggable vision module that sends evidence images to Ollama (Qwen2.5-VL 7B), parses structured JSON responses, caches results as RunStore artifacts, and enriches `EvidenceObservation` objects for downstream query planning.

**Architecture:** A single `vision.py` module with a `VisionBackend` protocol, three concrete backends (`OllamaVisionBackend`, `FilenameVisionBackend`, `StaticVisionBackend`), orchestration helpers (`extract_with_cache`, `enrich_observations`, `enrich_single`), and a `VisionResult` dataclass in `models.py`. Caching uses per-observation JSON artifacts via `RunStore`. The existing `FilenameVisionBackend` moves from `pipeline.py` into `vision.py` and adopts the new protocol.

**Tech Stack:** Python 3.11, `ollama>=0.4.0` (optional extra), `pytest`, existing `RunStore` artifact system.

**Spec:** `docs/2026-03-15-vision-module-design.md`

---

## File Map

- Existing foundation:
  - `src/fast_foto_forensics/models.py` — shared dataclasses (add `VisionResult`)
  - `src/fast_foto_forensics/storage.py` — `RunStore` with `artifact_path()`, `write_json_artifact()`, `read_json_artifact()`
  - `src/fast_foto_forensics/pipeline.py` — `FilenameVisionBackend` (to be moved) and `run_pipeline()` (to be updated)
- New:
  - `src/fast_foto_forensics/vision.py` — `VisionBackend` protocol, all backends, orchestration helpers
  - `tests/test_vision.py` — unit and integration tests
- Modified:
  - `src/fast_foto_forensics/pipeline.py` — remove `FilenameVisionBackend`, use `vision.py` orchestration
  - `pyproject.toml` — add `ollama` optional extra
  - `models/MODEL_SOURCES.md` — note Ollama as primary delivery mechanism

---

## Chunk 1: VisionResult Dataclass and Dependency Setup

### Task 1: Add VisionResult to models.py

**Files:**
- Modify: `src/fast_foto_forensics/models.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing tests for VisionResult**

Create `tests/test_vision.py`:

```python
"""Tests for the vision module."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import VisionResult


def _sample_vision_dict() -> dict:
    return {
        "evidence_id": "img-001",
        "source_path": "evidence/router.jpg",
        "source_sha256": "abc123",
        "backend_name": "ollama",
        "model_name": "qwen2.5vl:7b",
        "caption": "A blue wireless router with two antennas.",
        "ocr_text": "WRT54G LINKSYS",
        "candidate_identifiers": ["WRT54G"],
        "vendor": "Linksys",
        "object_class": "wireless router",
        "detected_labels": ["router", "networking"],
    }


class TestVisionResult:
    def test_from_dict_round_trips(self) -> None:
        data = _sample_vision_dict()
        result = VisionResult.from_dict(data)
        assert result.evidence_id == "img-001"
        assert result.vendor == "Linksys"
        assert result.candidate_identifiers == ["WRT54G"]
        assert result.to_dict() == data

    def test_from_dict_requires_evidence_id(self) -> None:
        data = _sample_vision_dict()
        del data["evidence_id"]
        with pytest.raises(ValueError, match="evidence_id"):
            VisionResult.from_dict(data)

    def test_from_dict_allows_null_vendor(self) -> None:
        data = _sample_vision_dict()
        data["vendor"] = None
        result = VisionResult.from_dict(data)
        assert result.vendor is None

    def test_from_dict_allows_null_object_class(self) -> None:
        data = _sample_vision_dict()
        data["object_class"] = None
        result = VisionResult.from_dict(data)
        assert result.object_class is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py -v`
Expected: FAIL with `ImportError: cannot import name 'VisionResult'`

- [ ] **Step 3: Implement VisionResult**

Add to `src/fast_foto_forensics/models.py` (after `EvidenceCluster`, before `ItemDatasheet`):

```python
@dataclass(slots=True)
class VisionResult:
    """Raw output of one vision extraction pass."""

    evidence_id: str
    source_path: str
    source_sha256: str
    backend_name: str
    model_name: str
    caption: str
    ocr_text: str
    candidate_identifiers: list[str]
    vendor: str | None
    object_class: str | None
    detected_labels: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "backend_name": self.backend_name,
            "model_name": self.model_name,
            "caption": self.caption,
            "ocr_text": self.ocr_text,
            "candidate_identifiers": list(self.candidate_identifiers),
            "vendor": self.vendor,
            "object_class": self.object_class,
            "detected_labels": list(self.detected_labels),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionResult":
        return cls(
            evidence_id=_require_str(data, "evidence_id"),
            source_path=_require_str(data, "source_path"),
            source_sha256=_require_str(data, "source_sha256"),
            backend_name=_require_str(data, "backend_name"),
            model_name=_require_str(data, "model_name"),
            caption=_optional_str(data, "caption") or "",
            ocr_text=_optional_str(data, "ocr_text") or "",
            candidate_identifiers=(
                _require_list(data, "candidate_identifiers")
                if "candidate_identifiers" in data
                else []
            ),
            vendor=_optional_str(data, "vendor"),
            object_class=_optional_str(data, "object_class"),
            detected_labels=(
                _require_list(data, "detected_labels")
                if "detected_labels" in data
                else []
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_vision.py src/fast_foto_forensics/models.py
git commit -m "feat: add VisionResult dataclass with round-trip serialization"
```

### Task 2: Add ollama optional dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the vision_ollama extra to pyproject.toml**

Add after the `dev` extra in `[project.optional-dependencies]`:

```toml
vision_ollama = [
    "ollama>=0.4.0",
]
```

- [ ] **Step 2: Sync and verify the package resolves**

Run: `cmd /c scripts\uvw.cmd sync --extra dev --extra vision_ollama`
Expected: ollama package installs successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add ollama as optional vision_ollama extra"
```

---

## Chunk 2: Vision Backends and Error Handling

### Task 3: Implement VisionBackend protocol, VisionExtractionError, StaticVisionBackend

**Files:**
- Create: `src/fast_foto_forensics/vision.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing tests for the protocol and static backend**

Append to `tests/test_vision.py`:

```python
from fast_foto_forensics.vision import (
    StaticVisionBackend,
    VisionExtractionError,
)


class TestStaticVisionBackend:
    def test_returns_fixture_by_evidence_id(self) -> None:
        fixture = VisionResult.from_dict(_sample_vision_dict())
        backend = StaticVisionBackend(fixtures={"img-001": fixture})
        observation = EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )
        result = backend.extract(observation)
        assert result.evidence_id == "img-001"
        assert result.caption == "A blue wireless router with two antennas."

    def test_raises_for_unknown_evidence_id(self) -> None:
        backend = StaticVisionBackend(fixtures={})
        observation = EvidenceObservation(
            evidence_id="unknown",
            source_path="evidence/missing.jpg",
            media_kind="image",
            sha256="000",
            order_index=0,
        )
        with pytest.raises(VisionExtractionError, match="unknown"):
            backend.extract(observation)
```

Also add the needed import at the top:

```python
from fast_foto_forensics.models import EvidenceObservation, VisionResult
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestStaticVisionBackend -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fast_foto_forensics.vision'`

- [ ] **Step 3: Implement vision.py with protocol, error, and static backend**

Create `src/fast_foto_forensics/vision.py`:

```python
"""Pluggable vision backends for evidence image analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from fast_foto_forensics.models import EvidenceObservation, VisionResult


class VisionExtractionError(RuntimeError):
    """Raised when a vision backend fails to extract structured data."""


@runtime_checkable
class VisionBackend(Protocol):
    def extract(self, observation: EvidenceObservation) -> VisionResult: ...


class StaticVisionBackend:
    """Return canned VisionResult objects keyed by evidence_id."""

    def __init__(self, fixtures: dict[str, VisionResult]) -> None:
        self._fixtures = fixtures

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        result = self._fixtures.get(observation.evidence_id)
        if result is None:
            raise VisionExtractionError(
                f"no fixture for evidence_id={observation.evidence_id!r}"
            )
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/vision.py tests/test_vision.py
git commit -m "feat: add VisionBackend protocol and StaticVisionBackend"
```

### Task 4: Move FilenameVisionBackend into vision.py

**Files:**
- Modify: `src/fast_foto_forensics/vision.py`
- Modify: `src/fast_foto_forensics/pipeline.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing test for FilenameVisionBackend**

Append to `tests/test_vision.py`:

```python
from fast_foto_forensics.vision import FilenameVisionBackend


class TestFilenameVisionBackend:
    def test_extracts_labels_and_identifiers_from_filename(self) -> None:
        backend = FilenameVisionBackend()
        observation = EvidenceObservation(
            evidence_id="img-002",
            source_path="evidence/001-WRT54G-router.jpg",
            media_kind="image",
            sha256="def456",
            order_index=0,
        )
        result = backend.extract(observation)
        assert result.evidence_id == "img-002"
        assert result.backend_name == "filename"
        assert result.model_name == "filename"
        assert "WRT54G" in result.candidate_identifiers
        assert "router" in result.detected_labels

    def test_satisfies_vision_backend_protocol(self) -> None:
        assert isinstance(FilenameVisionBackend(), VisionBackend)
```

Also add `VisionBackend` to the import from `fast_foto_forensics.vision`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestFilenameVisionBackend -v`
Expected: FAIL with `ImportError: cannot import name 'FilenameVisionBackend' from 'fast_foto_forensics.vision'`

- [ ] **Step 3: Move FilenameVisionBackend to vision.py and adapt to protocol**

Add to `src/fast_foto_forensics/vision.py`:

```python
class FilenameVisionBackend:
    """Derive lightweight labels and identifiers from filenames."""

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        stem_tokens = [
            token
            for token in Path(observation.source_path).stem.replace("_", "-").split("-")
            if token and not token.isdigit()
        ]
        identifiers = [
            token.upper() for token in stem_tokens if any(char.isdigit() for char in token)
        ]
        labels = [token.lower() for token in stem_tokens if token.isalpha()]
        caption = " ".join(labels) if labels else Path(observation.source_path).stem

        return VisionResult(
            evidence_id=observation.evidence_id,
            source_path=observation.source_path,
            source_sha256=observation.sha256,
            backend_name="filename",
            model_name="filename",
            caption=caption,
            ocr_text="",
            candidate_identifiers=identifiers,
            vendor=None,
            object_class=None,
            detected_labels=labels,
        )
```

- [ ] **Step 4: Add backward-compatible enrich() method**

`pipeline.py` currently calls `vision_backend.enrich(observation)`. To avoid
breaking `pipeline.py` and `test_pipeline.py` before Task 8 rewires them, add a
compatibility method on `FilenameVisionBackend` in `vision.py`:

```python
    def enrich(self, observation: EvidenceObservation) -> EvidenceObservation:
        """Backward-compatible wrapper used by pipeline.py until Task 8."""
        result = self.extract(observation)
        observation.caption = result.caption
        observation.ocr_text = result.ocr_text
        observation.detected_labels = list(result.detected_labels)
        observation.candidate_identifiers = list(result.candidate_identifiers)
        return observation
```

- [ ] **Step 5: Update pipeline.py to import from vision.py**

In `src/fast_foto_forensics/pipeline.py`:

1. Remove the `FilenameVisionBackend` class definition (find the class starting with
   `class FilenameVisionBackend:` and its `enrich` method, through the `return observation` line)
2. Add import: `from fast_foto_forensics.vision import FilenameVisionBackend`
3. The `run_pipeline()` type hint stays `vision_backend: FilenameVisionBackend` for
   now — the compat `enrich()` method keeps the call on line 113 working. Pipeline
   integration comes in Task 8.

- [ ] **Step 6: Run all tests to verify nothing broke**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest -v`
Expected: PASS (all existing tests plus new vision tests)

- [ ] **Step 7: Commit**

```bash
git add src/fast_foto_forensics/vision.py src/fast_foto_forensics/pipeline.py tests/test_vision.py
git commit -m "refactor: move FilenameVisionBackend to vision.py behind VisionBackend protocol"
```

### Task 5: Implement OllamaVisionBackend

**Files:**
- Modify: `src/fast_foto_forensics/vision.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing tests for OllamaVisionBackend**

Append to `tests/test_vision.py`:

```python
import json as json_mod

from fast_foto_forensics.vision import OllamaVisionBackend


class TestOllamaVisionBackend:
    def test_parses_valid_json_response(self, monkeypatch) -> None:
        """Verify the backend parses a well-formed Ollama response."""
        valid_response = {
            "caption": "A blue wireless router.",
            "ocr_text": "WRT54G LINKSYS",
            "candidate_identifiers": ["WRT54G"],
            "vendor": "Linksys",
            "object_class": "wireless router",
            "detected_labels": ["router", "networking"],
        }

        def fake_chat(**kwargs):
            class FakeMessage:
                content = json_mod.dumps(valid_response)
            class FakeResponse:
                message = FakeMessage()
            return FakeResponse()

        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        monkeypatch.setattr(backend, "_call_ollama", fake_chat)

        observation = EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )
        result = backend.extract(observation)
        assert result.caption == "A blue wireless router."
        assert result.candidate_identifiers == ["WRT54G"]
        assert result.backend_name == "ollama"
        assert result.model_name == "qwen2.5vl:7b"

    def test_retries_once_on_bad_json(self, monkeypatch) -> None:
        """First call returns garbage, second returns valid JSON."""
        valid_response = {
            "caption": "A router.",
            "ocr_text": "",
            "candidate_identifiers": [],
            "vendor": "",
            "object_class": "router",
            "detected_labels": ["router"],
        }
        call_count = 0

        def fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            class FakeMessage:
                content = "not json" if call_count == 1 else json_mod.dumps(valid_response)
            class FakeResponse:
                message = FakeMessage()
            return FakeResponse()

        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        monkeypatch.setattr(backend, "_call_ollama", fake_chat)

        observation = EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )
        result = backend.extract(observation)
        assert call_count == 2
        assert result.caption == "A router."

    def test_raises_after_two_failures(self, monkeypatch) -> None:
        """Two consecutive bad JSON responses should raise."""
        def fake_chat(**kwargs):
            class FakeMessage:
                content = "totally not json {{"
            class FakeResponse:
                message = FakeMessage()
            return FakeResponse()

        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        monkeypatch.setattr(backend, "_call_ollama", fake_chat)

        observation = EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )
        with pytest.raises(VisionExtractionError, match="Failed to parse"):
            backend.extract(observation)

    def test_satisfies_vision_backend_protocol(self) -> None:
        assert isinstance(OllamaVisionBackend(), VisionBackend)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestOllamaVisionBackend -v`
Expected: FAIL with `ImportError: cannot import name 'OllamaVisionBackend'`

- [ ] **Step 3: Implement OllamaVisionBackend**

Add to `src/fast_foto_forensics/vision.py`:

```python
import base64
import json
import logging

logger = logging.getLogger(__name__)

_VISION_PROMPT = """\
Examine this image carefully. Return ONLY a JSON object with these fields:
- "caption": a one-sentence description of what you see
- "ocr_text": all visible text, transcribed exactly as it appears
- "candidate_identifiers": list of serial numbers, model numbers, or part numbers found
- "vendor": manufacturer name if identifiable, otherwise ""
- "object_class": general category (e.g. "wireless router", "GPU", "circuit board")
- "detected_labels": list of all readable labels, markings, or stickers"""


class OllamaVisionBackend:
    """Send images to a local Ollama instance for structured extraction."""

    def __init__(self, model: str = "qwen2.5vl:7b") -> None:
        self._model = model

    def _call_ollama(self, **kwargs):
        """Thin wrapper around ollama.chat() for testability."""
        try:
            import ollama
        except ImportError as exc:
            raise VisionExtractionError(
                "ollama package not installed. Install with: pip install ollama>=0.4.0"
            ) from exc
        return ollama.chat(**kwargs)

    def extract(self, observation: EvidenceObservation) -> VisionResult:
        image_path = Path(observation.source_path)
        if not image_path.is_file():
            raise VisionExtractionError(f"Image not found: {image_path}")

        image_bytes = image_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._call_ollama(
                    model=self._model,
                    messages=[
                        {
                            "role": "user",
                            "content": _VISION_PROMPT,
                            "images": [image_b64],
                        }
                    ],
                )
                raw_text = response.message.content
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    raise ValueError("response is not a JSON object")

                return VisionResult(
                    evidence_id=observation.evidence_id,
                    source_path=observation.source_path,
                    source_sha256=observation.sha256,
                    backend_name="ollama",
                    model_name=self._model,
                    caption=parsed.get("caption", ""),
                    ocr_text=parsed.get("ocr_text", ""),
                    candidate_identifiers=parsed.get("candidate_identifiers", []),
                    vendor=parsed.get("vendor") or None,
                    object_class=parsed.get("object_class") or None,
                    detected_labels=parsed.get("detected_labels", []),
                )
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last_error = exc
                logger.warning(
                    "Vision extraction attempt %d failed: %s", attempt + 1, exc
                )
                continue

        raise VisionExtractionError(
            f"Failed to parse vision response after 2 attempts: {last_error}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py -v`
Expected: PASS (all tests including OllamaVisionBackend)

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/vision.py tests/test_vision.py
git commit -m "feat: add OllamaVisionBackend with retry and structured JSON parsing"
```

---

## Chunk 3: Caching and Enrichment Orchestration

### Task 6: Implement extract_with_cache

**Files:**
- Modify: `src/fast_foto_forensics/vision.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing cache tests**

Append to `tests/test_vision.py`:

```python
from pathlib import Path

from fast_foto_forensics.storage import RunStore
from fast_foto_forensics.vision import extract_with_cache


class TestExtractWithCache:
    def _make_observation(self) -> EvidenceObservation:
        return EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )

    def _make_backend(self) -> StaticVisionBackend:
        fixture = VisionResult.from_dict(_sample_vision_dict())
        return StaticVisionBackend(fixtures={"img-001": fixture})

    def test_writes_artifact_on_cache_miss(self, tmp_path: Path) -> None:
        store = RunStore.create(tmp_path, "run-1")
        observation = self._make_observation()
        backend = self._make_backend()

        result = extract_with_cache(observation, backend, store=store)

        assert result.evidence_id == "img-001"
        artifact = store.artifact_path("vision/img-001.json")
        assert artifact.exists()

    def test_reads_artifact_on_cache_hit(self, tmp_path: Path) -> None:
        store = RunStore.create(tmp_path, "run-1")
        observation = self._make_observation()
        backend = self._make_backend()

        # First call writes the cache
        extract_with_cache(observation, backend, store=store)

        # Second call with empty backend should still work (cache hit)
        empty_backend = StaticVisionBackend(fixtures={})
        result = extract_with_cache(observation, empty_backend, store=store)
        assert result.evidence_id == "img-001"

    def test_force_bypasses_cache(self, tmp_path: Path) -> None:
        store = RunStore.create(tmp_path, "run-1")
        observation = self._make_observation()
        backend = self._make_backend()

        extract_with_cache(observation, backend, store=store)

        # Force should call the backend again, so empty backend raises
        empty_backend = StaticVisionBackend(fixtures={})
        with pytest.raises(VisionExtractionError):
            extract_with_cache(observation, empty_backend, store=store, force=True)

    def test_invalidates_cache_on_sha256_mismatch(self, tmp_path: Path) -> None:
        store = RunStore.create(tmp_path, "run-1")
        observation = self._make_observation()
        backend = self._make_backend()

        extract_with_cache(observation, backend, store=store)

        # Change the sha256 — cache should be invalidated
        observation_v2 = self._make_observation()
        observation_v2.sha256 = "different_hash"

        # Empty backend means if cache is used we get a result, if not we get an error
        empty_backend = StaticVisionBackend(fixtures={})
        with pytest.raises(VisionExtractionError):
            extract_with_cache(observation_v2, empty_backend, store=store)

    def test_works_without_store(self) -> None:
        observation = self._make_observation()
        backend = self._make_backend()

        result = extract_with_cache(observation, backend, store=None)
        assert result.evidence_id == "img-001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestExtractWithCache -v`
Expected: FAIL with `ImportError: cannot import name 'extract_with_cache'`

- [ ] **Step 3: Implement extract_with_cache**

Add to `src/fast_foto_forensics/vision.py`:

```python
from fast_foto_forensics.storage import RunStore


def _backend_identity(backend: VisionBackend) -> tuple[str, str]:
    """Return (backend_name, model_name) for cache validation."""
    if hasattr(backend, "_model"):
        return ("ollama", backend._model)
    if isinstance(backend, FilenameVisionBackend):
        return ("filename", "filename")
    if isinstance(backend, StaticVisionBackend):
        return ("static", "static")
    return ("unknown", "unknown")


def extract_with_cache(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> VisionResult:
    """Extract vision data, using cached artifacts when available."""
    if store is not None and not force:
        artifact = store.artifact_path(f"vision/{observation.evidence_id}.json")
        if artifact.exists():
            cached = store.read_json_artifact(f"vision/{observation.evidence_id}.json")
            cached_result = VisionResult.from_dict(cached)
            backend_name, model_name = _backend_identity(backend)
            if (
                cached_result.source_sha256 == observation.sha256
                and cached_result.backend_name == backend_name
                and cached_result.model_name == model_name
            ):
                return cached_result

    result = backend.extract(observation)

    if store is not None:
        store.write_json_artifact(
            f"vision/{observation.evidence_id}.json",
            result.to_dict(),
        )

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestExtractWithCache -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/vision.py tests/test_vision.py
git commit -m "feat: add extract_with_cache with per-observation artifact caching"
```

### Task 7: Implement enrich_single and enrich_observations

**Files:**
- Modify: `src/fast_foto_forensics/vision.py`
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write failing enrichment tests**

Append to `tests/test_vision.py`:

```python
from fast_foto_forensics.vision import enrich_observations, enrich_single


class TestEnrichment:
    def _make_observation(self) -> EvidenceObservation:
        return EvidenceObservation(
            evidence_id="img-001",
            source_path="evidence/router.jpg",
            media_kind="image",
            sha256="abc123",
            order_index=0,
        )

    def _make_backend(self) -> StaticVisionBackend:
        fixture = VisionResult.from_dict(_sample_vision_dict())
        return StaticVisionBackend(fixtures={"img-001": fixture})

    def test_enrich_single_populates_observation_fields(self) -> None:
        observation = self._make_observation()
        backend = self._make_backend()

        enriched, vision_result = enrich_single(observation, backend)

        assert enriched.caption == "A blue wireless router with two antennas."
        assert enriched.ocr_text == "WRT54G LINKSYS"
        assert "WRT54G" in enriched.candidate_identifiers
        assert "linksys" in enriched.detected_labels  # _merge_labels lowercases
        assert "wireless router" in enriched.detected_labels
        assert "router" in enriched.detected_labels

    def test_enrich_observations_returns_parallel_lists(self) -> None:
        observation = self._make_observation()
        backend = self._make_backend()

        enriched_list, results = enrich_observations([observation], backend)

        assert len(enriched_list) == 1
        assert len(results) == 1
        assert enriched_list[0].caption == "A blue wireless router with two antennas."
        assert results[0].evidence_id == "img-001"

    def test_enrich_does_not_duplicate_labels(self) -> None:
        observation = self._make_observation()
        observation.detected_labels = ["router"]  # pre-existing label
        backend = self._make_backend()

        enriched, _ = enrich_single(observation, backend)

        # "router" should appear only once
        assert enriched.detected_labels.count("router") == 1

    def test_enrich_observations_skips_unreadable_images(self) -> None:
        """An image that raises VisionExtractionError should be skipped."""
        observation = self._make_observation()
        empty_backend = StaticVisionBackend(fixtures={})  # will raise for any ID

        enriched_list, results = enrich_observations([observation], empty_backend)

        assert len(enriched_list) == 1  # observation returned unenriched
        assert len(results) == 0  # no vision result for the failed image
        assert enriched_list[0].caption == ""  # still empty — not enriched


class TestCacheCollisionSafety:
    """Verify that two observations with the same filename but different
    evidence_ids do not collide in the artifact cache."""

    def test_same_basename_different_evidence_ids(self, tmp_path: Path) -> None:
        store = RunStore.create(tmp_path, "run-1")
        fixture_a = VisionResult(
            evidence_id="img-001",
            source_path="folderA/photo.jpg",
            source_sha256="aaa",
            backend_name="static",
            model_name="static",
            caption="Photo A",
            ocr_text="",
            candidate_identifiers=[],
            vendor=None,
            object_class=None,
            detected_labels=[],
        )
        fixture_b = VisionResult(
            evidence_id="img-002",
            source_path="folderB/photo.jpg",
            source_sha256="bbb",
            backend_name="static",
            model_name="static",
            caption="Photo B",
            ocr_text="",
            candidate_identifiers=[],
            vendor=None,
            object_class=None,
            detected_labels=[],
        )
        backend = StaticVisionBackend(fixtures={"img-001": fixture_a, "img-002": fixture_b})

        obs_a = EvidenceObservation(
            evidence_id="img-001", source_path="folderA/photo.jpg",
            media_kind="image", sha256="aaa", order_index=0,
        )
        obs_b = EvidenceObservation(
            evidence_id="img-002", source_path="folderB/photo.jpg",
            media_kind="image", sha256="bbb", order_index=1,
        )

        result_a = extract_with_cache(obs_a, backend, store=store)
        result_b = extract_with_cache(obs_b, backend, store=store)

        assert result_a.caption == "Photo A"
        assert result_b.caption == "Photo B"
        # Both cached separately under their evidence_id
        assert store.artifact_path("vision/img-001.json").exists()
        assert store.artifact_path("vision/img-002.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py::TestEnrichment -v`
Expected: FAIL with `ImportError: cannot import name 'enrich_single'`

- [ ] **Step 3: Implement enrich_single and enrich_observations**

Add to `src/fast_foto_forensics/vision.py`:

```python
def _merge_labels(
    existing: list[str],
    vision_result: VisionResult,
) -> list[str]:
    """Merge vision labels into existing labels, deduplicating by lowercase."""
    seen: set[str] = set()
    merged: list[str] = []
    for label in existing:
        normalized = label.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(label)

    extras: list[str] = list(vision_result.detected_labels)
    if vision_result.vendor:
        extras.append(vision_result.vendor)
    if vision_result.object_class:
        extras.append(vision_result.object_class)

    for label in extras:
        normalized = label.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)
    return merged


def enrich_single(
    observation: EvidenceObservation,
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> tuple[EvidenceObservation, VisionResult]:
    """Extract vision data and map it onto an observation."""
    result = extract_with_cache(observation, backend, store=store, force=force)

    observation.caption = result.caption
    observation.ocr_text = result.ocr_text
    observation.candidate_identifiers = list(result.candidate_identifiers)
    observation.detected_labels = _merge_labels(observation.detected_labels, result)

    return observation, result


def enrich_observations(
    observations: list[EvidenceObservation],
    backend: VisionBackend,
    store: RunStore | None = None,
    force: bool = False,
) -> tuple[list[EvidenceObservation], list[VisionResult]]:
    """Enrich a batch of observations via vision extraction.

    Unreadable images are skipped with a warning; the observation is
    returned unenriched so the pipeline can continue.
    """
    enriched: list[EvidenceObservation] = []
    results: list[VisionResult] = []
    for observation in observations:
        try:
            obs, result = enrich_single(observation, backend, store=store, force=force)
            enriched.append(obs)
            results.append(result)
        except VisionExtractionError:
            logger.warning(
                "Skipping unreadable image %s", observation.source_path
            )
            enriched.append(observation)
    return enriched, results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest tests\test_vision.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/fast_foto_forensics/vision.py tests/test_vision.py
git commit -m "feat: add enrich_single and enrich_observations with label merging"
```

---

## Chunk 4: Pipeline Integration and Cleanup

### Task 8: Update pipeline.py to use vision.py orchestration

**Files:**
- Modify: `src/fast_foto_forensics/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write a test for pipeline using new vision integration**

Add to `tests/test_pipeline.py` (or update existing test):

```python
from fast_foto_forensics.vision import FilenameVisionBackend, VisionBackend

def test_run_pipeline_uses_vision_backend_protocol(tmp_path):
    """Pipeline should accept any VisionBackend, not just FilenameVisionBackend."""
    backend = FilenameVisionBackend()
    assert isinstance(backend, VisionBackend)
```

- [ ] **Step 2: Update run_pipeline to use enrich_observations**

In `src/fast_foto_forensics/pipeline.py`:

1. Update imports:
```python
from fast_foto_forensics.vision import (
    FilenameVisionBackend,
    VisionBackend,
    enrich_observations,
)
```

2. Change `run_pipeline` signature to accept `VisionBackend`:
```python
def run_pipeline(
    input_path: Path,
    output_root: Path,
    run_label: str,
    vision_backend: VisionBackend,
    search_provider: SearchProvider,
    synthesis_backend: SynthesisBackend,
) -> RunResult:
```

3. Replace the vision call (line 113):
```python
# Before:
observations = [vision_backend.enrich(observation) for observation in ingest_path(input_path)]

# After:
raw_observations = ingest_path(input_path)
observations, _vision_results = enrich_observations(
    raw_observations, vision_backend, store=store
)
```

Note: `store` is created on line 112, so move the `store = RunStore.create(...)` line before the vision call.

- [ ] **Step 3: Run all tests**

Run: `cmd /c scripts\uvw.cmd run --extra dev pytest -v`
Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
git add src/fast_foto_forensics/pipeline.py tests/test_pipeline.py
git commit -m "refactor: pipeline uses VisionBackend protocol and enrich_observations"
```

### Task 9: Update MODEL_SOURCES.md

**Files:**
- Modify: `models/MODEL_SOURCES.md`

- [ ] **Step 1: Add Ollama section to MODEL_SOURCES.md**

Add a section at the top of `models/MODEL_SOURCES.md` noting that Ollama is the primary delivery mechanism:

```markdown
## Primary: Ollama (recommended)

The recommended way to run vision models is via Ollama. No manual weight
downloads required.

    ollama pull qwen2.5vl:7b

The `OllamaVisionBackend` in `src/fast_foto_forensics/vision.py` connects
to the local Ollama server automatically. Install the Python client with:

    pip install ollama>=0.4.0

Or via the project extra:

    uv sync --extra vision_ollama
```

- [ ] **Step 2: Commit**

```bash
git add models/MODEL_SOURCES.md
git commit -m "docs: note Ollama as primary vision model delivery mechanism"
```

---

### Task 10: Add Ollama integration test

**Files:**
- Test: `tests/test_vision.py`

- [ ] **Step 1: Write slow integration test**

Append to `tests/test_vision.py`. This test requires Ollama running locally with
`qwen2.5vl:7b` pulled. It will be skipped in CI.

```python
import pytest

try:
    import ollama as _ollama_mod
    _HAS_OLLAMA = True
except ImportError:
    _HAS_OLLAMA = False


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_OLLAMA, reason="ollama package not installed")
class TestOllamaIntegration:
    def test_round_trip_with_real_model(self, tmp_path: Path) -> None:
        """Send a tiny test image to Ollama and verify structured output."""
        # Create a minimal valid JPEG (1x1 red pixel)
        import struct
        # Minimal JPEG: SOI + APP0 + DQT + SOF0 + DHT + SOS + EOI
        # For simplicity, use a small PNG instead via raw bytes
        # or just write a tiny file the model can attempt to read
        test_image = tmp_path / "test.jpg"
        test_image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9")

        observation = EvidenceObservation(
            evidence_id="integration-test",
            source_path=str(test_image),
            media_kind="image",
            sha256="integration",
            order_index=0,
        )
        backend = OllamaVisionBackend(model="qwen2.5vl:7b")
        try:
            result = backend.extract(observation)
            assert isinstance(result, VisionResult)
            assert result.backend_name == "ollama"
            assert result.evidence_id == "integration-test"
        except VisionExtractionError:
            # Model may not parse a malformed JPEG, but we verify the round-trip
            pytest.skip("Ollama returned unparseable response for test image")
```

- [ ] **Step 2: Add slow marker to pytest config**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = ["slow: marks tests that require external services (deselect with '-m \"not slow\"')"]
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_vision.py pyproject.toml
git commit -m "test: add Ollama integration test with slow marker"
```

---

## Import Management Note

The test file `tests/test_vision.py` grows incrementally across tasks. After each
task, consolidate the import block at the top of the file so Ruff's isort rules
(`I`) pass. The final import block should look approximately like:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fast_foto_forensics.models import EvidenceObservation, VisionResult
from fast_foto_forensics.storage import RunStore
from fast_foto_forensics.vision import (
    FilenameVisionBackend,
    OllamaVisionBackend,
    StaticVisionBackend,
    VisionBackend,
    VisionExtractionError,
    enrich_observations,
    enrich_single,
    extract_with_cache,
)
```

---

## Final Verification

- [ ] **Step 1: Run the full test suite**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev pytest -v
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run Ruff**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev ruff check --no-cache .
```

Expected: PASS.

- [ ] **Step 3: Run mypy**

Run:

```bash
cmd /c scripts\uvw.cmd run --extra dev mypy src
```

Expected: PASS (or known pre-existing issues only).

- [ ] **Step 4: Verify Ollama integration test manually (optional)**

If Ollama is running locally with `qwen2.5vl:7b`:

```bash
cmd /c scripts\uvw.cmd run --extra dev --extra vision_ollama pytest tests\test_vision.py -v -m slow
```

- [ ] **Step 5: Commit any final fixes**

Stage only files that were changed during verification fixes:

```bash
git add src/fast_foto_forensics/vision.py src/fast_foto_forensics/models.py src/fast_foto_forensics/pipeline.py tests/test_vision.py pyproject.toml models/MODEL_SOURCES.md
git commit -m "chore: final cleanup for vision module"
```
