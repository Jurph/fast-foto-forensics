"""Tests for the fff command-line interface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fast_foto_forensics.main import main
from fast_foto_forensics.vision import OllamaVisionBackend


def test_cli_run_command_creates_run_directory(capsys) -> None:
    """The run subcommand should execute the pipeline and print a summary."""
    input_dir = Path(".tmp") / "cli-case"
    output_dir = Path(".tmp") / "cli-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    exit_code = main(
        ["run", str(input_dir), "--output", str(output_dir), "--run-label", "cli-demo"]
    )

    assert exit_code == 0
    assert (output_dir / "cli-demo" / "reports" / "report.md").exists()

    captured = capsys.readouterr().out
    assert "Run OK" in captured
    assert "Images processed" in captured
    assert "Identified items" in captured
    assert "Report" in captured


def test_cli_render_and_tag_commands_rebuild_artifacts() -> None:
    """Render and tag should recreate report and sidecars from stored artifacts."""
    input_dir = Path(".tmp") / "cli-render-case"
    output_dir = Path(".tmp") / "cli-render-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = input_dir / "001-wrt54g-router.jpg"
    image_path.write_bytes(b"router")

    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "render-demo"])
        == 0
    )

    run_dir = output_dir / "render-demo"
    report_path = run_dir / "reports" / "report.md"
    sidecar_path = image_path.with_suffix(".jpg.fff-tags.json")
    report_path.unlink()
    sidecar_path.unlink()

    assert main(["render", str(run_dir)]) == 0
    assert main(["tag", str(run_dir)]) == 0

    assert report_path.exists()
    assert sidecar_path.exists()


def test_cli_compose_command_writes_summary() -> None:
    """Compose should merge the identities from multiple runs into one summary."""
    input_dir = Path(".tmp") / "cli-compose-case"
    output_dir = Path(".tmp") / "cli-compose-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "compose-a"]) == 0
    )
    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "compose-b"]) == 0
    )

    composed_path = output_dir / "combined.md"

    assert (
        main(
            [
                "compose",
                str(output_dir / "compose-a"),
                str(output_dir / "compose-b"),
                "--output",
                str(composed_path),
            ]
        )
        == 0
    )

    assert composed_path.exists()
    assert "Linksys WRT54G" in composed_path.read_text(encoding="utf-8")


def test_cli_run_with_ollama_backend_flag() -> None:
    """--vision-backend=ollama should select OllamaVisionBackend."""
    input_dir = Path(".tmp") / "cli-ollama-case"
    output_dir = Path(".tmp") / "cli-ollama-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    # Patch OllamaVisionBackend.extract to behave like FilenameVisionBackend
    # so we don't need a real Ollama server
    from fast_foto_forensics.vision import FilenameVisionBackend

    filename_backend = FilenameVisionBackend()
    with patch.object(OllamaVisionBackend, "extract", side_effect=filename_backend.extract):
        exit_code = main(
            [
                "run",
                str(input_dir),
                "--output",
                str(output_dir),
                "--run-label",
                "ollama-demo",
                "--vision-backend",
                "ollama",
            ]
        )

    assert exit_code == 0
    assert (output_dir / "ollama-demo" / "reports" / "report.md").exists()


def test_cli_run_partial_failure_shows_warning(capsys) -> None:
    """When synthesis fails, the summary should show PARTIAL and list the failure."""
    from dataclasses import dataclass

    from fast_foto_forensics.models import EvidenceObservation, SearchHit
    from fast_foto_forensics.synthesis import SynthesisBackend

    @dataclass(slots=True)
    class FailingSynthesisBackend:
        def generate(
            self,
            observations: list[EvidenceObservation],
            hits: list[SearchHit],
            previous_error: str | None = None,
        ) -> str:
            raise RuntimeError("model crashed")

    input_dir = Path(".tmp") / "cli-partial-case"
    output_dir = Path(".tmp") / "cli-partial-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    # Patch HeuristicSynthesisBackend to use our failing one
    with patch(
        "fast_foto_forensics.cli.HeuristicSynthesisBackend",
        return_value=FailingSynthesisBackend(),
    ):
        exit_code = main(
            ["run", str(input_dir), "--output", str(output_dir), "--run-label", "partial-demo"]
        )

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "PARTIAL" in captured
    assert "Failures" in captured
    assert "synthesis" in captured


def test_cli_scan_prints_table(capsys) -> None:
    """The scan subcommand should print an inventory table."""
    input_dir = Path(".tmp") / "cli-scan-case"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "tp-link-OC200-router.jpg").write_bytes(b"router")
    (input_dir / "cisco-SG300-switch.jpg").write_bytes(b"switch")

    exit_code = main(["scan", str(input_dir)])
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert "tp-link-OC200-router.jpg" in captured
    assert "cisco-SG300-switch.jpg" in captured


def test_cli_scan_json_format(capsys) -> None:
    """The scan --format=json subcommand should output parseable JSON."""
    import json

    input_dir = Path(".tmp") / "cli-scan-json-case"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "tp-link-OC200-router.jpg").write_bytes(b"router")

    exit_code = main(["scan", str(input_dir), "--format", "json"])
    assert exit_code == 0

    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["filename"] == "tp-link-OC200-router.jpg"
    assert "model_no" in rows[0]
    assert "serial" in rows[0]


def test_cli_scan_csv_format(capsys) -> None:
    """The scan --format=csv subcommand should output CSV with headers."""
    input_dir = Path(".tmp") / "cli-scan-csv-case"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "device-A.jpg").write_bytes(b"a")

    exit_code = main(["scan", str(input_dir), "--format", "csv"])
    assert exit_code == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].strip() == "filename,function,manufacturer,model_no,serial"
    assert "device-A.jpg" in lines[1]
