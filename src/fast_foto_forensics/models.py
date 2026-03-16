"""Core data contracts for Fast Foto Forensics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string if provided")
    return value.strip() or None


def _require_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def tokenize_text(*values: str) -> list[str]:
    """Tokenize human-readable strings into reusable lowercase keywords."""
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for chunk in re.split(r"[^A-Za-z0-9]+", value.lower()):
            if len(chunk) < 2:
                continue
            if chunk in seen:
                continue
            seen.add(chunk)
            tokens.append(chunk)
    return tokens


@dataclass(slots=True)
class EvidenceObservation:
    """A normalized view of one image or document page."""

    evidence_id: str
    source_path: str
    media_kind: str
    sha256: str
    order_index: int
    caption: str = ""
    ocr_text: str = ""
    detected_labels: list[str] = field(default_factory=list)
    candidate_identifiers: list[str] = field(default_factory=list)
    serial_numbers: list[str] = field(default_factory=list)
    vendor: str = ""
    object_class: str = ""
    analyst_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceObservation:
        """Rebuild an observation from persisted JSON-friendly data."""
        return cls(
            evidence_id=_require_str(data, "evidence_id"),
            source_path=_require_str(data, "source_path"),
            media_kind=_require_str(data, "media_kind"),
            sha256=_require_str(data, "sha256"),
            order_index=int(data.get("order_index", 0)),
            caption=_optional_str(data, "caption") or "",
            ocr_text=_optional_str(data, "ocr_text") or "",
            detected_labels=(
                _require_list(data, "detected_labels") if "detected_labels" in data else []
            ),
            candidate_identifiers=(
                _require_list(data, "candidate_identifiers")
                if "candidate_identifiers" in data
                else []
            ),
            serial_numbers=(
                _require_list(data, "serial_numbers")
                if "serial_numbers" in data
                else []
            ),
            vendor=_optional_str(data, "vendor") or "",
            object_class=_optional_str(data, "object_class") or "",
            analyst_hints=_require_list(data, "analyst_hints") if "analyst_hints" in data else [],
        )


@dataclass(slots=True)
class VisionResult:
    """Structured output from a vision extraction backend."""

    evidence_id: str
    source_path: str
    source_sha256: str
    backend_name: str
    model_name: str
    caption: str
    ocr_text: str
    candidate_identifiers: list[str] = field(default_factory=list)
    serial_numbers: list[str] = field(default_factory=list)
    vendor: str | None = None
    object_class: str | None = None
    detected_labels: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert the result into a JSON-friendly dictionary."""
        return {
            "evidence_id": self.evidence_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "backend_name": self.backend_name,
            "model_name": self.model_name,
            "caption": self.caption,
            "ocr_text": self.ocr_text,
            "candidate_identifiers": list(self.candidate_identifiers),
            "serial_numbers": list(self.serial_numbers),
            "vendor": self.vendor,
            "object_class": self.object_class,
            "detected_labels": list(self.detected_labels),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisionResult:
        """Rebuild a vision result from persisted JSON-friendly data."""
        return cls(
            evidence_id=_require_str(data, "evidence_id"),
            source_path=_require_str(data, "source_path"),
            source_sha256=_require_str(data, "source_sha256"),
            backend_name=_require_str(data, "backend_name"),
            model_name=_require_str(data, "model_name"),
            caption=_require_str(data, "caption"),
            ocr_text=_optional_str(data, "ocr_text") or "",
            candidate_identifiers=(
                _require_list(data, "candidate_identifiers")
                if "candidate_identifiers" in data
                else []
            ),
            serial_numbers=(
                _require_list(data, "serial_numbers")
                if "serial_numbers" in data
                else []
            ),
            vendor=_optional_str(data, "vendor"),
            object_class=_optional_str(data, "object_class"),
            detected_labels=_require_list(data, "detected_labels")
            if "detected_labels" in data
            else [],
            confidence=float(data.get("confidence", 0.0)),
        )


@dataclass(slots=True)
class SearchHit:
    """A normalized search result."""

    hit_id: str
    provider: str
    query: str
    title: str
    snippet: str
    url: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchHit:
        """Rebuild a search hit from persisted JSON-friendly data."""
        return cls(
            hit_id=_require_str(data, "hit_id"),
            provider=_require_str(data, "provider"),
            query=_require_str(data, "query"),
            title=_require_str(data, "title"),
            snippet=_require_str(data, "snippet"),
            url=_require_str(data, "url"),
        )


@dataclass(slots=True)
class QueryCandidate:
    """A possible web query with score and provenance."""

    text: str
    provenance: list[str]
    score: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryCandidate:
        """Rebuild a query candidate from persisted JSON-friendly data."""
        return cls(
            text=_require_str(data, "text"),
            provenance=_require_list(data, "provenance"),
            score=float(data.get("score", 0.0)),
        )


@dataclass(slots=True)
class QueryPlan:
    """A capped set of ranked search queries."""

    selected_queries: list[QueryCandidate]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryPlan:
        """Rebuild a query plan from persisted JSON-friendly data."""
        value = data.get("selected_queries", [])
        if not isinstance(value, list):
            raise ValueError("selected_queries must be a list")
        return cls(
            selected_queries=[
                QueryCandidate.from_dict(item) for item in value if isinstance(item, dict)
            ]
        )


@dataclass(slots=True)
class ImageTagSet:
    """Structured tags that can be written beside an image."""

    tags: list[str]
    caption: str
    search_terms: list[str]


@dataclass(slots=True)
class EvidenceCluster:
    """A lightweight grouping of related observations."""

    cluster_id: str
    evidence_refs: list[str]
    shared_identifiers: list[str]
    source_roots: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceCluster:
        """Rebuild an evidence cluster from persisted JSON-friendly data."""
        return cls(
            cluster_id=_require_str(data, "cluster_id"),
            evidence_refs=_require_list(data, "evidence_refs"),
            shared_identifiers=_require_list(data, "shared_identifiers")
            if "shared_identifiers" in data
            else [],
            source_roots=_require_list(data, "source_roots") if "source_roots" in data else [],
        )


@dataclass(slots=True)
class ItemDatasheet:
    """A structured summary of a likely identified object."""

    probable_identity: str
    object_class: str
    likely_function: str
    manufacturer: str
    model_identifiers: list[str]
    year_range: str | None = None
    country_or_region: str | None = None
    security_findings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    search_hit_refs: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemDatasheet:
        """Validate a dictionary payload and rebuild a datasheet instance."""
        if not isinstance(data, dict):
            raise ValueError("datasheet payload must be an object")
        return cls(
            probable_identity=_require_str(data, "probable_identity"),
            object_class=_require_str(data, "object_class"),
            likely_function=_require_str(data, "likely_function"),
            manufacturer=_require_str(data, "manufacturer"),
            model_identifiers=_require_list(data, "model_identifiers"),
            year_range=_optional_str(data, "year_range"),
            country_or_region=_optional_str(data, "country_or_region"),
            security_findings=_require_list(data, "security_findings")
            if "security_findings" in data
            else [],
            confidence=float(data.get("confidence", 0.0)),
            evidence_refs=_require_list(data, "evidence_refs") if "evidence_refs" in data else [],
            search_hit_refs=(
                _require_list(data, "search_hit_refs") if "search_hit_refs" in data else []
            ),
            open_questions=(
                _require_list(data, "open_questions") if "open_questions" in data else []
            ),
        )

    @classmethod
    def from_json(cls, raw_payload: str) -> ItemDatasheet:
        """Parse and validate an LLM-style JSON payload."""
        try:
            data = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON payload") from exc
        return cls.from_dict(data)
