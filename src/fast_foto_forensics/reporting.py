"""Markdown reporting for structured evidence dossiers."""

from __future__ import annotations

from fast_foto_forensics.models import EvidenceObservation, ItemDatasheet, SearchHit


def render_item_dossier(
    datasheet: ItemDatasheet,
    hits: list[SearchHit],
    observations: list[EvidenceObservation],
) -> str:
    """Render a single datasheet and its supporting evidence as Markdown."""
    lines = [
        f"# {datasheet.probable_identity}",
        "",
        "## Probable Identity",
        datasheet.probable_identity,
        "",
        "## Summary",
        f"- Object class: {datasheet.object_class}",
        f"- Likely function: {datasheet.likely_function}",
        f"- Manufacturer: {datasheet.manufacturer}",
    ]
    if datasheet.year_range:
        lines.append(f"- Year range: {datasheet.year_range}")
    if datasheet.country_or_region:
        lines.append(f"- Country or region: {datasheet.country_or_region}")
    lines.extend(
        [
            "",
            "## Evidence",
        ]
    )
    for observation in observations:
        lines.append(f"- {observation.evidence_id}: {observation.source_path}")
        if observation.caption:
            lines.append(f"  - Caption: {observation.caption}")
        if observation.ocr_text:
            lines.append(f"  - OCR: {observation.ocr_text}")

    lines.extend(
        [
            "",
            "## Search Hits",
        ]
    )
    for hit in hits:
        lines.append(f"- Query: {hit.query}")
        lines.append(f"  - Title: {hit.title}")
        lines.append(f"  - Snippet: {hit.snippet}")
        lines.append(f"  - URL: {hit.url}")

    lines.extend(
        [
            "",
            "## Open Questions",
        ]
    )
    for question in datasheet.open_questions:
        lines.append(f"- {question}")
    return "\n".join(lines) + "\n"


def render_composed_summary(run_summaries: list[tuple[str, list[ItemDatasheet]]]) -> str:
    """Render a compact Markdown view across multiple prior runs."""
    lines = [
        "# Fast Foto Forensics Composition",
        "",
        "## Runs",
    ]
    for run_label, datasheets in run_summaries:
        if not datasheets:
            lines.append(f"- {run_label}: no datasheets found")
            continue
        identities = ", ".join(datasheet.probable_identity for datasheet in datasheets)
        lines.append(f"- {run_label}: {identities}")

    lines.extend(
        [
            "",
            "## Likely Identities",
        ]
    )
    for run_label, datasheets in run_summaries:
        for datasheet in datasheets:
            lines.append(f"- {datasheet.probable_identity} ({run_label})")
            lines.append(f"  - Class: {datasheet.object_class}")
            lines.append(f"  - Manufacturer: {datasheet.manufacturer}")
            lines.append(f"  - Function: {datasheet.likely_function}")
    return "\n".join(lines) + "\n"
