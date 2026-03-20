"""Tests for schema-first synthesis."""

from __future__ import annotations

import json

import pytest

from fast_foto_forensics.models import EvidenceObservation, SearchHit, SynthesisArtifact
from fast_foto_forensics.synthesis import (
    OllamaDatasheetSynthesisBackend,
    RemoteDatasheetSynthesisBackend,
    ReplaySynthesisBackend,
    SynthesisError,
    SynthesisFailure,
    _backfill_citations,
    _repair_json,
    synthesize_item,
    synthesize_item_with_artifact,
)


def _make_fake_chat(responses: list[str]):
    """Return a fake Ollama call that yields *responses* in order."""
    call_count = [0]
    captured_kwargs: list[dict[str, object]] = []

    def fake_chat(**kwargs):
        idx = call_count[0]
        call_count[0] += 1
        captured_kwargs.append(kwargs)

        class FakeMessage:
            content = responses[idx] if idx < len(responses) else ""

        class FakeResponse:
            message = FakeMessage()

        return FakeResponse()

    fake_chat.call_count = call_count
    fake_chat.captured_kwargs = captured_kwargs
    return fake_chat


def test_json_synthesis_retries_when_first_payload_is_invalid() -> None:
    """Invalid model output should trigger one repair attempt."""
    backend = ReplaySynthesisBackend(
        responses=[
            "not-json-at-all",
            """
            {
              "probable_identity": "Linksys WRT54G",
              "object_class": "router",
              "likely_function": "Wireless router",
              "manufacturer": "Linksys",
              "model_identifiers": ["WRT54G"],
              "year_range": "2002-2005",
              "country_or_region": "United States",
              "security_findings": ["Legacy firmware may have known weaknesses"],
              "confidence": 0.88,
              "evidence_refs": ["img-1"],
              "search_hit_refs": ["hit-1"],
              "open_questions": ["Confirm hardware revision"]
            }
            """,
        ]
    )

    result = synthesize_item(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        backend=backend,
    )

    assert result.probable_identity == "Linksys WRT54G"
    assert backend.calls == 2


def test_json_synthesis_retries_when_required_fields_are_missing() -> None:
    """Boundary validation should reject incomplete schema-mode responses."""
    backend = ReplaySynthesisBackend(
        responses=[
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "model_identifiers": ["WRT54G"],
                }
            ),
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "manufacturer": "Linksys",
                    "model_identifiers": ["WRT54G"],
                    "year_range": "2002-2005",
                    "country_or_region": "United States",
                    "security_findings": [],
                    "confidence": 0.88,
                    "evidence_refs": ["img-1"],
                    "search_hit_refs": ["hit-1"],
                    "open_questions": [],
                }
            ),
        ]
    )

    result = synthesize_item(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
        backend=backend,
    )

    assert result.manufacturer == "Linksys"
    assert backend.calls == 2


def test_ollama_backend_uses_schema_mode_and_preserves_raw_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama datasheet synthesis should request schema mode and return provenance."""
    backend = OllamaDatasheetSynthesisBackend(model="qwen2.5vl:7b")
    fake_chat = _make_fake_chat(
        [
            json.dumps(
                {
                    "probable_identity": "Linksys WRT54G",
                    "object_class": "router",
                    "likely_function": "Wireless router",
                    "manufacturer": "Linksys",
                    "model_identifiers": ["WRT54G"],
                    "year_range": "2002-2005",
                    "country_or_region": "United States",
                    "security_findings": [],
                    "confidence": 0.88,
                    "evidence_refs": ["img-1"],
                    "search_hit_refs": ["hit-1"],
                    "open_questions": [],
                }
            )
        ]
    )
    monkeypatch.setattr(backend, "_call_ollama", fake_chat)

    artifact = backend.generate(
        observations=[
            EvidenceObservation(
                evidence_id="img-1",
                source_path="rack-a/router.jpg",
                media_kind="image",
                sha256="abc",
                order_index=0,
                caption="A blue Linksys router.",
                ocr_text="WRT54G",
                detected_labels=["router"],
                candidate_identifiers=["WRT54G"],
            )
        ],
        hits=[
            SearchHit(
                hit_id="hit-1",
                provider="duckduckgo",
                query="WRT54G release date",
                title="Linksys WRT54G",
                snippet="The Linksys WRT54G is a wireless router series.",
                url="https://example.com/wrt54g",
            )
        ],
    )

    assert isinstance(artifact, SynthesisArtifact)
    assert artifact.backend_name == "ollama"
    assert artifact.model_name == "qwen2.5vl:7b"
    assert artifact.schema_name == "ItemDatasheet"
    assert artifact.prompt_text
    assert "Analyze the evidence observations and search hits" in artifact.prompt_text
    assert artifact.raw_payload

    request = fake_chat.captured_kwargs[0]
    assert request["model"] == "qwen2.5vl:7b"
    assert request["stream"] is False
    assert isinstance(request["format"], dict)
    assert request["format"]["type"] == "object"
    assert "manufacturer" in request["format"]["required"]


def test_ollama_backend_gives_actionable_error_when_package_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional dependency should tell the operator how to install it."""
    backend = OllamaDatasheetSynthesisBackend(model="qwen2.5vl:7b")

    def fake_call_ollama(**kwargs):
        raise RuntimeError(
            "ollama package not installed. Install with: "
            "pip install fast-foto-forensics[vision_ollama]"
        )

    monkeypatch.setattr(backend, "_call_ollama", fake_call_ollama)

    with pytest.raises(RuntimeError, match="vision_ollama"):
        backend.generate(observations=[], hits=[])


def test_remote_backend_raises_on_empty_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An API response with no choices should raise SynthesisError."""
    backend = RemoteDatasheetSynthesisBackend(
        model="gpt-4o-mini", api_key="test-key", api_base="https://test.example.com/v1"
    )
    monkeypatch.setattr(
        backend, "_call_remote", lambda msgs, fmt: {"choices": []}
    )

    with pytest.raises(SynthesisError, match="no choices"):
        backend.generate(observations=[], hits=[])


# ---------------------------------------------------------------------------
# JSON repair (#36)
# ---------------------------------------------------------------------------

_VALID_DATASHEET = {
    "probable_identity": "Linksys WRT54G",
    "object_class": "router",
    "likely_function": "Wireless router",
    "manufacturer": "Linksys",
    "model_identifiers": ["WRT54G"],
}

_OBS = EvidenceObservation(
    evidence_id="img-1",
    source_path="rack-a/router.jpg",
    media_kind="image",
    sha256="abc",
    order_index=0,
    caption="A blue Linksys router.",
    ocr_text="WRT54G",
    detected_labels=["router"],
    candidate_identifiers=["WRT54G"],
)

_HIT = SearchHit(
    hit_id="hit-1",
    provider="duckduckgo",
    query="WRT54G",
    title="Linksys WRT54G",
    snippet="The WRT54G is a wireless router series.",
    url="https://example.com/wrt54g",
)


def test_repair_json_strips_trailing_commas() -> None:
    """Trailing commas before } or ] should be removed."""
    raw = '{"a": 1, "b": [2, 3,],}'
    repaired = _repair_json(raw)
    assert json.loads(repaired) == {"a": 1, "b": [2, 3]}


def test_repair_json_strips_code_fences() -> None:
    """Markdown code fences should be stripped."""
    raw = '```json\n{"a": 1}\n```'
    repaired = _repair_json(raw)
    assert json.loads(repaired) == {"a": 1}


def test_repair_json_fixes_single_quotes() -> None:
    """Single-quoted JSON should be converted to double quotes."""
    raw = "{'a': 1, 'b': 'hello'}"
    repaired = _repair_json(raw)
    assert json.loads(repaired) == {"a": 1, "b": "hello"}


def test_repair_json_closes_truncated_payload() -> None:
    """Truncated JSON (missing closing braces) should be patched."""
    raw = '{"a": 1, "b": [2, 3]'
    repaired = _repair_json(raw)
    assert json.loads(repaired) == {"a": 1, "b": [2, 3]}


def test_repair_json_passes_valid_json_through() -> None:
    """Valid JSON should be returned unchanged."""
    raw = '{"a": 1}'
    assert _repair_json(raw) == raw


def test_backfill_citations_fills_empty_refs() -> None:
    """Missing evidence_refs and search_hit_refs should be filled from inputs."""
    data = dict(_VALID_DATASHEET)
    result = _backfill_citations(data, [_OBS], [_HIT])
    assert result["evidence_refs"] == ["img-1"]
    assert result["search_hit_refs"] == ["hit-1"]


def test_backfill_citations_preserves_existing_refs() -> None:
    """Existing evidence_refs should not be overwritten."""
    data = dict(_VALID_DATASHEET, evidence_refs=["custom-1"], search_hit_refs=["custom-2"])
    result = _backfill_citations(data, [_OBS], [_HIT])
    assert result["evidence_refs"] == ["custom-1"]
    assert result["search_hit_refs"] == ["custom-2"]


def test_backfill_citations_clamps_confidence() -> None:
    """Confidence values outside [0, 1] should be clamped."""
    data = dict(_VALID_DATASHEET, confidence=1.5)
    result = _backfill_citations(data, [], [])
    assert result["confidence"] == 1.0

    data2 = dict(_VALID_DATASHEET, confidence=-0.3)
    result2 = _backfill_citations(data2, [], [])
    assert result2["confidence"] == 0.0


def test_synthesize_repairs_trailing_comma_payload() -> None:
    """A payload with trailing commas should be repaired and accepted."""
    # Valid datasheet but with trailing commas
    raw = json.dumps(
        {
            **_VALID_DATASHEET,
            "confidence": 0.88,
            "evidence_refs": ["img-1"],
            "search_hit_refs": ["hit-1"],
            "open_questions": [],
        }
    )
    # Inject trailing commas
    broken = raw.replace("],", "],  ,").replace("},", "},  ,")
    # It shouldn't be valid JSON anymore
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)

    backend = ReplaySynthesisBackend(responses=[broken])
    datasheet, artifact = synthesize_item_with_artifact([_OBS], [_HIT], backend)

    assert datasheet.probable_identity == "Linksys WRT54G"
    assert artifact.accepted is True
    assert backend.calls == 1  # No retry needed — repair fixed it


def test_synthesize_backfills_missing_citations() -> None:
    """When the model omits evidence_refs, they should be backfilled."""
    raw = json.dumps(
        {
            **_VALID_DATASHEET,
            "confidence": 0.75,
            # No evidence_refs or search_hit_refs
        }
    )

    backend = ReplaySynthesisBackend(responses=[raw])
    datasheet, artifact = synthesize_item_with_artifact([_OBS], [_HIT], backend)

    assert datasheet.evidence_refs == ["img-1"]
    assert datasheet.search_hit_refs == ["hit-1"]
    assert artifact.accepted is True
    assert artifact.prompt_text


def test_synthesize_gives_up_after_two_bad_payloads() -> None:
    """Two consecutive unparseable payloads should raise SynthesisFailure."""
    backend = ReplaySynthesisBackend(responses=["garbage", "still garbage"])

    with pytest.raises(SynthesisFailure) as exc_info:
        synthesize_item_with_artifact([_OBS], [_HIT], backend)

    assert exc_info.value.artifact.accepted is False
    assert exc_info.value.artifact.attempt_count == 2
    assert "invalid JSON" in (exc_info.value.artifact.last_error or "")


# ---------------------------------------------------------------------------
# Remote synthesis backend (#35)
# ---------------------------------------------------------------------------


def _openai_response(content: str) -> dict:
    """Build a minimal OpenAI-compatible chat completions response."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "model": "gpt-4o-mini",
    }


def test_remote_backend_generates_artifact_from_openai_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The remote backend should parse an OpenAI-format response into provenance."""
    backend = RemoteDatasheetSynthesisBackend(
        model="gpt-4o-mini", api_key="test-key", api_base="https://test.example.com/v1"
    )
    content = json.dumps({**_VALID_DATASHEET, "confidence": 0.9})
    monkeypatch.setattr(backend, "_call_remote", lambda msgs, fmt: _openai_response(content))

    artifact = backend.generate(observations=[_OBS], hits=[_HIT])

    assert isinstance(artifact, SynthesisArtifact)
    assert artifact.backend_name == "remote"
    assert artifact.model_name == "gpt-4o-mini"
    assert artifact.schema_name == "ItemDatasheet"
    assert json.loads(artifact.raw_payload)["probable_identity"] == "Linksys WRT54G"


def test_remote_backend_normalizes_code_fenced_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Markdown fences in the remote response should be stripped."""
    backend = RemoteDatasheetSynthesisBackend(
        model="gpt-4o-mini", api_key="test-key", api_base="https://test.example.com/v1"
    )
    fenced = "```json\n" + json.dumps(_VALID_DATASHEET) + "\n```"
    monkeypatch.setattr(backend, "_call_remote", lambda msgs, fmt: _openai_response(fenced))

    artifact = backend.generate(observations=[_OBS], hits=[_HIT])

    parsed = json.loads(artifact.raw_payload)
    assert parsed["probable_identity"] == "Linksys WRT54G"


def test_remote_backend_raises_on_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing API key should raise SynthesisError with actionable message."""
    monkeypatch.delenv("FAST_FOTO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = RemoteDatasheetSynthesisBackend(model="gpt-4o-mini")

    with pytest.raises(SynthesisError, match="API key"):
        backend.generate(observations=[_OBS], hits=[_HIT])


def test_remote_backend_resolves_env_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_resolve_config should pick up environment variables."""
    monkeypatch.setenv("FAST_FOTO_API_KEY", "env-key-123")
    monkeypatch.setenv("FAST_FOTO_API_BASE", "https://custom.example.com/v1")
    backend = RemoteDatasheetSynthesisBackend(model="gpt-4o-mini")

    base, key = backend._resolve_config()

    assert base == "https://custom.example.com/v1"
    assert key == "env-key-123"


def test_remote_backend_prefers_explicit_args_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit constructor args should take priority over env vars."""
    monkeypatch.setenv("FAST_FOTO_API_KEY", "env-key")
    monkeypatch.setenv("FAST_FOTO_API_BASE", "https://env.example.com/v1")
    backend = RemoteDatasheetSynthesisBackend(
        model="gpt-4o-mini",
        api_key="explicit-key",
        api_base="https://explicit.example.com/v1",
    )

    base, key = backend._resolve_config()

    assert base == "https://explicit.example.com/v1"
    assert key == "explicit-key"


def test_remote_backend_falls_back_to_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENAI_API_KEY should work as a fallback when FAST_FOTO_API_KEY is unset."""
    monkeypatch.delenv("FAST_FOTO_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")
    backend = RemoteDatasheetSynthesisBackend(model="gpt-4o-mini")

    _base, key = backend._resolve_config()

    assert key == "openai-fallback-key"


def test_remote_backend_end_to_end_with_repair_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full repair/validate/retry loop should work with the remote backend."""
    backend = RemoteDatasheetSynthesisBackend(
        model="gpt-4o-mini", api_key="test-key", api_base="https://test.example.com/v1"
    )
    content = json.dumps({
        **_VALID_DATASHEET,
        "confidence": 0.85,
    })
    monkeypatch.setattr(backend, "_call_remote", lambda msgs, fmt: _openai_response(content))

    datasheet, artifact = synthesize_item_with_artifact([_OBS], [_HIT], backend)

    assert datasheet.probable_identity == "Linksys WRT54G"
    assert datasheet.evidence_refs == ["img-1"]  # backfilled
    assert datasheet.search_hit_refs == ["hit-1"]  # backfilled
    assert artifact.accepted is True
    assert artifact.backend_name == "remote"
